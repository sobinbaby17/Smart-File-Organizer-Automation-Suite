"""
backend/safety.py

Shared safety checks used across the app to prevent real-world disasters:
- picking a dangerous folder (home directory root, system folders) as a source
- source and destination folder being the same or nested in a conflicting way
- catching files that are still being written to (in-progress downloads/copies)
"""

import os
import time

# Folders that should never be allowed as a rule/backup "source" -- moving or
# deleting files from these could break the OS or wipe a user's entire home
# directory by accident.
_PROTECTED_PATHS = [
    "/", "/root", "/home", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64",
    "/boot", "/dev", "/proc", "/sys", "/var", "/opt", "/System", "/Windows",
    "C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
]

# A file must be at least this many seconds old before any rule or duplicate
# scan will touch it -- protects files that are still being downloaded or
# copied into the folder at the moment the scan runs.
MIN_FILE_AGE_SECONDS = 10


def normalize(path):
    return os.path.normpath(os.path.abspath(os.path.expanduser(path)))


def is_protected_path(path):
    """Return True if `path` is a folder that should never be used as a source."""
    norm = normalize(path)
    home = normalize(os.path.expanduser("~"))

    if norm in (normalize(p) for p in _PROTECTED_PATHS):
        return True
    if norm == home:
        # the home folder itself (not a subfolder inside it) is too broad a target
        return True
    return False


def validate_source_dest(source_folder, dest_folder):
    """
    Returns (is_valid, error_message). Checks:
      - source folder isn't a protected system/home root
      - source and destination aren't the same folder
      - destination isn't the same as, or a parent of, the source (would create a loop)
    """
    src = normalize(source_folder)
    dst = normalize(dest_folder)

    if is_protected_path(src):
        return False, f"'{source_folder}' is a protected system folder and cannot be used as a source."

    if src == dst:
        return False, "Source and destination folders cannot be the same."

    if src.startswith(dst + os.sep) or dst == src:
        return False, "Destination folder cannot be a parent of the source folder (this would create a loop)."

    return True, ""


def is_file_safe_to_touch(file_path):
    """
    Returns True if a file is safe to move/hash/backup right now:
      - not a hidden file (starts with '.')
      - not a symlink (broken symlinks crash hashing/zipping)
      - old enough that it's unlikely to still be mid-download/copy
    """
    name = os.path.basename(file_path)
    if name.startswith("."):
        return False
    if os.path.islink(file_path):
        return False
    try:
        age_seconds = time.time() - os.path.getmtime(file_path)
    except OSError:
        return False
    if age_seconds < MIN_FILE_AGE_SECONDS:
        return False
    return True
