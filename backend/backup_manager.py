"""
backend/backup_manager.py

Compresses a source folder into a zip archive inside a destination folder.
Backup jobs can be saved to the database for scheduling.

Builds the zip file-by-file (instead of shutil.make_archive) so that a
single broken symlink, permission-denied file, or file that disappears
mid-backup does not corrupt or abort the entire archive -- that file is
just skipped and reported, and the backup continues.
"""

import os
import zipfile
from datetime import datetime

from backend.database import get_connection
from backend.safety import is_file_safe_to_touch, validate_source_dest


def create_backup(source_folder, destination_folder):
    """
    Zip source_folder (recursively) into destination_folder.
    Returns (archive_path, errors). archive_path is None if the backup
    could not be created at all (e.g. invalid folders).
    """
    is_valid, error_msg = validate_source_dest(source_folder, destination_folder)
    if not is_valid:
        return None, [error_msg]

    if not os.path.isdir(source_folder):
        return None, [f"Source folder does not exist: {source_folder}"]

    try:
        os.makedirs(destination_folder, exist_ok=True)
    except OSError as e:
        return None, [f"Could not create destination folder: {e}"]

    folder_name = os.path.basename(os.path.normpath(source_folder))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(destination_folder, f"{folder_name}_backup_{timestamp}.zip")

    errors = []
    files_backed_up = 0

    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_folder):
                # never recurse into our own quarantine or backup output folders
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

                for filename in files:
                    full_path = os.path.join(root, filename)

                    if not is_file_safe_to_touch(full_path):
                        continue  # skip hidden files, symlinks, very-fresh files

                    arcname = os.path.relpath(full_path, source_folder)
                    try:
                        zf.write(full_path, arcname)
                        files_backed_up += 1
                    except (PermissionError, OSError, FileNotFoundError) as e:
                        errors.append(f"Skipped '{full_path}': {e}")
    except OSError as e:
        return None, [f"Could not create archive: {e}"]

    if files_backed_up == 0 and not errors:
        errors.append("No files were found to back up (folder may be empty).")

    conn = get_connection()
    conn.execute(
        "INSERT INTO actions (run_id, action, source_path, dest_path, timestamp) VALUES (?, ?, ?, ?, ?)",
        (f"backup_{timestamp}", "backup", source_folder, archive_path, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    return archive_path, errors


def save_backup_job(source_folder, destination_folder, schedule_minutes=0):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO backup_jobs (source_folder, destination_folder, schedule_minutes) VALUES (?, ?, ?)",
        (source_folder, destination_folder, schedule_minutes),
    )
    conn.commit()
    job_id = cur.lastrowid
    conn.close()
    return job_id


def get_all_backup_jobs():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM backup_jobs ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_backup_job(job_id):
    conn = get_connection()
    conn.execute("DELETE FROM backup_jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


def run_backup_job(job_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM backup_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        conn.close()
        return None, [f"No backup job found with ID {job_id}."]

    archive_path, errors = create_backup(row["source_folder"], row["destination_folder"])
    conn.execute("UPDATE backup_jobs SET last_run = ? WHERE id = ?", (datetime.now().isoformat(), job_id))
    conn.commit()
    conn.close()
    return archive_path, errors
