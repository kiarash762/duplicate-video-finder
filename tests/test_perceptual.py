import cv2
import numpy as np
from pathlib import Path
from duplicate_video_finder.perceptual import (
    DisjointSet,
    are_durations_similar,
    find_perceptual_duplicates,
)


def test_disjoint_set():
    dsu = DisjointSet()
    p1 = Path("a.mp4")
    p2 = Path("b.mp4")
    p3 = Path("c.mp4")
    p4 = Path("d.mp4")

    dsu.union(p1, p2)
    dsu.union(p2, p3)

    clusters = dsu.get_clusters()
    assert len(clusters) == 1
    cluster = clusters[0]
    assert len(cluster) == 3
    assert set(cluster) == {p1, p2, p3}
    assert p4 not in cluster


def test_are_durations_similar():
    # Close durations
    assert are_durations_similar(10.0, 10.5, pct_tolerance=5.0, sec_tolerance=2.0)
    assert are_durations_similar(100.0, 102.0, pct_tolerance=5.0, sec_tolerance=1.0)

    # Wildly different durations
    assert not are_durations_similar(10.0, 120.0, pct_tolerance=5.0, sec_tolerance=2.0)


def create_synthetic_video(file_path: Path, width: int, height: int, num_frames: int = 30, pattern_type: str = "gradient"):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(file_path), fourcc, 15.0, (width, height))

    for i in range(num_frames):
        if pattern_type == "gradient":
            # Animated gradient
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, :, 0] = (np.arange(height)[:, None] * 255 // height + i * 5) % 256
            frame[:, :, 1] = (np.arange(width)[None, :] * 255 // width + i * 2) % 256
            frame[:, :, 2] = (i * 8) % 256
        elif pattern_type == "noise":
            # Completely different noise pattern
            np.random.seed(i)
            frame = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
        else:
            frame = np.full((height, width, 3), 200, dtype=np.uint8)

        out.write(frame)

    out.release()


def test_perceptual_duplicates(tmp_path: Path):
    vid_orig = tmp_path / "vid_original.mp4"
    vid_resized = tmp_path / "vid_resized.mp4"
    vid_different = tmp_path / "vid_different.mp4"

    # Create original 128x128 video
    create_synthetic_video(vid_orig, width=128, height=128, num_frames=30, pattern_type="gradient")
    # Create resized version (64x64) of the exact same content
    create_synthetic_video(vid_resized, width=64, height=64, num_frames=30, pattern_type="gradient")
    # Create completely different noise video
    create_synthetic_video(vid_different, width=128, height=128, num_frames=30, pattern_type="noise")

    clusters, meta_map = find_perceptual_duplicates(
        video_files=[vid_orig, vid_resized, vid_different],
        threshold=10,
        show_progress=False,
    )

    assert len(clusters) == 1
    cluster = clusters[0]
    assert len(cluster) == 2
    assert vid_orig in cluster
    assert vid_resized in cluster
    assert vid_different not in cluster
