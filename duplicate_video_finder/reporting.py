"""
Reporting and export functionality: Console summaries, JSON, CSV, and standalone HTML reports.
"""

import csv
import html
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .actions import KeepStrategy, apply_keep_strategy
from .metadata import VideoMetadata, format_bytes, format_duration, get_video_metadata

logger = logging.getLogger("duplicate_video_finder")


def calculate_reclaimable_space(
    duplicate_groups: List[List[Path]],
    metadata_map: Dict[Path, VideoMetadata],
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
) -> int:
    """Calculates total bytes that would be freed by removing duplicate candidates."""
    total_reclaimable = 0
    for group in duplicate_groups:
        _, remove_paths = apply_keep_strategy(group, strategy, metadata_map)
        for p in remove_paths:
            meta = metadata_map.get(p)
            if meta:
                total_reclaimable += meta.size
            else:
                try:
                    total_reclaimable += p.stat().st_size
                except OSError:
                    pass
    return total_reclaimable


def print_console_report(
    duplicate_groups: List[List[Path]],
    metadata_map: Dict[Path, VideoMetadata],
    dry_run: bool = True,
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
    use_trash: bool = True,
):
    """Outputs a clean, structured summary table to the terminal."""
    if not duplicate_groups:
        print("\n[+] No duplicate videos found.")
        return

    total_removable = sum(len(g) - 1 for g in duplicate_groups)
    reclaimable_bytes = calculate_reclaimable_space(duplicate_groups, metadata_map, strategy)

    print("\n" + "=" * 78)
    print(f" DUPLICATE VIDEO FINDER REPORT")
    print(f" Found {len(duplicate_groups)} group(s) | {total_removable} redundant file(s)")
    print(f" Estimated Reclaimable Space: {format_bytes(reclaimable_bytes)}")
    if dry_run:
        print(" Mode: [DRY-RUN] No files were touched.")
    else:
        dest = "Recycle Bin / Trash" if use_trash else "Permanent Deletion"
        print(f" Mode: [EXECUTED] Redundant files sent to {dest}.")
    print("=" * 78 + "\n")

    for idx, group in enumerate(duplicate_groups, start=1):
        keep_path, remove_paths = apply_keep_strategy(group, strategy, metadata_map)
        keep_meta = metadata_map.get(keep_path, get_video_metadata(keep_path))

        print(f"--- Group #{idx} ({len(group)} files) ---")
        keep_info = f"({keep_meta.resolution_label}, {keep_meta.formatted_size}, {keep_meta.formatted_duration})"
        print(f"  [KEEP]            -> {keep_path}")
        print(f"                       {keep_info}")

        action_label = "[DRY-RUN DELETE]" if dry_run else ("[TRASH]" if use_trash else "[DELETED]")
        for rm_path in remove_paths:
            rm_meta = metadata_map.get(rm_path, get_video_metadata(rm_path))
            rm_info = f"({rm_meta.resolution_label}, {rm_meta.formatted_size}, {rm_meta.formatted_duration})"
            print(f"  {action_label:<17} -> {rm_path}")
            print(f"                       {rm_info}")
        print()


def export_json(
    duplicate_groups: List[List[Path]],
    metadata_map: Dict[Path, VideoMetadata],
    output_path: Path,
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
):
    """Exports duplicate groups and full metadata to a JSON file."""
    output_path = Path(output_path).resolve()
    data = {
        "total_groups": len(duplicate_groups),
        "total_redundant_files": sum(len(g) - 1 for g in duplicate_groups),
        "reclaimable_bytes": calculate_reclaimable_space(duplicate_groups, metadata_map, strategy),
        "reclaimable_formatted": format_bytes(calculate_reclaimable_space(duplicate_groups, metadata_map, strategy)),
        "groups": [],
    }

    def serialize_meta(p: Path, is_keep: bool) -> dict:
        meta = metadata_map.get(p, get_video_metadata(p))
        return {
            "path": str(p),
            "status": "KEEP" if is_keep else "DELETE_CANDIDATE",
            "size_bytes": meta.size,
            "size_formatted": meta.formatted_size,
            "resolution": meta.resolution_label,
            "width": meta.width,
            "height": meta.height,
            "duration_seconds": meta.duration,
            "duration_formatted": meta.formatted_duration,
            "fps": meta.fps,
            "bitrate_bps": meta.bitrate,
            "codec": meta.codec,
        }

    for idx, group in enumerate(duplicate_groups, start=1):
        keep_path, remove_paths = apply_keep_strategy(group, strategy, metadata_map)
        group_obj = {
            "group_id": idx,
            "file_count": len(group),
            "keep_file": serialize_meta(keep_path, True),
            "remove_candidates": [serialize_meta(p, False) for p in remove_paths],
        }
        data["groups"].append(group_obj)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Exported JSON report to: {output_path}")


def export_csv(
    duplicate_groups: List[List[Path]],
    metadata_map: Dict[Path, VideoMetadata],
    output_path: Path,
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
):
    """Exports duplicate groups to a CSV file."""
    output_path = Path(output_path).resolve()
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Group_ID", "Status", "Path", "Size_Bytes", "Size_Formatted",
            "Resolution", "Duration_Sec", "Duration_Formatted", "Bitrate_Bps", "Codec"
        ])

        for idx, group in enumerate(duplicate_groups, start=1):
            keep_path, remove_paths = apply_keep_strategy(group, strategy, metadata_map)

            # Write KEEP row
            k_meta = metadata_map.get(keep_path, get_video_metadata(keep_path))
            writer.writerow([
                idx, "KEEP", str(keep_path), k_meta.size, k_meta.formatted_size,
                k_meta.resolution_label, f"{k_meta.duration:.2f}", k_meta.formatted_duration,
                f"{k_meta.bitrate:.0f}", k_meta.codec
            ])

            # Write REMOVE rows
            for rm_path in remove_paths:
                rm_meta = metadata_map.get(rm_path, get_video_metadata(rm_path))
                writer.writerow([
                    idx, "DELETE_CANDIDATE", str(rm_path), rm_meta.size, rm_meta.formatted_size,
                    rm_meta.resolution_label, f"{rm_meta.duration:.2f}", rm_meta.formatted_duration,
                    f"{rm_meta.bitrate:.0f}", rm_meta.codec
                ])

    logger.info(f"Exported CSV report to: {output_path}")


def export_html(
    duplicate_groups: List[List[Path]],
    metadata_map: Dict[Path, VideoMetadata],
    output_path: Path,
    strategy: KeepStrategy = KeepStrategy.HIGHEST_RES,
):
    """Generates an elegant, standalone, dark-mode HTML report."""
    output_path = Path(output_path).resolve()
    total_groups = len(duplicate_groups)
    total_redundant = sum(len(g) - 1 for g in duplicate_groups)
    reclaimable = calculate_reclaimable_space(duplicate_groups, metadata_map, strategy)

    cards_html = []
    for idx, group in enumerate(duplicate_groups, start=1):
        keep_path, remove_paths = apply_keep_strategy(group, strategy, metadata_map)
        k_meta = metadata_map.get(keep_path, get_video_metadata(keep_path))

        rows_html = []
        # Keep row
        rows_html.append(f"""
        <tr class="keep-row">
            <td><span class="badge badge-keep">KEEP</span></td>
            <td class="path-cell" title="{html.escape(str(keep_path))}">{html.escape(str(keep_path))}</td>
            <td>{html.escape(k_meta.resolution_label)}</td>
            <td>{html.escape(k_meta.formatted_duration)}</td>
            <td>{html.escape(k_meta.formatted_size)}</td>
        </tr>
        """)

        # Remove rows
        for rm_path in remove_paths:
            rm_meta = metadata_map.get(rm_path, get_video_metadata(rm_path))
            rows_html.append(f"""
            <tr class="delete-row">
                <td><span class="badge badge-delete">DELETE</span></td>
                <td class="path-cell" title="{html.escape(str(rm_path))}">{html.escape(str(rm_path))}</td>
                <td>{html.escape(rm_meta.resolution_label)}</td>
                <td>{html.escape(rm_meta.formatted_duration)}</td>
                <td>{html.escape(rm_meta.formatted_size)}</td>
            </tr>
            """)

        cards_html.append(f"""
        <div class="card">
            <div class="card-header">
                <h3>Group #{idx} <span class="file-count">({len(group)} files)</span></h3>
            </div>
            <table>
                <thead>
                    <tr>
                        <th style="width: 100px;">Action</th>
                        <th>File Path</th>
                        <th style="width: 130px;">Resolution</th>
                        <th style="width: 110px;">Duration</th>
                        <th style="width: 120px;">Size</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows_html)}
                </tbody>
            </table>
        </div>
        """)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Duplicate Video Finder - Report</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --keep-color: #10b981;
            --delete-color: #ef4444;
            --accent-color: #6366f1;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 30px 20px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 2.2rem;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 1.8rem;
            font-weight: 700;
            color: #38bdf8;
            margin-bottom: 4px;
        }}
        .stat-label {{
            font-size: 0.9rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            margin-bottom: 24px;
            overflow: hidden;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        .card-header {{
            padding: 16px 20px;
            background-color: rgba(255, 255, 255, 0.02);
            border-bottom: 1px solid var(--border-color);
        }}
        .card-header h3 {{
            margin: 0;
            font-size: 1.15rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .file-count {{
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: normal;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.92rem;
        }}
        th, td {{
            padding: 12px 18px;
            border-bottom: 1px solid var(--border-color);
        }}
        th {{
            background-color: rgba(0, 0, 0, 0.2);
            color: var(--text-muted);
            font-weight: 600;
            font-size: 0.85rem;
            text-transform: uppercase;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 700;
            text-align: center;
            letter-spacing: 0.04em;
        }}
        .badge-keep {{
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--keep-color);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .badge-delete {{
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--delete-color);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}
        .path-cell {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.86rem;
            word-break: break-all;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            color: var(--text-muted);
            font-size: 0.85rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Duplicate Video Finder Report</h1>
            <p style="color: var(--text-muted);">Inspection and duplicate analysis summary</p>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{total_groups}</div>
                <div class="stat-label">Duplicate Groups</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total_redundant}</div>
                <div class="stat-label">Redundant Videos</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: var(--keep-color);">{html.escape(format_bytes(reclaimable))}</div>
                <div class="stat-label">Reclaimable Space</div>
            </div>
        </div>
        <div class="groups-list">
            {"".join(cards_html) if cards_html else "<p style='text-align:center;'>No duplicate videos detected.</p>"}
        </div>
        <div class="footer">
            Generated with <a href="https://github.com/kiarash762/duplicate-video-finder" style="color: #818cf8; text-decoration: none;">Duplicate Video Finder</a>
        </div>
    </div>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"Exported HTML report to: {output_path}")
