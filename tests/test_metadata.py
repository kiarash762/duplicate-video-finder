from pathlib import Path
from duplicate_video_finder.metadata import (
    VideoMetadata,
    format_bytes,
    format_duration,
)


def test_format_bytes():
    assert format_bytes(500) == "500.00 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024 * 5) == "5.00 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2) == "2.00 GB"
    assert format_bytes(-10) == "0 B"


def test_format_duration():
    assert format_duration(0) == "00:00"
    assert format_duration(45.2) == "00:45"
    assert format_duration(75) == "01:15"
    assert format_duration(3665) == "01:01:05"


def test_resolution_labels():
    meta_4k = VideoMetadata(path=Path("test.mp4"), size=100, width=3840, height=2160)
    assert "4K" in meta_4k.resolution_label

    meta_1080p = VideoMetadata(path=Path("test.mp4"), size=100, width=1920, height=1080)
    assert "1080p" in meta_1080p.resolution_label

    meta_720p = VideoMetadata(path=Path("test.mp4"), size=100, width=1280, height=720)
    assert "720p" in meta_720p.resolution_label

    meta_480p = VideoMetadata(path=Path("test.mp4"), size=100, width=854, height=480)
    assert "480p" in meta_480p.resolution_label

    meta_custom = VideoMetadata(path=Path("test.mp4"), size=100, width=640, height=360)
    assert meta_custom.resolution_label == "640x360"
