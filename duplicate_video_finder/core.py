"""
Core multi-stage hashing pipeline for exact duplicate video detection.
"""

import fnmatch
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

logger = logging.getLogger("duplicate_video_finder")

DEFAULT_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv",
    ".webm", ".m4v", ".ts", ".m2ts", ".vob", ".3gp", ".ogv"
}

DEFAULT_SAMPLE_SIZE = 64 * 1024  # 64 KB
FULL_HASH_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunks for high throughput


def scan_videos(
    target_dir: Path,
    extensions: Optional[Set[str]] = None,
    min_size_bytes: int = 0,
    exclude_patterns: Optional[List[str]] = None,
) -> List[Path]:
    """
    Recursively scans target directory for video files matching extensions.
    Filters out files below min_size_bytes and matching exclude_patterns.
    """
    if extensions is None:
        extensions = DEFAULT_VIDEO_EXTENSIONS
    else:
        extensions = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions}

    exclude_patterns = exclude_patterns or []
    target_path = Path(target_dir).resolve()
    logger.info(f"Scanning directory: {target_path}")

    video_files: List[Path] = []

    for root, dirs, files in os.walk(target_path, topdown=True):
        # Filter directories in-place based on exclude patterns
        if exclude_patterns:
            dirs[:] = [
                d for d in dirs
                if not any(fnmatch.fnmatch(d, pat) for pat in exclude_patterns)
            ]

        for file_name in files:
            if exclude_patterns and any(fnmatch.fnmatch(file_name, pat) for pat in exclude_patterns):
                continue

            file_path = Path(root) / file_name
            if file_path.suffix.lower() not in extensions:
                continue

            try:
                st = file_path.stat()
                if st.st_size >= min_size_bytes:
                    video_files.append(file_path)
            except (OSError, PermissionError) as e:
                logger.warning(f"Skipping inaccessible file {file_path}: {e}")
                continue

    logger.info(f"Found {len(video_files)} video file(s) matching criteria.")
    return video_files


def get_head_hash(file_path: Path, sample_size: int = DEFAULT_SAMPLE_SIZE) -> str:
    """Reads the first block of the file to quickly reject non-duplicates."""
    try:
        hasher = hashlib.blake2b(digest_size=16)
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
            hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError) as e:
        logger.error(f"Error reading head chunk for {file_path}: {e}")
        return ""


def get_multi_chunk_hash(file_path: Path, sample_size: int = DEFAULT_SAMPLE_SIZE) -> str:
    """Computes hash over head, middle, and tail chunks."""
    try:
        file_size = file_path.stat().st_size
        hasher = hashlib.blake2b(digest_size=16)

        with open(file_path, "rb") as f:
            if file_size <= sample_size * 3:
                hasher.update(f.read())
            else:
                # Head
                hasher.update(f.read(sample_size))
                # Middle
                f.seek(file_size // 2)
                hasher.update(f.read(sample_size))
                # Tail
                f.seek(file_size - sample_size)
                hasher.update(f.read(sample_size))

        return hasher.hexdigest()
    except (OSError, PermissionError) as e:
        logger.error(f"Error computing chunk hash for {file_path}: {e}")
        return ""


def get_full_hash(
    file_path: Path,
    chunk_size: int = FULL_HASH_CHUNK_SIZE,
    progress_callback: Optional[Callable[[int], None]] = None
) -> str:
    """Calculates full BLAKE2b hash using buffered streaming."""
    try:
        hasher = hashlib.blake2b(digest_size=32)
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
                if progress_callback:
                    progress_callback(len(chunk))
        return hasher.hexdigest()
    except (OSError, PermissionError) as e:
        logger.error(f"Error computing full hash for {file_path}: {e}")
        return ""


def check_hardlinks(paths: List[Path]) -> Dict[str, List[Path]]:
    """
    Identifies if candidate duplicate paths share the same device/inode.
    Returns grouped paths with warning flags.
    """
    seen_inodes: Dict[tuple, Path] = {}
    unique_candidates: List[Path] = []

    for p in paths:
        try:
            stat = p.stat()
            ident = (stat.st_dev, stat.st_ino)
            if ident in seen_inodes:
                logger.warning(
                    f"Files '{p}' and '{seen_inodes[ident]}' point to the exact same disk inode (hardlink). "
                    "Skipping redundant deletion candidate."
                )
            else:
                seen_inodes[ident] = p
                unique_candidates.append(p)
        except OSError:
            unique_candidates.append(p)

    return unique_candidates


def find_exact_duplicates(
    video_files: List[Path],
    workers: int = 4,
    show_progress: bool = True,
) -> Dict[str, List[Path]]:
    """
    Multi-stage exact duplicate detection pipeline:
      Stage 1: Group by file size in bytes
      Stage 2: Quick head-hash (first 64 KB)
      Stage 3: Multi-chunk hash (head + middle + tail)
      Stage 4: Full BLAKE2b streaming hash
    Returns a dictionary of {hash: [Path, ...]} for groups with 2+ files.
    """
    if not video_files:
        return {}

    # Stage 1: Size Grouping
    logger.info("Stage 1/4: Grouping files by exact byte size...")
    size_map: Dict[int, List[Path]] = {}
    for path in video_files:
        try:
            sz = path.stat().st_size
            if sz > 0:
                size_map.setdefault(sz, []).append(path)
        except OSError:
            continue

    stage1_candidates = [p for paths in size_map.values() if len(paths) > 1 for p in paths]
    if not stage1_candidates:
        logger.info("Stage 1 complete: No size-matched candidates found.")
        return {}

    logger.info(f"Stage 1 complete: {len(stage1_candidates)} candidate files with matching sizes.")

    # Stage 2: Head Hash (First 64 KB)
    logger.info(f"Stage 2/4: Computing head hash on {len(stage1_candidates)} files...")
    head_map: Dict[str, List[Path]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(get_head_hash, p): p for p in stage1_candidates}
        iterator = as_completed(futures)
        if show_progress:
            iterator = tqdm(iterator, total=len(futures), desc="Stage 2 [Head Hash]", leave=False)

        for future in iterator:
            path = futures[future]
            h = future.result()
            if h:
                head_map.setdefault(h, []).append(path)

    stage2_candidates = [p for paths in head_map.values() if len(paths) > 1 for p in paths]
    if not stage2_candidates:
        logger.info("Stage 2 complete: No head-hash matched candidates.")
        return {}

    logger.info(f"Stage 2 complete: {len(stage2_candidates)} candidate files with matching headers.")

    # Stage 3: Multi-chunk Hash (Head + Middle + Tail)
    logger.info(f"Stage 3/4: Computing multi-chunk sample hash on {len(stage2_candidates)} files...")
    chunk_map: Dict[str, List[Path]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(get_multi_chunk_hash, p): p for p in stage2_candidates}
        iterator = as_completed(futures)
        if show_progress:
            iterator = tqdm(iterator, total=len(futures), desc="Stage 3 [Sample Hash]", leave=False)

        for future in iterator:
            path = futures[future]
            h = future.result()
            if h:
                chunk_map.setdefault(h, []).append(path)

    stage3_candidates = [p for paths in chunk_map.values() if len(paths) > 1 for p in paths]
    if not stage3_candidates:
        logger.info("Stage 3 complete: No sample-hash matched candidates.")
        return {}

    logger.info(f"Stage 3 complete: {len(stage3_candidates)} candidate files with matching samples.")

    # Stage 4: Full Hash Confirmation
    logger.info(f"Stage 4/4: Confirming exact match with full hash on {len(stage3_candidates)} files...")
    full_hash_map: Dict[str, List[Path]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(get_full_hash, p): p for p in stage3_candidates}
        iterator = as_completed(futures)
        if show_progress:
            iterator = tqdm(iterator, total=len(futures), desc="Stage 4 [Full Hash]", leave=False)

        for future in iterator:
            path = futures[future]
            full_h = future.result()
            if full_h:
                full_hash_map.setdefault(full_h, []).append(path)

    duplicates = {
        h: check_hardlinks(paths)
        for h, paths in full_hash_map.items()
        if len(paths) > 1
    }

    # Filter out groups where hardlink deduplication left only 1 file
    duplicates = {h: paths for h, paths in duplicates.items() if len(paths) > 1}

    logger.info(f"Exact search complete: Found {len(duplicates)} exact duplicate group(s).")
    return duplicates
