"""
Metadata extraction and formatting utilities for video files.
"""

import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


@dataclass
class VideoMetadata:
    path: Path
    size: int
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: float = 0.0
    codec: str = ""
    modified_time: float = 0.0
    created_time: float = 0.0

    @property
    def resolution_label(self) -> str:
        if self.width <= 0 or self.height <= 0:
            return "Unknown"
        h = self.height
        w = self.width
        # Common resolution tags
        if (w >= 3840 and h >= 2160) or (w >= 2160 and h >= 3840):
            return f"{w}x{h} (4K)"
        elif (w >= 2560 and h >= 1440) or (w >= 1440 and h >= 2560):
            return f"{w}x{h} (2K/1440p)"
        elif (w >= 1920 and h >= 1080) or (w >= 1080 and h >= 1920):
            return f"{w}x{h} (1080p)"
        elif (w >= 1280 and h >= 720) or (w >= 720 and h >= 1280):
            return f"{w}x{h} (720p)"
        elif (w >= 854 and h >= 480) or (w >= 480 and h >= 854):
            return f"{w}x{h} (480p)"
        return f"{w}x{h}"

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.size)

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)


def format_bytes(num_bytes: int) -> str:
    """Formats bytes to a human-readable string (KB, MB, GB, TB)."""
    if num_bytes < 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """Formats duration in seconds to HH:MM:SS or MM:SS."""
    if seconds <= 0:
        return "00:00"
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _get_metadata_via_cv2(file_path: Path) -> Optional[VideoMetadata]:
    """Extract metadata using OpenCV VideoCapture."""
    if not HAS_CV2:
        return None
    try:
        cap = cv2.VideoCapture(str(file_path))
        if not cap.isOpened():
            cap.release()
            return None

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)

        codec = "".join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)]).strip()
        cap.release()

        duration = (frame_count / fps) if (fps > 0 and frame_count > 0) else 0.0
        stat = file_path.stat()
        size = stat.st_size
        bitrate = (size * 8 / duration) if duration > 0 else 0.0

        return VideoMetadata(
            path=file_path,
            size=size,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            bitrate=bitrate,
            codec=codec,
            modified_time=stat.st_mtime,
            created_time=getattr(stat, "st_ctime", stat.st_mtime),
        )
    except Exception:
        return None


def _get_metadata_via_ffprobe(file_path: Path) -> Optional[VideoMetadata]:
    """Fallback metadata extractor using ffprobe if cv2 is unavailable or fails."""
    if not shutil.which("ffprobe"):
        return None
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,duration,codec_name:format=duration,size",
            "-of", "default=noprint_wrappers=1:nokey=0",
            str(file_path),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if result.returncode != 0:
            return None

        data = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()

        stat = file_path.stat()
        size = int(data.get("size", stat.st_size))
        width = int(data.get("width", 0))
        height = int(data.get("height", 0))
        codec = data.get("codec_name", "")

        duration = 0.0
        if "duration" in data and data["duration"] != "N/A":
            try:
                duration = float(data["duration"])
            except ValueError:
                duration = 0.0

        fps = 0.0
        r_frame_rate = data.get("r_frame_rate", "")
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/", 1)
            try:
                den_f = float(den)
                if den_f > 0:
                    fps = float(num) / den_f
            except ValueError:
                pass

        bitrate = (size * 8 / duration) if duration > 0 else 0.0

        return VideoMetadata(
            path=file_path,
            size=size,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            bitrate=bitrate,
            codec=codec,
            modified_time=stat.st_mtime,
            created_time=getattr(stat, "st_ctime", stat.st_mtime),
        )
    except Exception:
        return None


def get_video_metadata(file_path: Path) -> VideoMetadata:
    """
    Extracts video metadata (dimensions, duration, fps, bitrate).
    Tries cv2 first, falls back to ffprobe, then basic stat.
    """
    meta = _get_metadata_via_cv2(file_path)
    if meta is None or (meta.width == 0 and meta.height == 0):
        probe_meta = _get_metadata_via_ffprobe(file_path)
        if probe_meta is not None:
            meta = probe_meta

    if meta is None:
        try:
            stat = file_path.stat()
            meta = VideoMetadata(
                path=file_path,
                size=stat.st_size,
                modified_time=stat.st_mtime,
                created_time=getattr(stat, "st_ctime", stat.st_mtime),
            )
        except OSError:
            meta = VideoMetadata(path=file_path, size=0)

    return meta
