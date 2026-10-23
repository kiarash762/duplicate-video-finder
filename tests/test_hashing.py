from pathlib import Path
from duplicate_video_finder.core import (
    find_exact_duplicates,
    get_head_hash,
    get_multi_chunk_hash,
    get_full_hash,
    scan_videos,
)


def test_hashing_exact_matches(tmp_path: Path):
    # Create identical files
    content1 = b"VIDEODATA" * 10000
    f1 = tmp_path / "vid1.mp4"
    f2 = tmp_path / "vid2.mp4"
    f1.write_bytes(content1)
    f2.write_bytes(content1)

    # Create a different file with same size
    content2 = b"DIFFERENT" * 10000
    f3 = tmp_path / "vid3.mp4"
    f3.write_bytes(content2)

    # Create a unique sized file
    content3 = b"UNIQUE" * 500
    f4 = tmp_path / "vid4.mp4"
    f4.write_bytes(content3)

    videos = scan_videos(tmp_path)
    assert len(videos) == 4

    dups = find_exact_duplicates(videos, show_progress=False)
    assert len(dups) == 1

    matched_group = list(dups.values())[0]
    assert len(matched_group) == 2
    assert f1 in matched_group
    assert f2 in matched_group
    assert f3 not in matched_group
    assert f4 not in matched_group


def test_head_and_chunk_hashes(tmp_path: Path):
    file_a = tmp_path / "file_a.mp4"
    file_b = tmp_path / "file_b.mp4"

    # Files that match only in the head
    head = b"HEAD" * 16384  # 64 KB
    file_a.write_bytes(head + b"A" * 100000)
    file_b.write_bytes(head + b"B" * 100000)

    # Head hash should match
    assert get_head_hash(file_a) == get_head_hash(file_b)

    # Full hash must differ
    assert get_full_hash(file_a) != get_full_hash(file_b)
