"""Load the simulation into SQL for the dashboard's Ask chat: Tiger Data if DATABASE_URL is set, else data/simulation.db.

    uv run --env-file .env --extra tiger scripts/load_sql.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from backend import simdb  # noqa: E402

if __name__ == "__main__":
    for table, n in simdb.build().items():
        print(f"  {table:16s} {n:>9,}")
