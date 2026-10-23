"""
Perceptual video duplicate detection using keyframe extraction and DCT perceptual hashing.
Finds duplicates even across re-encoding, format changes, resolutions, and minor edits.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .metadata import VideoMetadata, get_video_metadata

try:
    import cv2
    import imagehash
    from PIL import Image
    HAS_PERCEPTUAL_DEPS = True
except ImportError:
    HAS_PERCEPTUAL_DEPS = False

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

logger = logging.getLogger("duplicate_video_finder")

DEFAULT_KEYFRAME_COUNT = 5
DEFAULT_HAMMING_THRESHOLD = 8  # Bits out of 64 (lower = stricter, higher = looser)
DEFAULT_DURATION_TOLERANCE_PCT = 5.0  # Percentage
DEFAULT_DURATION_TOLERANCE_SEC = 4.0  # Seconds
DEFAULT_HASH_ALGO = "dhash"


class DisjointSet:
    """Disjoint Set Union (Union-Find) to cluster duplicate video pairs."""

    def __init__(self):
        self.parent: Dict[Path, Path] = {}

    def find(self, item: Path) -> Path:
        if item not in self.parent:
            self.parent[item] = item
            return item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: Path, b: Path):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a

    def get_clusters(self) -> List[List[Path]]:
        clusters: Dict[Path, List[Path]] = {}
        for item in list(self.parent.keys()):
            root = self.find(item)
            clusters.setdefault(root, []).append(item)
        return [paths for paths in clusters.values() if len(paths) > 1]


def _get_hash_fn(algo: str) -> Callable[[Image.Image], imagehash.ImageHash]:
    algo_lower = (algo or "dhash").lower()
    if algo_lower == "phash":
        return imagehash.phash
    elif algo_lower == "ahash":
        return imagehash.average_hash
    elif algo_lower == "whash":
        return imagehash.whash
    return imagehash.dhash


def extract_video_fingerprint(
    file_path: Path,
    num_keyframes: int = DEFAULT_KEYFRAME_COUNT,
    hash_algo: str = DEFAULT_HASH_ALGO,
    metadata: Optional[VideoMetadata] = None,
) -> Optional[Tuple[VideoMetadata, List[imagehash.ImageHash]]]:
    """
    Extracts evenly spaced keyframes and computes perceptual/difference hash for each.
    Returns (VideoMetadata, [ImageHash, ...]) or None on failure.
    """
    if not HAS_PERCEPTUAL_DEPS:
        return None

    if metadata is None:
        metadata = get_video_metadata(file_path)

    if metadata.duration <= 0.2:
        return None

    hash_fn = _get_hash_fn(hash_algo)

    try:
        cap = cv2.VideoCapture(str(file_path))
        if not cap.isOpened():
            cap.release()
            return None

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

        # Distribute sample points between 10% and 90% of duration
        start_pct = 0.10
        end_pct = 0.90
        step_pct = (end_pct - start_pct) / max(1, (num_keyframes - 1))
        sample_pcts = [start_pct + i * step_pct for i in range(num_keyframes)]

        hashes: List[imagehash.ImageHash] = []

        for pct in sample_pcts:
            ret = False
            frame = None

            # Frame seek is most reliable across diverse video containers
            if total_frames > 0:
                target_frame = max(0, min(total_frames - 1, int(total_frames * pct)))
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()

            # Millisecond seek fallback if frame seek failed
            if not ret or frame is None:
                duration_ms = metadata.duration * 1000.0
                cap.set(cv2.CAP_PROP_POS_MSEC, duration_ms * pct)
                ret, frame = cap.read()

            if ret and frame is not None:
                small_frame = cv2.resize(frame, (128, 128), interpolation=cv2.INTER_AREA)
                rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                h = hash_fn(pil_img)
                hashes.append(h)

        cap.release()

        # Require at least half of the keyframes to consider fingerprint valid
        if len(hashes) >= max(2, num_keyframes // 2):
            return metadata, hashes
        return None

    except Exception as e:
        logger.error(f"Error computing perceptual fingerprint for {file_path}: {e}")
        return None


def are_durations_similar(
    dur1: float,
    dur2: float,
    pct_tolerance: float = DEFAULT_DURATION_TOLERANCE_PCT,
    sec_tolerance: float = DEFAULT_DURATION_TOLERANCE_SEC,
) -> bool:
    """Checks if two durations match within percentage or absolute seconds tolerance."""
    diff = abs(dur1 - dur2)
    if diff <= sec_tolerance:
        return True
    max_dur = max(dur1, dur2)
    if max_dur > 0 and (diff / max_dur) * 100.0 <= pct_tolerance:
        return True
    return False


def compare_fingerprints(
    hashes_a: List[imagehash.ImageHash],
    hashes_b: List[imagehash.ImageHash],
    threshold: int = DEFAULT_HAMMING_THRESHOLD,
) -> Tuple[bool, float]:
    """
    Computes average Hamming distance between corresponding keyframes.
    Returns (is_match, average_distance).
    """
    min_len = min(len(hashes_a), len(hashes_b))
    if min_len < 2:
        return False, 999.0

    distances = [hashes_a[i] - hashes_b[i] for i in range(min_len)]
    avg_distance = sum(distances) / len(distances)

    # Match if average distance is within threshold and max distance is not wildly divergent
    is_match = (avg_distance <= threshold) and (max(distances) <= threshold * 1.5)
    return is_match, avg_distance


def find_perceptual_duplicates(
    video_files: List[Path],
    threshold: int = DEFAULT_HAMMING_THRESHOLD,
    num_keyframes: int = DEFAULT_KEYFRAME_COUNT,
    hash_algo: str = DEFAULT_HASH_ALGO,
    duration_tolerance_pct: float = DEFAULT_DURATION_TOLERANCE_PCT,
    duration_tolerance_sec: float = DEFAULT_DURATION_TOLERANCE_SEC,
    workers: int = 4,
    show_progress: bool = True,
    metadata_cache: Optional[Dict[Path, VideoMetadata]] = None,
) -> Tuple[List[List[Path]], Dict[Path, VideoMetadata]]:
    """
    Finds visually similar/duplicate videos across different formats/resolutions.
    Returns (duplicate_groups, metadata_map).
    """
    if not HAS_PERCEPTUAL_DEPS:
        logger.error(
            "Perceptual dependencies missing! Please install opencv-python, pillow, and imagehash."
        )
        return [], {}

    if len(video_files) < 2:
        return [], {}

    metadata_map: Dict[Path, VideoMetadata] = metadata_cache if metadata_cache is not None else {}

    logger.info(f"Extracting visual fingerprints ({hash_algo}) for {len(video_files)} video(s)...")

    fingerprints: Dict[Path, List[imagehash.ImageHash]] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                extract_video_fingerprint,
                path,
                num_keyframes,
                hash_algo,
                metadata_map.get(path)
            ): path
            for path in video_files
        }

        iterator = as_completed(futures)
        if show_progress:
            iterator = tqdm(iterator, total=len(futures), desc="Perceptual Fingerprinting", leave=False)

        for future in iterator:
            path = futures[future]
            res = future.result()
            if res:
                meta, hashes = res
                metadata_map[path] = meta
                fingerprints[path] = hashes

    logger.info(f"Fingerprinted {len(fingerprints)} videos successfully.")

    valid_paths = list(fingerprints.keys())
    if len(valid_paths) < 2:
        return [], metadata_map

    # Compare candidates with similar durations
    dsu = DisjointSet()
    total_comparisons = 0

    logger.info("Comparing video fingerprints based on duration and visual hash distance...")

    for i in range(len(valid_paths)):
        path_a = valid_paths[i]
        meta_a = metadata_map[path_a]
        hashes_a = fingerprints[path_a]

        for j in range(i + 1, len(valid_paths)):
            path_b = valid_paths[j]
            meta_b = metadata_map[path_b]

            # Fast duration gate
            if not are_durations_similar(
                meta_a.duration,
                meta_b.duration,
                duration_tolerance_pct,
                duration_tolerance_sec,
            ):
                continue

            total_comparisons += 1
            hashes_b = fingerprints[path_b]
            is_match, avg_dist = compare_fingerprints(hashes_a, hashes_b, threshold)

            if is_match:
                logger.debug(
                    f"Perceptual match: '{path_a.name}' <-> '{path_b.name}' (avg Hamming dist: {avg_dist:.2f})"
                )
                dsu.union(path_a, path_b)

    clusters = dsu.get_clusters()
    logger.info(
        f"Perceptual search complete: {total_comparisons} candidate pairs compared, "
        f"found {len(clusters)} visual duplicate cluster(s)."
    )

    return clusters, metadata_map
