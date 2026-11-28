"""Relational integrity-checking baseline. SQLite JSON input preserves nested record fields."""
import json
import sqlite3
from pathlib import Path

SQL = Path(__file__).with_name("decision.sql").read_text(encoding="utf-8")


def decide(archive, incoming):
    # Canonical JSON makes differently ordered fields comparable and captures the full record,
    # including supporting sources and evidence basis. SQL implements all decision logic.
    bound = {k: json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
             for k, v in {"db": archive, "req": incoming}.items()}
    con = sqlite3.connect(":memory:")
    try:
        return con.execute(SQL, bound).fetchone()[0]
    finally:
        con.close()
