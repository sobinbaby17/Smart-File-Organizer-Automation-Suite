"""
backend/undo_manager.py

Handles safe (undoable) removal of duplicate files via quarantine,
and reversing any logged action -- single action, full run, or by ID.
"""

import os
import shutil
from datetime import datetime

from backend.database import get_connection

QUARANTINE_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".quarantine"
)


def quarantine_duplicates(duplicate_groups, keep_first=True, run_id=None):
    """
    Moves duplicate files into a quarantine folder instead of deleting them,
    so the action can be undone later. Keeps one file per group by default.
    """
    if run_id is None:
        run_id = "dup_" + datetime.now().strftime("%Y%m%d%H%M%S%f")

    os.makedirs(QUARANTINE_FOLDER, exist_ok=True)
    conn = get_connection()
    moved_count = 0

    for file_hash, paths in duplicate_groups.items():
        files_to_quarantine = paths[1:] if keep_first else paths
        for path in files_to_quarantine:
            if not os.path.exists(path):
                continue
            filename = os.path.basename(path)
            dest_path = os.path.join(QUARANTINE_FOLDER, filename)

            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                dest_path = os.path.join(QUARANTINE_FOLDER, f"{base}_{int(datetime.now().timestamp())}{ext}")

            shutil.move(path, dest_path)
            moved_count += 1

            conn.execute(
                "INSERT INTO actions (run_id, action, source_path, dest_path, timestamp) VALUES (?, ?, ?, ?, ?)",
                (run_id, "quarantine_duplicate", path, dest_path, datetime.now().isoformat()),
            )

    conn.commit()
    conn.close()
    return run_id, moved_count


def get_action_history(limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, run_id, action, source_path, dest_path, timestamp FROM actions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _reverse_single_action(conn, action_id, action, source_path, dest_path):
    if action in ("move", "quarantine_duplicate", "auto_organize"):
        if dest_path and os.path.exists(dest_path):
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            shutil.move(dest_path, source_path)
            return True
    return False


def get_quarantine_info():
    """Return (file_count, total_size_kb) of everything currently sitting in quarantine."""
    if not os.path.isdir(QUARANTINE_FOLDER):
        return 0, 0.0
    count = 0
    total_bytes = 0
    for entry in os.scandir(QUARANTINE_FOLDER):
        if entry.is_file():
            count += 1
            try:
                total_bytes += entry.stat().st_size
            except OSError:
                pass
    return count, total_bytes / 1024


def empty_quarantine():
    """
    PERMANENTLY deletes everything in the quarantine folder and removes the
    matching 'quarantine_duplicate' log entries. This cannot be undone --
    the GUI must confirm with the user before calling this.
    Returns the number of files permanently deleted.
    """
    if not os.path.isdir(QUARANTINE_FOLDER):
        return 0

    deleted = 0
    conn = get_connection()

    for entry in os.scandir(QUARANTINE_FOLDER):
        if entry.is_file():
            try:
                os.remove(entry.path)
                deleted += 1
            except OSError:
                continue
            conn.execute(
                "DELETE FROM actions WHERE action = 'quarantine_duplicate' AND dest_path = ?",
                (entry.path,),
            )

    conn.commit()
    conn.close()
    return deleted


def undo_last_action():
    conn = get_connection()
    row = conn.execute(
        "SELECT id, action, source_path, dest_path FROM actions ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if not row:
        conn.close()
        return False, "Nothing to undo."

    success = _reverse_single_action(conn, row["id"], row["action"], row["source_path"], row["dest_path"])
    conn.execute("DELETE FROM actions WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()

    if success:
        return True, f"Restored '{row['dest_path']}' -> '{row['source_path']}'"
    return False, f"Could not restore -- file missing at '{row['dest_path']}'"


def undo_rule_run(run_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, action, source_path, dest_path FROM actions WHERE run_id = ? ORDER BY id DESC",
        (run_id,),
    ).fetchall()

    if not rows:
        conn.close()
        return 0, 0

    reversed_count = 0
    for row in rows:
        if _reverse_single_action(conn, row["id"], row["action"], row["source_path"], row["dest_path"]):
            reversed_count += 1
        conn.execute("DELETE FROM actions WHERE id = ?", (row["id"],))

    conn.commit()
    conn.close()
    return reversed_count, len(rows)


def undo_action_by_id(action_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, action, source_path, dest_path FROM actions WHERE id = ?",
        (action_id,),
    ).fetchone()

    if not row:
        conn.close()
        return False, f"No action found with ID {action_id}."

    success = _reverse_single_action(conn, row["id"], row["action"], row["source_path"], row["dest_path"])
    conn.execute("DELETE FROM actions WHERE id = ?", (action_id,))
    conn.commit()
    conn.close()

    if success:
        return True, f"Restored '{row['dest_path']}' -> '{row['source_path']}'"
    return False, f"Could not restore -- file missing at '{row['dest_path']}'"
