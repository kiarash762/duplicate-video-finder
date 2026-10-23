import json
import csv
from pathlib import Path
from duplicate_video_finder.metadata import VideoMetadata
from duplicate_video_finder.reporting import (
    export_json,
    export_csv,
    export_html,
    calculate_reclaimable_space,
)


def test_reporting_exports(tmp_path: Path):
    p1 = tmp_path / "movie_1080p.mp4"
    p2 = tmp_path / "movie_720p.mp4"
    p1.touch()
    p2.touch()

    meta_map = {
        p1: VideoMetadata(path=p1, size=2000000, width=1920, height=1080, duration=120.0),
        p2: VideoMetadata(path=p2, size=1000000, width=1280, height=720, duration=120.0),
    }

    groups = [[p1, p2]]

    # Reclaimable space should equal the removable file's size (p2 = 1,000,000)
    reclaimable = calculate_reclaimable_space(groups, meta_map)
    assert reclaimable == 1000000

    # JSON export
    json_path = tmp_path / "report.json"
    export_json(groups, meta_map, json_path)
    assert json_path.exists()
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
        assert data["total_groups"] == 1
        assert data["reclaimable_bytes"] == 1000000
        assert data["groups"][0]["keep_file"]["path"] == str(p1)

    # CSV export
    csv_path = tmp_path / "report.csv"
    export_csv(groups, meta_map, csv_path)
    assert csv_path.exists()
    with open(csv_path, encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 3  # Header + 2 files
        assert reader[1][1] == "KEEP"
        assert reader[2][1] == "DELETE_CANDIDATE"

    # HTML export
    html_path = tmp_path / "report.html"
    export_html(groups, meta_map, html_path)
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert "Duplicate Video Finder Report" in content
    assert "movie_1080p.mp4" in content
    assert "movie_720p.mp4" in content
