"""
gui/main_window.py

The main application window. Built with PyQt6, organized as tabs:
  - Rules        : create/run/delete file organization rules
  - Duplicates    : scan a folder and quarantine duplicate files
  - Activity Log  : view history and undo actions
  - Backup        : configure and run folder backups
  - Dashboard     : summary of everything above + scheduler on/off
"""

import os
import sys

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QSpinBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QMessageBox, QGroupBox,
    QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QTimer

from backend.database import init_db
from backend.rule_engine import save_rule, get_all_rules, delete_rule, run_rule_by_id
from backend.duplicate_finder import scan_for_duplicates
from backend.undo_manager import (
    quarantine_duplicates, get_action_history, undo_last_action,
    undo_action_by_id, get_quarantine_info, empty_quarantine,
)
from backend.backup_manager import (
    save_backup_job, get_all_backup_jobs, delete_backup_job, run_backup_job
)
from backend.scheduler import Scheduler
from backend.safety import validate_source_dest
from backend.auto_organizer import organize_folder, CATEGORY_MAP, DEFAULT_CATEGORY
from backend.folder_monitor import FolderMonitor


class FolderPicker(QWidget):
    """A small reusable widget: text field + Browse button for picking a folder."""

    def __init__(self, placeholder=""):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText(placeholder)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(self.line_edit)
        layout.addWidget(browse_btn)
        self.setLayout(layout)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.line_edit.setText(folder)

    def text(self):
        return self.line_edit.text().strip()


# ---------------------------------------------------------------- Rules Tab

class RulesTab(QWidget):
    def __init__(self, status_callback):
        super().__init__()
        self.status_callback = status_callback
        layout = QVBoxLayout()

        form_box = QGroupBox("Create New Rule")
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.source_picker = FolderPicker("Folder to watch")
        self.dest_picker = FolderPicker("Folder to move matching files into")
        self.extension_input = QLineEdit()
        self.extension_input.setPlaceholderText(".pdf")
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("e.g. client1 (optional -- leave blank to match all)")
        self.age_input = QSpinBox()
        self.age_input.setRange(0, 3650)
        self.age_input.setSuffix(" days old (minimum)")
        self.schedule_input = QSpinBox()
        self.schedule_input.setRange(0, 100000)
        self.schedule_input.setSuffix(" minutes (0 = manual only)")
        self.enabled_checkbox = QCheckBox("Enabled")
        self.enabled_checkbox.setChecked(True)

        form.addRow("Rule name:", self.name_input)
        form.addRow("Source folder:", self.source_picker)
        form.addRow("Destination folder:", self.dest_picker)
        form.addRow("File extension:", self.extension_input)
        form.addRow("Filename must contain:", self.keyword_input)
        form.addRow("Minimum age:", self.age_input)
        form.addRow("Auto-run every:", self.schedule_input)
        form.addRow("", self.enabled_checkbox)

        save_btn = QPushButton("Save Rule")
        save_btn.clicked.connect(self.save_new_rule)
        form.addRow("", save_btn)

        form_box.setLayout(form)
        layout.addWidget(form_box)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Source", "Destination", "Extension", "Keyword", "Schedule (min)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("Run Selected Now")
        run_btn.clicked.connect(self.run_selected)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.refresh()

    def save_new_rule(self):
        name = self.name_input.text().strip() or "Unnamed Rule"
        source = self.source_picker.text()
        dest = self.dest_picker.text()
        extension = self.extension_input.text().strip()

        if not source or not dest or not extension:
            QMessageBox.warning(self, "Missing info", "Source folder, destination folder, and extension are required.")
            return
        if not os.path.isdir(source):
            QMessageBox.warning(self, "Invalid folder", f"Source folder does not exist:\n{source}")
            return

        is_valid, error_msg = validate_source_dest(source, dest)
        if not is_valid:
            QMessageBox.warning(self, "Unsafe folder choice", error_msg)
            return

        save_rule(
            name=name, source_folder=source, dest_folder=dest, extension=extension,
            older_than_days=self.age_input.value(), schedule_minutes=self.schedule_input.value(),
            enabled=1 if self.enabled_checkbox.isChecked() else 0,
            keyword=self.keyword_input.text().strip(),
        )
        self.status_callback(f"Rule '{name}' saved.")
        self.name_input.clear()
        self.extension_input.clear()
        self.keyword_input.clear()
        self.refresh()

    def refresh(self):
        rules = get_all_rules()
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            self.table.setItem(row, 0, QTableWidgetItem(str(rule["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(rule["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(rule["source_folder"]))
            self.table.setItem(row, 3, QTableWidgetItem(rule["dest_folder"]))
            self.table.setItem(row, 4, QTableWidgetItem(rule["extension"]))
            self.table.setItem(row, 5, QTableWidgetItem(rule.get("keyword", "") or ""))
            self.table.setItem(row, 6, QTableWidgetItem(str(rule["schedule_minutes"])))

    def _selected_rule_id(self):
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        return int(self.table.item(row, 0).text())

    def run_selected(self):
        rule_id = self._selected_rule_id()
        if rule_id is None:
            QMessageBox.information(self, "No selection", "Select a rule first.")
            return
        run_id, moved, errors = run_rule_by_id(rule_id)
        if errors:
            QMessageBox.warning(self, "Completed with issues",
                                 f"{len(moved)} file(s) moved, but {len(errors)} issue(s) occurred:\n\n" + "\n".join(errors[:5]))
        self.status_callback(f"Rule run complete: {len(moved)} file(s) moved" + (f", {len(errors)} error(s)" if errors else "."))

    def delete_selected(self):
        rule_id = self._selected_rule_id()
        if rule_id is None:
            QMessageBox.information(self, "No selection", "Select a rule first.")
            return
        delete_rule(rule_id)
        self.status_callback("Rule deleted.")
        self.refresh()


# ----------------------------------------------------------- Duplicates Tab

class DuplicatesTab(QWidget):
    def __init__(self, status_callback):
        super().__init__()
        self.status_callback = status_callback
        self.last_groups = {}
        layout = QVBoxLayout()

        scan_row = QHBoxLayout()
        self.folder_picker = FolderPicker("Folder to scan for duplicates")
        scan_btn = QPushButton("Scan for Duplicates")
        scan_btn.clicked.connect(self.scan)
        scan_row.addWidget(self.folder_picker)
        scan_row.addWidget(scan_btn)
        layout.addLayout(scan_row)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(QLabel("Duplicate files found (first file in each group is kept automatically):"))
        layout.addWidget(self.list_widget)

        quarantine_btn = QPushButton("Quarantine Duplicates (Safe, Undoable)")
        quarantine_btn.clicked.connect(self.quarantine)
        layout.addWidget(quarantine_btn)

        quarantine_box = QGroupBox("Quarantine Folder")
        q_layout = QVBoxLayout()
        self.quarantine_status_label = QLabel()
        q_layout.addWidget(self.quarantine_status_label)
        empty_btn = QPushButton("Permanently Empty Quarantine")
        empty_btn.clicked.connect(self.empty_quarantine_clicked)
        q_layout.addWidget(empty_btn)
        quarantine_box.setLayout(q_layout)
        layout.addWidget(quarantine_box)

        self.setLayout(layout)
        self.refresh_quarantine_status()

    def refresh_quarantine_status(self):
        count, size_kb = get_quarantine_info()
        if count == 0:
            self.quarantine_status_label.setText("Quarantine is empty.")
        else:
            self.quarantine_status_label.setText(f"{count} file(s) in quarantine, {size_kb:.1f} KB total.")

    def empty_quarantine_clicked(self):
        count, size_kb = get_quarantine_info()
        if count == 0:
            QMessageBox.information(self, "Nothing to empty", "Quarantine is already empty.")
            return

        confirm = QMessageBox.question(
            self, "Permanently Delete Quarantined Files",
            f"This will PERMANENTLY delete {count} file(s) ({size_kb:.1f} KB) from quarantine.\n"
            "This CANNOT be undone.\n\n"
            "Only do this after you're confident you don't need these files.\n\n"
            "Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        deleted = empty_quarantine()
        self.status_callback(f"Permanently deleted {deleted} file(s) from quarantine.")
        self.refresh_quarantine_status()

    def scan(self):
        folder = self.folder_picker.text()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Invalid folder", "Please choose a valid folder to scan.")
            return

        self.last_groups, errors = scan_for_duplicates(folder)
        self.list_widget.clear()

        if errors:
            QMessageBox.warning(self, "Some files were skipped",
                                 f"{len(errors)} file(s) could not be read:\n\n" + "\n".join(errors[:5]))

        if not self.last_groups:
            self.list_widget.addItem("No duplicate files found.")
            self.status_callback("Scan complete: no duplicates found.")
            return

        for i, (file_hash, paths) in enumerate(self.last_groups.items(), start=1):
            self.list_widget.addItem(f"--- Group {i} ---")
            for j, p in enumerate(paths):
                marker = "(KEEP)" if j == 0 else "(will be quarantined)"
                self.list_widget.addItem(f"   {p}  {marker}")

        self.status_callback(f"Scan complete: {len(self.last_groups)} duplicate group(s) found.")

    def quarantine(self):
        if not self.last_groups:
            QMessageBox.information(self, "Nothing to do", "Scan a folder first.")
            return

        total_files = sum(len(paths) - 1 for paths in self.last_groups.values())
        confirm = QMessageBox.question(
            self, "Confirm Quarantine",
            f"This will move {total_files} duplicate file(s) to the quarantine folder.\n"
            "They will not be permanently deleted and can be undone from the Activity Log.\n\n"
            "Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        run_id, count = quarantine_duplicates(self.last_groups)
        self.status_callback(f"Quarantined {count} duplicate file(s). (Run ID: {run_id})")
        self.last_groups = {}
        self.list_widget.clear()
        self.refresh_quarantine_status()


# --------------------------------------------------------- Activity Log Tab

class ActivityLogTab(QWidget):
    def __init__(self, status_callback):
        super().__init__()
        self.status_callback = status_callback
        layout = QVBoxLayout()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Action", "Source", "Destination", "Timestamp"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        undo_last_btn = QPushButton("Undo Last Action")
        undo_last_btn.clicked.connect(self.undo_last)
        undo_selected_btn = QPushButton("Undo Selected Action")
        undo_selected_btn.clicked.connect(self.undo_selected)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(undo_last_btn)
        btn_row.addWidget(undo_selected_btn)
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.refresh()

    def refresh(self):
        history = get_action_history(limit=100)
        self.table.setRowCount(len(history))
        for row, entry in enumerate(history):
            self.table.setItem(row, 0, QTableWidgetItem(str(entry["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(entry["action"]))
            self.table.setItem(row, 2, QTableWidgetItem(entry["source_path"] or ""))
            self.table.setItem(row, 3, QTableWidgetItem(entry["dest_path"] or ""))
            self.table.setItem(row, 4, QTableWidgetItem(entry["timestamp"]))

    def undo_last(self):
        success, msg = undo_last_action()
        self.status_callback(msg)
        self.refresh()

    def undo_selected(self):
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.information(self, "No selection", "Select an action first.")
            return
        row = selected[0].row()
        action_id = int(self.table.item(row, 0).text())
        success, msg = undo_action_by_id(action_id)
        self.status_callback(msg)
        self.refresh()


# -------------------------------------------------------------- Backup Tab

class BackupTab(QWidget):
    def __init__(self, status_callback):
        super().__init__()
        self.status_callback = status_callback
        layout = QVBoxLayout()

        form_box = QGroupBox("New Backup Job")
        form = QFormLayout()
        self.source_picker = FolderPicker("Folder to back up")
        self.dest_picker = FolderPicker("Where to store the backup zip")
        self.schedule_input = QSpinBox()
        self.schedule_input.setRange(0, 100000)
        self.schedule_input.setSuffix(" minutes (0 = manual only)")

        form.addRow("Source folder:", self.source_picker)
        form.addRow("Backup destination:", self.dest_picker)
        form.addRow("Auto-run every:", self.schedule_input)

        save_btn = QPushButton("Save Backup Job")
        save_btn.clicked.connect(self.save_job)
        form.addRow("", save_btn)
        form_box.setLayout(form)
        layout.addWidget(form_box)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Source", "Destination", "Last Run"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("Run Selected Now")
        run_btn.clicked.connect(self.run_selected)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.refresh()

    def save_job(self):
        source = self.source_picker.text()
        dest = self.dest_picker.text()
        if not source or not dest:
            QMessageBox.warning(self, "Missing info", "Both source and destination folders are required.")
            return
        if not os.path.isdir(source):
            QMessageBox.warning(self, "Invalid folder", f"Source folder does not exist:\n{source}")
            return

        is_valid, error_msg = validate_source_dest(source, dest)
        if not is_valid:
            QMessageBox.warning(self, "Unsafe folder choice", error_msg)
            return

        save_backup_job(source, dest, self.schedule_input.value())
        self.status_callback("Backup job saved.")
        self.refresh()

    def refresh(self):
        jobs = get_all_backup_jobs()
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self.table.setItem(row, 0, QTableWidgetItem(str(job["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(job["source_folder"]))
            self.table.setItem(row, 2, QTableWidgetItem(job["destination_folder"]))
            self.table.setItem(row, 3, QTableWidgetItem(job["last_run"] or "Never"))

    def _selected_job_id(self):
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        return int(self.table.item(row, 0).text())

    def run_selected(self):
        job_id = self._selected_job_id()
        if job_id is None:
            QMessageBox.information(self, "No selection", "Select a backup job first.")
            return
        archive_path, errors = run_backup_job(job_id)
        if errors and not archive_path:
            QMessageBox.critical(self, "Backup failed", "\n".join(errors))
            self.status_callback("Backup failed.")
        elif errors:
            QMessageBox.warning(self, "Backup completed with issues",
                                 f"Backup created, but {len(errors)} file(s) were skipped:\n\n" + "\n".join(errors[:5]))
            self.status_callback(f"Backup created with {len(errors)} skipped file(s): {archive_path}")
        else:
            self.status_callback(f"Backup created: {archive_path}")
        self.refresh()

    def delete_selected(self):
        job_id = self._selected_job_id()
        if job_id is None:
            QMessageBox.information(self, "No selection", "Select a backup job first.")
            return
        delete_backup_job(job_id)
        self.status_callback("Backup job deleted.")
        self.refresh()


# ------------------------------------------------------- Auto Organize Tab

class AutoOrganizeTab(QWidget):
    """
    Organizes files automatically into a Type -> Year -> Month -> Week -> Day
    folder hierarchy (e.g. Images/2026/July/Week 2/Day 12/).
    Supports one-time "Organize Now" and continuous background monitoring.
    """

    def __init__(self, status_callback):
        super().__init__()
        self.status_callback = status_callback
        self.monitor = None
        layout = QVBoxLayout()

        form_box = QGroupBox("Auto Organize Settings")
        form = QFormLayout()

        self.source_picker = FolderPicker("Folder to watch (e.g. Downloads)")
        self.root_picker = FolderPicker("Root folder for organized files")
        self.use_creation_date = QCheckBox("Use file creation date instead of modified date")

        form.addRow("Source folder:", self.source_picker)
        form.addRow("Organized root folder:", self.root_picker)
        form.addRow("", self.use_creation_date)

        organize_now_btn = QPushButton("Organize Now (one-time)")
        organize_now_btn.clicked.connect(self.organize_now)
        form.addRow("", organize_now_btn)

        form_box.setLayout(form)
        layout.addWidget(form_box)

        monitor_box = QGroupBox("Continuous Monitoring")
        monitor_layout = QVBoxLayout()
        monitor_layout.addWidget(QLabel(
            "When started, this checks the source folder every few seconds\n"
            "and automatically organizes any new file that appears in it."
        ))
        self.monitor_toggle_btn = QPushButton("Start Monitoring")
        self.monitor_toggle_btn.clicked.connect(self.toggle_monitor)
        self.monitor_status_label = QLabel("Monitoring: STOPPED")
        monitor_layout.addWidget(self.monitor_toggle_btn)
        monitor_layout.addWidget(self.monitor_status_label)
        monitor_box.setLayout(monitor_layout)
        layout.addWidget(monitor_box)

        categories = ", ".join(list(CATEGORY_MAP.keys()) + [DEFAULT_CATEGORY])
        info_label = QLabel(f"Categories used: {categories}")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #555555; padding-top: 8px;")
        layout.addWidget(info_label)

        layout.addStretch()
        self.setLayout(layout)

    def organize_now(self):
        source = self.source_picker.text()
        root = self.root_picker.text()
        if not source or not root:
            QMessageBox.warning(self, "Missing info", "Both source and root folders are required.")
            return
        if not os.path.isdir(source):
            QMessageBox.warning(self, "Invalid folder", f"Source folder does not exist:\n{source}")
            return

        try:
            run_id, moved, skipped = organize_folder(
                source, root, use_creation_date=self.use_creation_date.isChecked()
            )
        except ValueError as e:
            QMessageBox.warning(self, "Blocked", str(e))
            return

        self.status_callback(f"Organized {len(moved)} file(s), skipped {skipped}. (Run ID: {run_id})")

    def toggle_monitor(self):
        if self.monitor and self.monitor.is_running():
            self.monitor.stop()
            self.monitor_status_label.setText("Monitoring: STOPPED")
            self.monitor_toggle_btn.setText("Start Monitoring")
            self.status_callback("Auto-organize monitoring stopped.")
            return

        source = self.source_picker.text()
        root = self.root_picker.text()
        if not source or not root:
            QMessageBox.warning(self, "Missing info", "Both source and root folders are required.")
            return
        if not os.path.isdir(source):
            QMessageBox.warning(self, "Invalid folder", f"Source folder does not exist:\n{source}")
            return

        self.monitor = FolderMonitor(
            source, root, use_creation_date=self.use_creation_date.isChecked(),
            on_event=self.status_callback,
        )
        self.monitor.start()
        self.monitor_status_label.setText("Monitoring: RUNNING")
        self.monitor_toggle_btn.setText("Stop Monitoring")
        self.status_callback("Auto-organize monitoring started.")

    def stop_monitor_if_running(self):
        if self.monitor and self.monitor.is_running():
            self.monitor.stop()


# ----------------------------------------------------------- Dashboard Tab

class DashboardTab(QWidget):
    def __init__(self, scheduler, status_callback):
        super().__init__()
        self.scheduler = scheduler
        self.status_callback = status_callback
        layout = QVBoxLayout()

        self.rules_label = QLabel()
        self.actions_label = QLabel()
        self.backups_label = QLabel()
        self.scheduler_label = QLabel()

        for lbl in (self.rules_label, self.actions_label, self.backups_label, self.scheduler_label):
            lbl.setStyleSheet("font-size: 14px; padding: 4px;")
            layout.addWidget(lbl)

        self.toggle_btn = QPushButton("Start Scheduler")
        self.toggle_btn.clicked.connect(self.toggle_scheduler)
        layout.addWidget(self.toggle_btn)

        layout.addWidget(QLabel(
            "\nThe scheduler runs in the background and checks every 30 seconds\n"
            "for rules or backup jobs that are due, based on the schedule you set."
        ))

        layout.addStretch()
        self.setLayout(layout)
        self.refresh()

    def toggle_scheduler(self):
        if self.scheduler.is_running():
            self.scheduler.stop()
            self.status_callback("Scheduler stopped.")
        else:
            self.scheduler.start()
            self.status_callback("Scheduler started.")
        self.refresh()

    def refresh(self):
        rules = get_all_rules()
        actions = get_action_history(limit=100000)
        jobs = get_all_backup_jobs()

        self.rules_label.setText(f"Active rules: {len(rules)}")
        self.actions_label.setText(f"Actions logged: {len(actions)}")
        self.backups_label.setText(f"Backup jobs configured: {len(jobs)}")

        running = self.scheduler.is_running()
        self.scheduler_label.setText(f"Scheduler status: {'RUNNING' if running else 'STOPPED'}")
        self.toggle_btn.setText("Stop Scheduler" if running else "Start Scheduler")


# --------------------------------------------------------------- Main Window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart File Organizer & Automation Suite")
        self.resize(900, 650)

        init_db()
        self.scheduler = Scheduler(on_event=self.show_status)

        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("padding: 6px; color: #2F5496; font-weight: bold;")

        self.tabs = QTabWidget()
        self.rules_tab = RulesTab(self.show_status)
        self.duplicates_tab = DuplicatesTab(self.show_status)
        self.auto_organize_tab = AutoOrganizeTab(self.show_status)
        self.activity_tab = ActivityLogTab(self.show_status)
        self.backup_tab = BackupTab(self.show_status)
        self.dashboard_tab = DashboardTab(self.scheduler, self.show_status)

        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.rules_tab, "Rules")
        self.tabs.addTab(self.duplicates_tab, "Duplicates")
        self.tabs.addTab(self.auto_organize_tab, "Auto Organize")
        self.tabs.addTab(self.activity_tab, "Activity Log")
        self.tabs.addTab(self.backup_tab, "Backup")

        # refresh other tabs whenever the user switches into them
        self.tabs.currentChanged.connect(self.on_tab_changed)

        container = QWidget()
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        main_layout.addWidget(self.status_label)
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # periodic UI refresh (e.g. dashboard counts) every 5 seconds
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.dashboard_tab.refresh)
        self.refresh_timer.start(5000)

    def on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if hasattr(widget, "refresh"):
            widget.refresh()

    def show_status(self, message):
        self.status_label.setText(message)

    def closeEvent(self, event):
        self.scheduler.stop()
        self.auto_organize_tab.stop_monitor_if_running()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
