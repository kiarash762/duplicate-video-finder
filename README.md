# Duplicate Video Finder

A Python utility for detecting and managing duplicate or visually similar video files within a specified directory.

## Features

- **Multi-Stage Hashing Pipeline:**
  - **Stage 1:** Groups files by exact byte size to ignore unique files instantly.
  - **Stage 2:** Calculates a **Fast Hash** (MD5 over head, middle, and tail chunks) on size-matched files.
  - **Stage 3:** Computes a full **SHA256 Hash** for exact duplicate confirmation.
- **Perceptual Video Hashing (Optional):**
  - Extracts keyframes using OpenCV and computes image hashes to catch duplicates even if re-encoded, converted, or resized.
- **Multiprocessing & Multithreading:**
  - Utilizes `concurrent.futures` to speed up operations across multiple CPU cores.
- **Safe Handling & Dry-Run Mode:**
  - Default **Dry-Run Mode** allows reviewing candidates without altering any files.
  - Integration with `send2trash` moves deleted files safely to the system Recycle Bin/Trash instead of permanently deleting them.
- **Command-Line Interface:**
  - Full CLI support with progress bar feedback via `tqdm`.

---

## Installation

### Prerequisites

Ensure Python 3.8+ is installed on your system.

### Install Required Dependencies

```bash
pip install tqdm send2trash opencv-python pillow imagehash