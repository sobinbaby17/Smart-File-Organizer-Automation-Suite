"""
backend/database.py

Central place for the SQLite connection and table creation.
Every other backend module imports get_connection() from here so
everyone reads/writes the same database file.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "organizer.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            action TEXT,
            source_path TEXT,
            dest_path TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            source_folder TEXT,
            dest_folder TEXT,
            extension TEXT,
            older_than_days INTEGER DEFAULT 0,
            schedule_minutes INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            last_run TEXT
        );

        CREATE TABLE IF NOT EXISTS backup_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_folder TEXT,
            destination_folder TEXT,
            schedule_minutes INTEGER DEFAULT 0,
            last_run TEXT
        );
    """)
    conn.commit()

    # Safe migration: add 'keyword' column if it doesn't already exist
    # (needed for databases created before this feature was added).
    try:
        conn.execute("ALTER TABLE rules ADD COLUMN keyword TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # column already exists

    conn.close()
