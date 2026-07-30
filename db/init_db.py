"""Create the event store and seed the competitor table from config/competitors.yaml.

Usage: python -m db.init_db [--reset]
"""
import argparse
import sqlite3
from pathlib import Path

from config import competitors_as_json_row, db_path, get_competitors

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(path=None):
    conn = sqlite3.connect(path or db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())


def seed_competitors(conn):
    for competitor in get_competitors():
        row = competitors_as_json_row(competitor)
        conn.execute(
            """
            INSERT INTO competitor (id, name, tier, ownership, tickers, pillars, cadence, filings_path, notes)
            VALUES (:id, :name, :tier, :ownership, :tickers, :pillars, :cadence, :filings_path, :notes)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, tier=excluded.tier, ownership=excluded.ownership,
              tickers=excluded.tickers, pillars=excluded.pillars, cadence=excluded.cadence,
              filings_path=excluded.filings_path, notes=excluded.notes,
              updated_at=datetime('now')
            """,
            row,
        )
    conn.commit()


def init_db(path=None, reset=False):
    resolved = Path(path or db_path())
    if reset and resolved.exists():
        resolved.unlink()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(resolved)
    try:
        create_schema(conn)
        seed_competitors(conn)
    finally:
        conn.close()
    return resolved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete existing db file first")
    args = parser.parse_args()
    resolved_path = init_db(reset=args.reset)
    print(f"Initialized event store at {resolved_path}")
