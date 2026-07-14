import os
import shutil
import subprocess

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts"}

def get_video_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return float(result.stdout.strip())
    except:
        return None

def find_duplicates(input_folder):
    same_folder = os.path.join(input_folder, "same")
    os.makedirs(same_folder, exist_ok=True)

    video_info = {}  # {filename: (size, duration)}

    # scan files
    for file in os.listdir(input_folder):
        path = os.path.join(input_folder, file)
        if not os.path.isfile(path):
            continue

        ext = os.path.splitext(file)[1].lower()
        if ext not in VIDEO_EXTENSIONS:
            continue

        size = os.path.getsize(path)
        duration = get_video_duration(path)

        video_info[file] = (size, duration)

    # check duplicates
    checked = set()
    for f1, (size1, dur1) in video_info.items():
        for f2, (size2, dur2) in video_info.items():
            if f1 == f2 or (f1, f2) in checked or (f2, f1) in checked:
                continue

            # "اگر حتی یکی برابر بود"
            if size1 == size2 or (dur1 is not None and dur1 == dur2):
                # move f2 to same folder
                src = os.path.join(input_folder, f2)
                dst = os.path.join(same_folder, f2)
                shutil.move(src, dst)

            checked.add((f1, f2))

    print("all files moved to 'same'")

if __name__ == "__main__":
    folder = input("Enter the path of the movies folder: ").strip()
    find_duplicates(folder)