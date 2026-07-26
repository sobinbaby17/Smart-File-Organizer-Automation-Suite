"""
backend/duplicate_finder.py

Finds duplicate files in a folder using content hashing (SHA-256).
Does not delete or move anything itself -- see undo_manager.quarantine_duplicates
for safely removing duplicates in an undoable way.

Skips hidden files, symlinks, and files that are too new (likely still being
written/downloaded), the same safety rules used by the rule engine.
"""

import hashlib
from pathlib import Path

from backend.safety import is_file_safe_to_touch


def hash_file(file_path, block_size=65536):
    """Compute the SHA-256 hash of a file's contents, read in chunks (safe for large files)."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            sha256.update(block)
    return sha256.hexdigest()


def scan_for_duplicates(folder_path):
    """
    Scan a folder and group files by identical content hash.
    Returns (duplicate_groups, errors):
      duplicate_groups: { hash_value: [list of file paths with that hash] }
        (only hashes with more than 1 file are included)
      errors: list of human-readable strings for any file that could not be read
    """
    folder = Path(folder_path)
    if not folder.exists():
        return {}, [f"Folder does not exist: {folder_path}"]

    hashes = {}
    errors = []

    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        if not is_file_safe_to_touch(str(entry)):
            continue
        try:
            file_hash = hash_file(entry)
        except (PermissionError, OSError) as e:
            errors.append(f"Could not read '{entry}': {e}")
            continue
        hashes.setdefault(file_hash, []).append(str(entry))

    duplicate_groups = {h: paths for h, paths in hashes.items() if len(paths) > 1}
    return duplicate_groups, errors
