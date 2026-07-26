"""
backend/rule_engine.py

Scans folders, applies move rules, and manages saved rules in the database
so they persist between app launches and can be scheduled.
"""

import os
import shutil
import time
from pathlib import Path
from datetime import datetime

from backend.database import get_connection
from backend.safety import is_file_safe_to_touch, validate_source_dest


def scan_folder(folder_path):
    """
    Return a list of dicts describing each file in the folder.
    Skips hidden files, symlinks, and files that are too new (likely still
    being written/downloaded) -- see backend/safety.py.
    """
    files = []
    folder = Path(folder_path)
    if not folder.exists():
        return files

    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        if not is_file_safe_to_touch(str(entry)):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        age_days = (time.time() - stat.st_mtime) / 86400
        files.append({
            "path": str(entry),
            "name": entry.name,
            "extension": entry.suffix.lower(),
            "size_kb": stat.st_size / 1024,
            "age_days": age_days,
        })
    return files


def file_matches_rule(file_info, extension=None, older_than_days=None, keyword=None):
    """Check if a single file matches the rule's conditions."""
    if extension and file_info["extension"] != extension.lower():
        return False
    if older_than_days is not None and file_info["age_days"] < older_than_days:
        return False
    if keyword:
        if keyword.lower() not in file_info["name"].lower():
            return False
    return True


def apply_move_rule(source_folder, dest_folder, extension=None, older_than_days=0, keyword=None, run_id=None):
    """
    Scan source_folder, find files matching the rule, move them to dest_folder,
    and log every move. Returns (run_id, list_of_moved_pairs, list_of_errors).

    Validates source/destination folders first (see backend/safety.py) and
    continues past individual file errors instead of aborting the whole run --
    a single locked or permission-denied file will not stop the others.
    """
    is_valid, error_msg = validate_source_dest(source_folder, dest_folder)
    if not is_valid:
        return run_id, [], [error_msg]

    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")

    try:
        os.makedirs(dest_folder, exist_ok=True)
    except OSError as e:
        return run_id, [], [f"Could not create destination folder: {e}"]

    files = scan_folder(source_folder)
    moved = []
    errors = []

    conn = get_connection()

    for f in files:
        if file_matches_rule(f, extension=extension, older_than_days=older_than_days, keyword=keyword):
            source_path = f["path"]
            dest_path = os.path.join(dest_folder, f["name"])

            if os.path.exists(dest_path):
                base, ext = os.path.splitext(f["name"])
                dest_path = os.path.join(dest_folder, f"{base}_{int(time.time())}{ext}")

            try:
                shutil.move(source_path, dest_path)
            except (OSError, PermissionError, shutil.Error) as e:
                errors.append(f"Could not move '{source_path}': {e}")
                continue

            moved.append((source_path, dest_path))

            conn.execute(
                "INSERT INTO actions (run_id, action, source_path, dest_path, timestamp) VALUES (?, ?, ?, ?, ?)",
                (run_id, "move", source_path, dest_path, datetime.now().isoformat()),
            )

    conn.commit()
    conn.close()

    return run_id, moved, errors


# ---------- Persistent rule storage (for GUI + scheduler) ----------

def save_rule(name, source_folder, dest_folder, extension, older_than_days=0, schedule_minutes=0, enabled=1, keyword=""):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO rules (name, source_folder, dest_folder, extension, older_than_days, schedule_minutes, enabled, keyword) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, source_folder, dest_folder, extension, older_than_days, schedule_minutes, enabled, keyword),
    )
    conn.commit()
    rule_id = cur.lastrowid
    conn.close()
    return rule_id


def get_all_rules():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM rules ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_rule(rule_id):
    conn = get_connection()
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()


def mark_rule_run(rule_id):
    conn = get_connection()
    conn.execute("UPDATE rules SET last_run = ? WHERE id = ?", (datetime.now().isoformat(), rule_id))
    conn.commit()
    conn.close()


def run_rule_by_id(rule_id):
    """Fetch a saved rule and execute it. Used by both the GUI 'Run Now' button and the scheduler."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    conn.close()
    if not row:
        return None, [], [f"No rule found with ID {rule_id}."]

    run_id, moved, errors = apply_move_rule(
        source_folder=row["source_folder"],
        dest_folder=row["dest_folder"],
        extension=row["extension"],
        older_than_days=row["older_than_days"],
        keyword=row["keyword"] if "keyword" in row.keys() else None,
    )
    mark_rule_run(rule_id)
    return run_id, moved, errors
