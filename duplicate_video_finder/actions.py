"""
Handling duplicate groups: smart keep strategies, safe deletion, and interactive review.
"""

import enum
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .metadata import VideoMetadata, get_video_metadata, format_bytes, format_duration

try:
    import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False

logger = logging.getLogger("duplicate_video_finder")


class KeepStrategy(str, enum.Enum):
    HIGHEST_RES = "highest-res"
    LARGEST = "largest"
    SMALLEST = "smallest"
    OLDEST = "oldest"
    NEWEST = "newest"
    SHORTEST_PATH = "shortest-path"


def apply_keep_strategy(
    paths: List[Path],
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
    metadata_map: Optional[Dict[Path, VideoMetadata]] = None,
) -> Tuple[Path, List[Path]]:
    """
    Evaluates candidate paths using the requested strategy and designates
    one file to KEEP and the rest as REMOVABLE.
    Returns (path_to_keep, [paths_to_remove, ...]).
    """
    if len(paths) <= 1:
        return paths[0] if paths else Path(""), []

    metadata_map = metadata_map or {}

    def get_meta(p: Path) -> VideoMetadata:
        if p not in metadata_map:
            metadata_map[p] = get_video_metadata(p)
        return metadata_map[p]

    def sort_key(p: Path):
        meta = get_meta(p)
        if strategy == KeepStrategy.HIGHEST_RES:
            # Prefer higher resolution (width * height), then bitrate, then size, then shorter path
            return (
                meta.pixels,
                meta.bitrate,
                meta.size,
                -len(str(p.resolve())),
            )
        elif strategy == KeepStrategy.LARGEST:
            return (meta.size, -len(str(p.resolve())))
        elif strategy == KeepStrategy.SMALLEST:
            # Invert size so smaller gets sorted last (or we pick max)
            return (-meta.size if meta.size > 0 else -float("inf"), -len(str(p.resolve())))
        elif strategy == KeepStrategy.OLDEST:
            # Older mtime is smaller, so invert so older has highest key
            mtime = meta.modified_time or float("inf")
            return (-mtime, -len(str(p.resolve())))
        elif strategy == KeepStrategy.NEWEST:
            return (meta.modified_time, -len(str(p.resolve())))
        elif strategy == KeepStrategy.SHORTEST_PATH:
            return (-len(str(p.resolve())), meta.size)
        else:
            return (meta.size, -len(str(p.resolve())))

    sorted_paths = sorted(paths, key=sort_key, reverse=True)
    keep_path = sorted_paths[0]
    remove_paths = sorted_paths[1:]
    return keep_path, remove_paths


def delete_file(
    file_path: Path,
    dry_run: bool = True,
    use_trash: bool = True,
) -> bool:
    """
    Deletes or trashes a file safely.
    Returns True on success (or simulated success in dry-run), False on error.
    """
    if dry_run:
        action_name = "TRASH" if (use_trash and HAS_SEND2TRASH) else "DELETE"
        logger.info(f"[DRY-RUN {action_name}] Would remove: {file_path}")
        return True

    if use_trash and HAS_SEND2TRASH:
        try:
            send2trash.send2trash(str(file_path))
            logger.info(f"Moved to trash: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to move '{file_path}' to trash: {e}")
            return False
    else:
        try:
            os.remove(file_path)
            logger.info(f"Permanently deleted: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to permanently delete '{file_path}': {e}")
            return False


def run_interactive_review(
    duplicate_groups: List[List[Path]],
    metadata_map: Dict[Path, VideoMetadata],
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
    use_trash: bool = True,
) -> Tuple[int, int]:
    """
    Interactive prompt allowing the user to inspect each duplicate group
    side-by-side with metadata and choose which file to keep or skip.
    Returns (total_deleted, total_skipped).
    """
    deleted_count = 0
    skipped_count = 0

    print("\n" + "=" * 70)
    print(" INTERACTIVE DUPLICATE REVIEW MODE")
    print(" Review each group. Select the number of the file to KEEP.")
    print(" Commands: [Enter] = Accept recommendation | [s] = Skip | [q] = Quit")
    print("=" * 70 + "\n")

    for idx, group in enumerate(duplicate_groups, start=1):
        recommended_keep, _ = apply_keep_strategy(group, strategy, metadata_map)

        print(f"\n--- Group {idx}/{len(duplicate_groups)} ({len(group)} files) ---")
        for num, path in enumerate(group, start=1):
            meta = metadata_map.get(path, get_video_metadata(path))
            is_rec = (path == recommended_keep)
            rec_tag = " [RECOMMENDED KEEP]" if is_rec else " [DELETE CANDIDATE]"
            res_tag = f"Resolution: {meta.resolution_label}" if meta.width > 0 else ""
            dur_tag = f"Duration: {format_duration(meta.duration)}" if meta.duration > 0 else ""
            size_tag = f"Size: {format_bytes(meta.size)}"
            details = ", ".join(filter(None, [res_tag, dur_tag, size_tag]))

            print(f"  [{num}]{rec_tag}")
            print(f"      Path: {path}")
            print(f"      Info: {details}")

        rec_num = group.index(recommended_keep) + 1
        prompt = f"\nSelect file to KEEP [1-{len(group)}] (Default {rec_num}), [s]kip, [q]uit: "

        try:
            choice = input(prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting interactive review.")
            break

        if choice == "q":
            print("Interactive review aborted by user.")
            break
        elif choice == "s":
            print(f"Skipped group {idx}.")
            skipped_count += 1
            continue
        elif choice == "" or choice == str(rec_num):
            keep_file = recommended_keep
        else:
            try:
                selected_num = int(choice)
                if 1 <= selected_num <= len(group):
                    keep_file = group[selected_num - 1]
                else:
                    print(f"Invalid number. Skipping group {idx}.")
                    skipped_count += 1
                    continue
            except ValueError:
                print(f"Invalid input. Skipping group {idx}.")
                skipped_count += 1
                continue

        # Perform deletion for files other than keep_file
        to_delete = [p for p in group if p != keep_file]
        for p in to_delete:
            if delete_file(p, dry_run=False, use_trash=use_trash):
                deleted_count += 1

    return deleted_count, skipped_count
