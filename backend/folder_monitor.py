"""
backend/folder_monitor.py

Continuously watches a source folder and auto-organizes any file that
appears in it, using auto_organizer.organize_folder().

Implemented with simple polling (checking every few seconds) rather than
OS-level file system events (which would need the external 'watchdog'
library). This keeps the project dependency-free beyond PyQt6, at the
cost of a few seconds' delay before a new file is picked up -- an
acceptable trade-off for a mini-project, and noted as a possible future
upgrade (real-time monitoring via 'watchdog').
"""

import threading
from datetime import datetime

from backend.auto_organizer import organize_folder

POLL_INTERVAL_SECONDS = 5


class FolderMonitor:
    def __init__(self, source_folder, root_folder, use_creation_date=False, on_event=None):
        self.source_folder = source_folder
        self.root_folder = root_folder
        self.use_creation_date = use_creation_date
        self.on_event = on_event
        self._thread = None
        self._stop_flag = threading.Event()

    def _run_loop(self):
        while not self._stop_flag.is_set():
            try:
                run_id, moved, skipped = organize_folder(
                    self.source_folder, self.root_folder, self.use_creation_date
                )
                if moved and self.on_event:
                    self.on_event(f"Auto-organized {len(moved)} file(s) at {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                if self.on_event:
                    self.on_event(f"Auto-organize monitor error: {e}")
            self._stop_flag.wait(POLL_INTERVAL_SECONDS)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()
