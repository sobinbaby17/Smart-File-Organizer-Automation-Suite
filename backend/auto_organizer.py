"""
backend/auto_organizer.py

Automatically organizes files into a Type -> Year -> Month -> Week -> Day
folder hierarchy, based on file extension and modification date.

Example: a .jpg file modified on 12 July 2026 goes to:
    <root>/Images/2026/July/Week 2/Day 12/photo.jpg

This module reuses the same 'actions' log as rule_engine.py, so every
file it moves is automatically undoable through undo_manager.py --
no separate undo logic needed.
"""

import os
import shutil
import time
from pathlib import Path
from datetime import datetime

from backend.database import get_connection
from backend.safety import validate_source_dest, is_file_safe_to_touch

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Maps a category folder name to the file extensions that belong in it.
# Anything not listed here falls into "Others".
CATEGORY_MAP = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic", ".svg"],
    "PDFs": [".pdf"],
    "Excel": [".xls", ".xlsx", ".csv"],
    "Word": [".doc", ".docx", ".odt", ".rtf"],
    "PowerPoint": [".ppt", ".pptx"],
    "Videos": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv"],
    "Audio": [".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
}

DEFAULT_CATEGORY = "Others"


def get_category(file_path):
    """Return the category folder name for a file, based on its extension."""
    ext = Path(file_path).suffix.lower()
    for category, extensions in CATEGORY_MAP.items():
        if ext in extensions:
            return category
    return DEFAULT_CATEGORY


def get_date_folder_parts(dt):
    """
    Given a datetime, return (year_str, month_name, week_str, day_str)
    e.g. datetime(2026, 7, 12) -> ("2026", "July", "Week 2", "Day 12")
    Week number is simply which 7-day block of the month the day falls in.
    """
    year_str = str(dt.year)
    month_name = MONTH_NAMES[dt.month - 1]
    week_number = ((dt.day - 1) // 7) + 1
    week_str = f"Week {week_number}"
    day_str = f"Day {dt.day}"
    return year_str, month_name, week_str, day_str


def build_destination_folder(root_folder, category, dt):
    """Build (and create if needed) the full nested folder path for a file."""
    year_str, month_name, week_str, day_str = get_date_folder_parts(dt)
    dest_folder = os.path.join(root_folder, category, year_str, month_name, week_str, day_str)
    os.makedirs(dest_folder, exist_ok=True)
    return dest_folder


def organize_file(file_path, root_folder, run_id, use_creation_date=False):
    """
    Move a single file into its Type/Year/Month/Week/Day folder under root_folder.
    Returns the destination path, or None if the file was skipped (unsafe to touch).
    """
    if not is_file_safe_to_touch(file_path):
        return None

    stat = os.stat(file_path)
    timestamp = stat.st_ctime if use_creation_date else stat.st_mtime
    dt = datetime.fromtimestamp(timestamp)

    category = get_category(file_path)
    dest_folder = build_destination_folder(root_folder, category, dt)

    filename = os.path.basename(file_path)
    dest_path = os.path.join(dest_folder, filename)

    if os.path.exists(dest_path):
        base, ext = os.path.splitext(filename)
        dest_path = os.path.join(dest_folder, f"{base}_{int(time.time())}{ext}")

    shutil.move(file_path, dest_path)

    conn = get_connection()
    conn.execute(
        "INSERT INTO actions (run_id, action, source_path, dest_path, timestamp) VALUES (?, ?, ?, ?, ?)",
        (run_id, "auto_organize", file_path, dest_path, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    return dest_path


def organize_folder(source_folder, root_folder, use_creation_date=False, run_id=None, progress_callback=None):
    """
    Scan source_folder (non-recursive) and organize every file in it into
    root_folder's Type/Year/Month/Week/Day hierarchy.
    Returns (run_id, list_of_moved_pairs, skipped_count).

    progress_callback, if given, is called as progress_callback(done, total)
    after each file is processed -- used to drive a progress bar in the GUI.
    This is optional so existing callers are unaffected.
    """
    is_valid, error = validate_source_dest(source_folder, root_folder)
    if not is_valid:
        raise ValueError(error)

    if run_id is None:
        run_id = "autoorg_" + datetime.now().strftime("%Y%m%d%H%M%S%f")

    moved = []
    skipped = 0

    folder = Path(source_folder)
    if not folder.exists():
        return run_id, moved, skipped

    entries = [e for e in folder.iterdir() if e.is_file()]
    total = len(entries)

    for i, entry in enumerate(entries, start=1):
        dest = organize_file(str(entry), root_folder, run_id, use_creation_date)
        if dest:
            moved.append((str(entry), dest))
        else:
            skipped += 1
        if progress_callback:
            progress_callback(i, total)

    return run_id, moved, skipped
