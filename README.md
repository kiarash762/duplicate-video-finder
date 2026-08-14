# Duplicate Video Finder

A Python script designed to scan directories and identify duplicate video files based on file hashing or video frame analysis.

## Features

- **Recursive Scanning**: Recursively searches folders and subfolders for standard video file extensions (`.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`).
- **Duplicate Identification**: Efficiently grouping duplicates by file hash, file size, or frame-by-frame visual similarity.
- **Detailed Summary**: Lists duplicated files along with their paths, file sizes, and duration for easy inspection.
- **Safe Review**: Interactive prompts or logs to review duplicates before taking deletion or cleanup actions.

## Requirements & Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/kiarash762/duplicate-video-finder.git
   cd duplicate-video-finder
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Execute the main script by providing the target directory:

```bash
python "duplicate video finder.py" --path "/path/to/videos"
```

### Command Line Arguments

- `--path`: Target folder path containing video files to analyze.
- `--interactive`: Prompt for interactive file removal/management.

## License

Distributed under the MIT License. See `LICENSE` for more information.
