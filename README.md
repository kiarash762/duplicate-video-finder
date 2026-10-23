# Duplicate Video Finder

A blazing-fast, multi-stage duplicate video detection and management tool. Features both high-throughput **exact byte-level deduplication** and **perceptual visual hashing** to catch duplicate videos even if they have been re-encoded, resized, compressed, or converted between container formats.

---

## Key Features

- **Multi-Stage Exact Hashing Pipeline:**
  - **Stage 1 (Size Gate):** Groups files by exact byte size to eliminate unique files instantly.
  - **Stage 2 (Head Hash):** Reads the initial 64 KB block to reject files with different headers.
  - **Stage 3 (Multi-Chunk Sample):** Computes BLAKE2b hash over head, middle, and tail chunks.
  - **Stage 4 (Full BLAKE2b Stream):** Streams candidate files with buffered 4 MB chunks for definitive confirmation.
  - **Hardlink & Inode Safety:** Identifies hardlinks sharing the same inode to avoid accidental double-deletion.

- **Perceptual Visual Similarity Detection:**
  - Decoupled from file size: identifies duplicates across different resolutions (e.g. 1080p vs 720p), bitrates, codecs, and container formats (.mp4, .mkv, .avi, .webm, etc.).
  - **Duration Gating:** Prunes video pairs differing by more than a configurable duration tolerance (default 5%) before running expensive frame extraction.
  - **Keyframe Fingerprinting:** Extracts evenly spaced keyframes across the middle 80% of playback (bypassing intro/outro titles).
  - **Difference & Perceptual Hashing:** Compares frames using Difference Hash (`dhash`), DCT Perceptual Hash (`phash`), or Average Hash (`ahash`) with configurable Hamming distance threshold.
  - **Graph Clustering:** Disjoint Set Union (Union-Find) automatically clusters multi-video duplicates into clean groups.

- **Intelligent Keep Strategies:**
  - `--keep highest-res` *(default)*: Retains the highest-resolution video (pixel count and bitrate) and marks lower-quality copies for removal.
  - `--keep largest`: Keeps the largest file size.
  - `--keep smallest`: Keeps the smallest file size (ideal when disk space is critically constrained).
  - `--keep oldest`: Keeps the original/earliest created file.
  - `--keep newest`: Keeps the latest modified file.
  - `--keep shortest-path`: Keeps the file with the cleanest/shortest directory path.

- **Safe Handling by Default:**
  - **Dry-Run Mode Active by Default:** Previews candidates without deleting or modifying any file on disk.
  - **Recycle Bin / Trash Integration:** Deletion moves files safely to the system Recycle Bin via `send2trash` rather than permanently deleting them (permanent deletion available via `--permanent`).
  - **Interactive Review Mode (`-i` / `--interactive`):** Side-by-side terminal comparison displaying resolution, duration, size, and path with interactive keep/skip prompts.

- **Comprehensive Reporting & Exporting:**
  - Formatted terminal report with human-readable file sizes and estimated reclaimable disk space.
  - `--export-html`: Generates an interactive, standalone dark-mode HTML report.
  - `--export-json`: Machine-readable JSON summary for scripting and pipelines.
  - `--export-csv`: Tabular spreadsheet export with metadata columns.

- **Modern Architecture & Full Backward Compatibility:**
  - Clean modular package structure (`duplicate_video_finder/`).
  - Standard `pyproject.toml` and CLI entrypoint (`duplicate-video-finder`).
  - Backwards-compatible script wrappers (`python duplicate_video_finder.py` and `python "duplicate video finder.py"`).

---

## Installation

### Prerequisites

- Python 3.8 or higher.
- [FFmpeg](https://ffmpeg.org/) (optional, recommended for extended codec support).

### Install via pip

Clone the repository and install dependencies:

```bash
git clone https://github.com/kiarash762/duplicate-video-finder.git
cd duplicate-video-finder
pip install -r requirements.txt
```

Or install in editable mode to register the `duplicate-video-finder` command:

```bash
pip install -e .
```

---

## Usage

### 1. Basic Exact Scan (Safe Dry-Run Preview)

Scan a folder for identical video duplicates without modifying any files:

```bash
duplicate-video-finder "D:/Movies"
```

*Or run directly via Python:*
```bash
python duplicate_video_finder.py "D:/Movies"
```

### 2. Detect Re-encoded or Resized Duplicates (Perceptual Mode)

Detect videos with the same visual content regardless of resolution, bitrate, or format:

```bash
duplicate-video-finder "D:/Movies" --mode perceptual
```

### 3. Combined Pipeline (Exact + Perceptual)

Run exact deduplication first, followed by visual perceptual comparison on remaining videos:

```bash
duplicate-video-finder "D:/Movies" --mode both --keep highest-res
```

### 4. Interactive Review Mode

Inspect each duplicate group side-by-side in the terminal before taking action:

```bash
duplicate-video-finder "D:/Movies" --interactive
```

### 5. Execute Deletion (Recycle Bin / Trash)

Safely move redundant duplicate files to the system Recycle Bin:

```bash
duplicate-video-finder "D:/Movies" --delete
```

To permanently remove files instead of sending them to the Recycle Bin:

```bash
duplicate-video-finder "D:/Movies" --delete --permanent
```

### 6. Export Reports (HTML, JSON, CSV)

Generate visual and data reports:

```bash
duplicate-video-finder "D:/Movies" \
  --export-html report.html \
  --export-json duplicates.json \
  --export-csv duplicates.csv
```

---

## Command-Line Options

| Option | Description | Default |
|---|---|---|
| `directory` | Target directory to scan | *(Required)* |
| `--mode, -m` | Detection mode: `exact`, `perceptual`, or `both` | `exact` |
| `--keep, -k` | Strategy to select file to keep: `highest-res`, `largest`, `smallest`, `oldest`, `newest`, `shortest-path` | `highest-res` |
| `--delete` | Execute file removal (default sends to Recycle Bin / Trash) | `False` (Dry-Run) |
| `--permanent` | Permanently delete files instead of sending to Recycle Bin | `False` |
| `--interactive, -i`| Interactively inspect and decide for each duplicate group | `False` |
| `--threshold` | Perceptual Hamming distance threshold (0–64, lower is stricter) | `8` |
| `--hash-algo` | Visual hash algorithm: `dhash` (difference), `phash` (DCT), `ahash` (average) | `dhash` |
| `--keyframes` | Number of keyframes extracted per video for visual comparison | `5` |
| `--duration-tolerance` | Max duration variance allowed between candidates (percent) | `5.0` |
| `--min-size` | Ignore files smaller than this size in megabytes (MB) | `0` |
| `--exclude` | Glob pattern to exclude directories or files (can be repeated) | `[]` |
| `--workers, -w` | Number of worker threads for parallel hashing/fingerprinting | `CPU Count` |
| `--export-html` | File path to export standalone dark-mode HTML report | `None` |
| `--export-json` | File path to export JSON report | `None` |
| `--export-csv` | File path to export CSV report | `None` |
| `--verbose, -v` | Enable verbose debug logging | `False` |
| `--quiet, -q` | Suppress non-error console output | `False` |

---

## Architecture

```
                        Input Directory
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
            [--mode exact]      [--mode perceptual]
                    │                   │
            Stage 1: File Size          Stage 1: Metadata & Duration Probe
                    │                   │
            Stage 2: Head Hash          Stage 2: Duration Similarity Gate
                    │                   │
            Stage 3: Multi-Chunk Hash   Stage 3: Evenly Spaced Keyframe Sampling
                    │                   │
            Stage 4: Full BLAKE2b       Stage 4: Frame Hashing (dhash / phash)
                    │                   │
                    │                   Stage 5: Hamming Distance & DSU Clustering
                    │                   │
                    └─────────┬─────────┘
                              ▼
                   Duplicate Groups Found
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
            Keep Strategy Selection   Action Execution
            (highest-res, largest,    (Dry-Run, Recycle Bin,
             oldest, shortest-path)    Permanent, Interactive)
                              │
                              ▼
            Reporting (Console, HTML, JSON, CSV)
```

---

## Running the Tests

To run the automated test suite:

```bash
pytest
```

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
