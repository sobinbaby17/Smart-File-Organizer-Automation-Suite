# Smart File Organizer & Automation Suite

MCA Mini Project — a desktop application that automatically organizes files
by rule, detects and safely removes duplicates, performs scheduled backups,
and lets you undo any action it takes.

## Project Structure

```
final_project/
├── main.py                     Entry point -- run this to launch the app
├── requirements.txt
├── backend/
│   ├── database.py              Shared SQLite connection + schema
│   ├── safety.py                Protected-path checks, safe-to-touch file checks
│   ├── rule_engine.py           Scan folders, apply/save/run move rules
│   ├── duplicate_finder.py      Hash-based duplicate detection
│   ├── auto_organizer.py        Type + date (Year/Month/Week/Day) auto-organization
│   ├── folder_monitor.py        Polling-based continuous folder monitoring
│   ├── undo_manager.py          Quarantine + undo (single action / full run)
│   ├── backup_manager.py        Zip-based folder backup
│   └── scheduler.py             Background thread that runs due rules/backups
└── gui/
    └── main_window.py           PyQt6 GUI (Dashboard, Rules, Duplicates,
                                   Auto Organize, Activity Log, Backup tabs)
```

## Setup

1. Make sure Python 3.10+ is installed:
   ```bash
   python3 --version
   ```

2. Install the one dependency (PyQt6):
   ```bash
   pip install -r requirements.txt --break-system-packages
   ```
   (On some systems you can drop `--break-system-packages`, or use a virtual
   environment: `python3 -m venv venv && source venv/bin/activate` first.)

3. Run the app:
   ```bash
   python3 main.py
   ```

## How to Use

- **Rules tab**: create a rule (e.g. move all `.pdf` files from Downloads to
  Documents), optionally set it to auto-run on a schedule, then Save.
  Use "Run Selected Now" to test it immediately.
- **Duplicates tab**: pick a folder, click "Scan for Duplicates" to see a
  report, then "Quarantine Duplicates" to safely move extras into a hidden
  `.quarantine` folder (nothing is permanently deleted).
- **Auto Organize tab**: pick a source folder and a root destination folder.
  "Organize Now" sorts every file in the source folder into
  `<root>/<Category>/<Year>/<Month>/Week N/Day N/`, based on file type and
  date (e.g. a `.jpg` modified on 12 July 2026 goes to
  `Images/2026/July/Week 2/Day 12/`). "Start Monitoring" keeps checking the
  source folder every few seconds and auto-organizes any new file that
  appears, without you doing anything further.
- **Activity Log tab**: see every action the app has taken. Select any row
  and click "Undo Selected Action", or just "Undo Last Action" for the most
  recent one.
- **Backup tab**: configure a folder to be zipped and backed up, on demand
  or on a schedule.
- **Dashboard tab**: summary counts, and a Start/Stop button for the
  background scheduler (checks every 30 seconds for anything due to run).

## Real-World Safety Features

These were added after testing the app against messy real folders (broken
symlinks, locked files, accidental dangerous folder selection):

- **Protected folder blocking** -- you cannot set your home directory, `/`,
  `/etc`, `C:\Windows`, or similar system folders as a rule/backup source.
  Prevents catastrophic accidental mass-moves.
- **Source/destination validation** -- a rule cannot have the same folder as
  both source and destination, and the destination cannot be a parent of the
  source (which would create an infinite loop).
- **In-progress file protection** -- any file modified in the last 10 seconds
  is skipped by rules, duplicate scans, and backups. This avoids grabbing a
  file that a browser or another app is still writing to.
- **Hidden files and symlinks are skipped** -- prevents crashes from broken
  shortcuts (a common issue in Ubuntu's Downloads folder) and avoids moving
  OS/config files by accident.
- **Per-file error resilience** -- if one file is locked, permission-denied,
  or disappears mid-operation, that single file is skipped and reported;
  the rest of the rule run or backup still completes instead of failing
  entirely.
- **Backups are built file-by-file** (not with a single archive call), so a
  single broken file cannot corrupt the entire zip -- this directly fixes an
  earlier real bug where a broken symlink in Downloads produced an
  unopenable backup archive.
- **Quarantine cleanup** -- duplicate files sent to quarantine no longer
  accumulate forever. The Duplicates tab shows how much is currently
  quarantined and lets you permanently empty it (with a confirmation dialog,
  since this step cannot be undone).
- **Confirmation dialogs** before quarantining duplicates and before
  permanently emptying quarantine -- both irreversible-ish actions now
  require explicit confirmation.

## Known Limitations (Honest, for your report)

- The scheduler only runs while the app is open (see "Future Enhancements"
  in the Need of the Project document for the OS-level service alternative).
- Backups are full snapshots, not incremental, and old backups are not
  automatically cleaned up.
- Rule matching supports one extension + one optional keyword per rule --
  not full wildcard/regex patterns yet.

## Design Notes (for your report / viva)

- **Layered architecture**: `backend/` contains all business logic and has
  no dependency on PyQt6 -- it can be tested and reused independently of the
  GUI. `gui/` only handles presentation and calls into `backend/`.
- **Undo as a first-class feature**: every file-moving action (rule moves,
  duplicate quarantines) is logged with enough information to be reversed.
  Deletions are never permanent -- duplicates go to `.quarantine` instead of
  being removed outright.
- **No external scheduling library**: the scheduler is a simple background
  `threading.Thread` loop, avoiding an extra dependency (APScheduler) while
  still demonstrating real scheduling/automation concepts.
- **Auto Organize reuses the same undo system**: files moved by the
  Type/Year/Month/Week/Day organizer are logged into the same `actions`
  table as rule moves, so undo works on them automatically with no
  separate undo logic required.
- **Continuous monitoring uses polling, not OS file-system events**: real
  instant detection would use the external `watchdog` library; polling
  every few seconds avoids that dependency at the cost of a short delay --
  noted as a future enhancement (real-time monitoring via `watchdog`).
- **Single shared database** (`organizer.db`, created automatically on first
  run) ties rules, backups, and the activity log together.

## Testing Notes

All backend modules (`rule_engine`, `duplicate_finder`, `undo_manager`,
`backup_manager`, `scheduler`) were tested independently of the GUI, since
they have no PyQt6 dependency -- you can `import` and call their functions
directly from a Python shell to verify behavior without launching the app.
