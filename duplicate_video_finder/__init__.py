"""
Duplicate Video Finder
A fast, intelligent tool for detecting exact and perceptual video duplicates.
"""

__version__ = "2.0.0"

from .metadata import VideoMetadata, get_video_metadata, format_bytes, format_duration
from .core import find_exact_duplicates, scan_videos
from .perceptual import find_perceptual_duplicates
from .actions import KeepStrategy, apply_keep_strategy, delete_file

__all__ = [
    "__version__",
    "VideoMetadata",
    "get_video_metadata",
    "format_bytes",
    "format_duration",
    "find_exact_duplicates",
    "scan_videos",
    "find_perceptual_duplicates",
    "KeepStrategy",
    "apply_keep_strategy",
    "delete_file",
]
