import argparse
import concurrent.futures
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Dependencies and optional module handling
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

try:
    import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False

try:
    import cv2
    import imagehash
    from PIL import Image
    HAS_PERCEPTUAL = True
except ImportError:
    HAS_PERCEPTUAL = False


# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("duplicate_finder.log", encoding="utf-8")
    ]
)

# Supported Video Extensions
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v"}


def get_fast_hash(file_path: Path, sample_size: int = 64 * 1024) -> str:
    """Calculates a fast hash by reading head, middle, and tail chunks of the file."""
    try:
        file_size = file_path.stat().st_size
        hasher = hashlib.md5()
        
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
    except Exception as e:
        logging.error(f"Error computing fast hash for {file_path}: {e}")
        return ""


def get_full_hash(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculates full SHA256 hash in chunks."""
    try:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logging.error(f"Error computing full hash for {file_path}: {e}")
        return ""


def get_perceptual_hash(file_path: Path, num_frames: int = 3) -> Optional[str]:
    """Extracts frame hashes to detect visually similar videos across formats/resolutions."""
    if not HAS_PERCEPTUAL:
        return None
    try:
        cap = cv2.VideoCapture(str(file_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return None

        hashes = []
        step = total_frames // (num_frames + 1)

        for i in range(1, num_frames + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, step * i)
            ret, frame = cap.read()
            if ret:
                color_converted = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(color_converted)
                hashes.append(str(imagehash.average_hash(pil_img)))

        cap.release()
        return "-".join(hashes) if hashes else None
    except Exception as e:
        logging.error(f"Error computing perceptual hash for {file_path}: {e}")
        return None


def scan_videos(target_dir: Path) -> List[Path]:
    """Scans target directory for video files."""
    logging.info(f"Scanning directory: {target_dir}")
    video_files = []
    for root, _, files in os.walk(target_dir):
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(file_path)
    logging.info(f"Found {len(video_files)} video file(s).")
    return video_files


def find_duplicates(
    video_files: List[Path],
    use_perceptual: bool = False,
    workers: int = 4
) -> Dict[str, List[Path]]:
    """Multi-stage process to detect duplicates."""
    # Stage 1: Group by File Size
    logging.info("Stage 1/3: Grouping files by size...")
    size_map: Dict[int, List[Path]] = {}
    for path in video_files:
        try:
            size = path.stat().st_size
            size_map.setdefault(size, []).append(path)
        except OSError:
            continue

    candidates = [paths for paths in size_map.values() if len(paths) > 1]
    candidate_files = [path for sublist in candidates for path in sublist]

    if not candidate_files:
        return {}

    # Stage 2: Fast Hash filtering
    logging.info(f"Stage 2/3: Calculating fast hash for {len(candidate_files)} files...")
    fast_hash_map: Dict[str, List[Path]] = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(get_fast_hash, path): path for path in candidate_files}
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Fast Hash"):
            path = futures[future]
            f_hash = future.result()
            if f_hash:
                fast_hash_map.setdefault(f_hash, []).append(path)

    full_hash_candidates = [paths for paths in fast_hash_map.values() if len(paths) > 1]
    final_files_to_check = [path for sublist in full_hash_candidates for path in sublist]

    # Stage 3: Full Hash or Perceptual Hash
    duplicates: Dict[str, List[Path]] = {}

    if use_perceptual:
        if not HAS_PERCEPTUAL:
            logging.warning("opencv-python or imagehash not installed! Perceptual hashing disabled.")
            return {}
            
        logging.info("Stage 3/3: Calculating perceptual hashes (visual comparison)...")
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(get_perceptual_hash, path): path for path in final_files_to_check}
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Perceptual Hash"):
                path = futures[future]
                p_hash = future.result()
                if p_hash:
                    duplicates.setdefault(p_hash, []).append(path)
    else:
        logging.info("Stage 3/3: Calculating full hash (SHA256) for exact match...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(get_full_hash, path): path for path in final_files_to_check}
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Full Hash"):
                path = futures[future]
                full_hash = future.result()
                if full_hash:
                    duplicates.setdefault(full_hash, []).append(path)

    return {hash_val: paths for hash_val, paths in duplicates.items() if len(paths) > 1}


def handle_duplicates(duplicates: Dict[str, List[Path]], dry_run: bool = True, use_trash: bool = True):
    """Prints results and manages duplicates (dry-run or trash/delete)."""
    if not duplicates:
        logging.info("No duplicate videos found.")
        return

    total_duplicates = sum(len(paths) - 1 for paths in duplicates.values())
    logging.info(f"Found {len(duplicates)} duplicate group(s) | Total removable file(s): {total_duplicates}")

    for group_idx, (hash_val, paths) in enumerate(duplicates.items(), start=1):
        print(f"\n--- Group {group_idx} (Hash: {hash_val[:12]}...) ---")
        print(f"  [KEEPING] -> {paths[0]}")
        
        for dup_path in paths[1:]:
            if dry_run:
                print(f"  [DRY-RUN DELETE] -> {dup_path}")
            else:
                if use_trash and HAS_SEND2TRASH:
                    try:
                        send2trash.send2trash(str(dup_path))
                        logging.info(f"Moved to trash: {dup_path}")
                    except Exception as e:
                        logging.error(f"Failed to move to trash {dup_path}: {e}")
                else:
                    try:
                        os.remove(dup_path)
                        logging.info(f"Permanently deleted: {dup_path}")
                    except Exception as e:
                        logging.error(f"Failed to delete {dup_path}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Fast & Advanced Duplicate Video Finder")
    parser.add_argument("directory", type=str, help="Target directory path to scan")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview mode (no files deleted)")
    parser.add_argument("--delete", action="store_true", help="Execute actual deletion/moving to trash")
    parser.add_argument("--perceptual", action="store_true", help="Use perceptual hashing to find visually similar videos")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker threads/processes")

    args = parser.parse_args()

    target_dir = Path(args.directory)
    if not target_dir.exists() or not target_dir.is_dir():
        logging.error("Invalid directory path provided.")
        sys.exit(1)

    is_dry_run = not args.delete

    if is_dry_run:
        logging.info(">>> DRY-RUN MODE ACTIVE. No files will be modified or deleted. <<<")

    videos = scan_videos(target_dir)
    if videos:
        duplicates = find_duplicates(videos, use_perceptual=args.perceptual, workers=args.workers)
        handle_duplicates(duplicates, dry_run=is_dry_run, use_trash=True)


if __name__ == "__main__":
    main()