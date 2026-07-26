"""
backend/scheduler.py

A lightweight background scheduler using only Python's standard library
(threading), so no extra dependency like APScheduler is required.

It periodically checks saved rules and backup jobs in the database and
runs any that are "due" based on their schedule_minutes and last_run time.
"""

import threading
import time
from datetime import datetime, timedelta

from backend.rule_engine import get_all_rules, run_rule_by_id
from backend.backup_manager import get_all_backup_jobs, run_backup_job

CHECK_INTERVAL_SECONDS = 30  # how often the scheduler checks if anything is due


class Scheduler:
    def __init__(self, on_event=None):
        """
        on_event: optional callback(str message) -- called whenever the
        scheduler runs a rule or backup, so the GUI can show a notification.
        """
        self._thread = None
        self._stop_flag = threading.Event()
        self.on_event = on_event

    def _is_due(self, schedule_minutes, last_run):
        if not schedule_minutes or schedule_minutes <= 0:
            return False
        if not last_run:
            return True
        last_run_time = datetime.fromisoformat(last_run)
        return datetime.now() >= last_run_time + timedelta(minutes=schedule_minutes)

    def _tick(self):
        for rule in get_all_rules():
            if rule["enabled"] and self._is_due(rule["schedule_minutes"], rule["last_run"]):
                run_id, moved, errors = run_rule_by_id(rule["id"])
                if self.on_event:
                    msg = f"Scheduled rule '{rule['name']}' ran: {len(moved)} file(s) moved."
                    if errors:
                        msg += f" ({len(errors)} error(s), see log)"
                    self.on_event(msg)

        for job in get_all_backup_jobs():
            if self._is_due(job["schedule_minutes"], job["last_run"]):
                archive_path, errors = run_backup_job(job["id"])
                if self.on_event:
                    if archive_path:
                        msg = f"Scheduled backup completed: {archive_path}"
                        if errors:
                            msg += f" ({len(errors)} file(s) skipped)"
                        self.on_event(msg)
                    else:
                        self.on_event(f"Scheduled backup FAILED: {'; '.join(errors)}")

    def _run_loop(self):
        while not self._stop_flag.is_set():
            try:
                self._tick()
            except Exception as e:
                if self.on_event:
                    self.on_event(f"Scheduler error: {e}")
            self._stop_flag.wait(CHECK_INTERVAL_SECONDS)

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
