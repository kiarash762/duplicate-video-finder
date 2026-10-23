from pathlib import Path
from duplicate_video_finder.actions import (
    KeepStrategy,
    apply_keep_strategy,
    delete_file,
)
from duplicate_video_finder.metadata import VideoMetadata


def test_keep_strategy_highest_res():
    p1 = Path("low_res.mp4")
    p2 = Path("high_res.mp4")

    meta_map = {
        p1: VideoMetadata(path=p1, size=500, width=1280, height=720, bitrate=1000),
        p2: VideoMetadata(path=p2, size=1500, width=1920, height=1080, bitrate=3000),
    }

    keep, remove = apply_keep_strategy([p1, p2], KeepStrategy.HIGHEST_RES, meta_map)
    assert keep == p2
    assert remove == [p1]


def test_keep_strategy_largest_and_smallest():
    p1 = Path("small.mp4")
    p2 = Path("large.mp4")

    meta_map = {
        p1: VideoMetadata(path=p1, size=100),
        p2: VideoMetadata(path=p2, size=9999),
    }

    keep_large, _ = apply_keep_strategy([p1, p2], KeepStrategy.LARGEST, meta_map)
    assert keep_large == p2

    keep_small, _ = apply_keep_strategy([p1, p2], KeepStrategy.SMALLEST, meta_map)
    assert keep_small == p1


def test_keep_strategy_shortest_path():
    p1 = Path("a/b/c/long_filename_duplicate.mp4")
    p2 = Path("a/short.mp4")

    keep, remove = apply_keep_strategy([p1, p2], KeepStrategy.SHORTEST_PATH)
    assert keep == p2
    assert remove == [p1]


def test_dry_run_delete(tmp_path: Path):
    target = tmp_path / "do_not_delete.mp4"
    target.write_text("safe content")

    # Dry-run delete should NOT remove the file
    res = delete_file(target, dry_run=True)
    assert res is True
    assert target.exists()
