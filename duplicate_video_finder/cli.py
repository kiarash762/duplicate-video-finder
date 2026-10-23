"""
Command-line interface for Duplicate Video Finder.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List

from .actions import KeepStrategy, apply_keep_strategy, delete_file, run_interactive_review
from .core import find_exact_duplicates, scan_videos
from .metadata import VideoMetadata, get_video_metadata
from .perceptual import find_perceptual_duplicates, DisjointSet
from .reporting import export_csv, export_html, export_json, print_console_report

logger = logging.getLogger("duplicate_video_finder")


def setup_logging(verbose: bool = False, quiet: bool = False):
    """Sets up clean terminal and file logging without mangling progress bars."""
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    logger.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_fmt)

    # File handler
    file_handler = logging.FileHandler("duplicate_finder.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s")
    file_handler.setFormatter(file_fmt)

    # Avoid duplicate handlers if re-initialized
    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="duplicate-video-finder",
        description="Fast, multi-stage exact and perceptual duplicate video finder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan a folder in safe preview (dry-run) mode:
  duplicate-video-finder "D:/Movies"

  # Find visually similar videos (re-encoded, resized, or converted):
  duplicate-video-finder "D:/Movies" --mode perceptual

  # Find both exact and visual duplicates, keeping highest-resolution copies:
  duplicate-video-finder "D:/Movies" --mode both --keep highest-res

  # Interactively review each group before moving duplicates to Recycle Bin:
  duplicate-video-finder "D:/Movies" --interactive

  # Execute deletion (moves to Recycle Bin/Trash by default):
  duplicate-video-finder "D:/Movies" --delete

  # Export a beautiful standalone dark-mode HTML report:
  duplicate-video-finder "D:/Movies" --export-html report.html
        """,
    )

    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        type=str,
        help="Target folder path to scan for videos.",
    )
    parser.add_argument(
        "--path", "-p",
        dest="opt_directory",
        type=str,
        default=None,
        help="Alternative flag to specify target directory.",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["exact", "perceptual", "both"],
        default="exact",
        help="Detection mode: 'exact' (byte hash), 'perceptual' (visual similarity), or 'both' (default: exact).",
    )
    parser.add_argument(
        "--keep", "-k",
        choices=[s.value for s in KeepStrategy],
        default=KeepStrategy.HIGHEST_RES.value,
        help="Strategy to choose which file to KEEP in each group (default: highest-res).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Execute actual removal (default sends to Recycle Bin / Trash).",
    )
    parser.add_argument(
        "--permanent",
        action="store_true",
        help="Permanently delete files from disk instead of moving to Recycle Bin / Trash.",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Review each duplicate group interactively in terminal.",
    )
    parser.add_argument(
        "--min-size",
        type=float,
        default=0.0,
        help="Minimum file size in megabytes (MB) to inspect (default: 0).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude (e.g. --exclude '*sample*' --exclude '.git*'). Can be repeated.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=8,
        help="Perceptual hash Hamming distance threshold [0-64]. Lower is stricter (default: 8).",
    )
    parser.add_argument(
        "--hash-algo",
        choices=["dhash", "phash", "ahash"],
        default="dhash",
        help="Visual hashing algorithm to use: 'dhash' (difference), 'phash' (DCT), 'ahash' (average) (default: dhash).",
    )
    parser.add_argument(
        "--keyframes",
        type=int,
        default=5,
        help="Number of keyframes to extract for visual comparison (default: 5).",
    )
    parser.add_argument(
        "--duration-tolerance",
        type=float,
        default=5.0,
        help="Allowed duration variance in percent between visual duplicate candidates (default: 5.0%%).",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=min(16, (os.cpu_count() or 4)),
        help="Number of worker threads (default: CPU count).",
    )
    parser.add_argument(
        "--export-json",
        type=str,
        default=None,
        help="Export results to a JSON file.",
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        default=None,
        help="Export results to a CSV file.",
    )
    parser.add_argument(
        "--export-html",
        type=str,
        default=None,
        help="Export an interactive HTML report.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress informational output.",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    target_dir_str = args.directory or args.opt_directory
    if not target_dir_str:
        print("Error: Target directory is required. Run with --help for usage.")
        sys.exit(1)

    target_dir = Path(target_dir_str).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        logger.error(f"Target directory does not exist or is not a directory: {target_dir}")
        sys.exit(1)

    min_size_bytes = int(args.min_size * 1024 * 1024)
    strategy = KeepStrategy(args.keep)
    is_dry_run = not args.delete and not args.interactive
    use_trash = not args.permanent

    if is_dry_run:
        logger.info(">>> DRY-RUN PREVIEW ACTIVE. No files will be modified or deleted. <<<")

    # Step 1: Scan directory
    video_files = scan_videos(
        target_dir=target_dir,
        min_size_bytes=min_size_bytes,
        exclude_patterns=args.exclude,
    )

    if not video_files:
        logger.info("No matching video files found.")
        sys.exit(0)

    duplicate_groups: List[List[Path]] = []
    metadata_map: Dict[Path, VideoMetadata] = {}

    # Step 2: Detection Pipeline based on Mode
    if args.mode == "exact":
        exact_map = find_exact_duplicates(
            video_files=video_files,
            workers=args.workers,
            show_progress=not args.quiet,
        )
        duplicate_groups = list(exact_map.values())

    elif args.mode == "perceptual":
        p_clusters, p_meta = find_perceptual_duplicates(
            video_files=video_files,
            threshold=args.threshold,
            num_keyframes=args.keyframes,
            hash_algo=args.hash_algo,
            duration_tolerance_pct=args.duration_tolerance,
            workers=args.workers,
            show_progress=not args.quiet,
            metadata_cache=metadata_map,
        )
        metadata_map.update(p_meta)
        duplicate_groups = p_clusters

    elif args.mode == "both":
        exact_map = find_exact_duplicates(
            video_files=video_files,
            workers=args.workers,
            show_progress=not args.quiet,
        )
        exact_groups = list(exact_map.values())

        # Exclude exact duplicates from perceptual check, keeping only 1 representative per group
        already_grouped = {p for group in exact_groups for p in group}
        represented = {group[0] for group in exact_groups}
        files_for_perceptual = [
            p for p in video_files
            if p not in already_grouped or p in represented
        ]

        p_clusters, p_meta = find_perceptual_duplicates(
            video_files=files_for_perceptual,
            threshold=args.threshold,
            num_keyframes=args.keyframes,
            hash_algo=args.hash_algo,
            duration_tolerance_pct=args.duration_tolerance,
            workers=args.workers,
            show_progress=not args.quiet,
            metadata_cache=metadata_map,
        )
        metadata_map.update(p_meta)

        # Merge exact groups and perceptual clusters using Disjoint Set Union
        dsu = DisjointSet()
        for group in exact_groups:
            for i in range(len(group) - 1):
                dsu.union(group[i], group[i + 1])
        for cluster in p_clusters:
            for i in range(len(cluster) - 1):
                dsu.union(cluster[i], cluster[i + 1])

        duplicate_groups = dsu.get_clusters()

    # Step 3: Populate metadata for all candidates if needed
    for group in duplicate_groups:
        for p in group:
            if p not in metadata_map:
                metadata_map[p] = get_video_metadata(p)

    # Step 4: Handle Actions (Interactive review or batch execution)
    if args.interactive:
        if duplicate_groups:
            deleted_cnt, skipped_cnt = run_interactive_review(
                duplicate_groups=duplicate_groups,
                metadata_map=metadata_map,
                strategy=strategy,
                use_trash=use_trash,
            )
            print(f"\n[+] Interactive review finished: {deleted_cnt} removed, {skipped_cnt} skipped.")
        else:
            print("\n[+] No duplicate videos found.")
    else:
        # Batch mode: display report
        print_console_report(
            duplicate_groups=duplicate_groups,
            metadata_map=metadata_map,
            dry_run=is_dry_run,
            strategy=strategy,
            use_trash=use_trash,
        )

        if args.delete:
            # Actually execute deletion
            total_deleted = 0
            for group in duplicate_groups:
                _, remove_paths = apply_keep_strategy(group, strategy, metadata_map)
                for rm_path in remove_paths:
                    if delete_file(rm_path, dry_run=False, use_trash=use_trash):
                        total_deleted += 1
            action_word = "sent to trash" if use_trash else "permanently deleted"
            print(f"[+] Successfully {action_word} {total_deleted} duplicate video file(s).")

    # Step 5: Exports
    if args.export_json:
        export_json(duplicate_groups, metadata_map, Path(args.export_json), strategy)
    if args.export_csv:
        export_csv(duplicate_groups, metadata_map, Path(args.export_csv), strategy)
    if args.export_html:
        export_html(duplicate_groups, metadata_map, Path(args.export_html), strategy)


if __name__ == "__main__":
    main()
