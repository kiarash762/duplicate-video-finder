import subprocess
import sys
from pathlib import Path


def test_cli_help():
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, str(repo_root / "duplicate_video_finder.py"), "--help"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0
    assert "Fast, multi-stage exact and perceptual duplicate video finder" in res.stdout
    assert "--mode" in res.stdout
    assert "--keep" in res.stdout


def test_cli_backward_compatibility():
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, str(repo_root / "duplicate video finder.py"), "--help"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0
    assert "Fast, multi-stage exact and perceptual duplicate video finder" in res.stdout


def test_cli_scan_dry_run(tmp_path: Path):
    repo_root = Path(__file__).resolve().parent.parent
    # Create two identical files
    f1 = tmp_path / "v1.mp4"
    f2 = tmp_path / "v2.mp4"
    data = b"VIDEOSAMPLE" * 5000
    f1.write_bytes(data)
    f2.write_bytes(data)

    cmd = [
        sys.executable,
        str(repo_root / "duplicate_video_finder.py"),
        str(tmp_path),
        "--export-json",
        str(tmp_path / "out.json"),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0
    assert "DRY-RUN PREVIEW ACTIVE" in res.stdout or "DRY-RUN PREVIEW ACTIVE" in res.stderr or "Found 1 group" in res.stdout
    assert (tmp_path / "out.json").exists()
