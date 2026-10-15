"""Group SKUs into wine groups (the same wine across vintages and bottle sizes).

    uv run python -m src.data.group_wines --method npc

Reads  data/processed/winescience.duckdb   (read-only)
Writes data/processed/wine_groups_<method>.parquet
"""

import argparse
from pathlib import Path

import duckdb

from src import DATA_DIR

DB = DATA_DIR / "processed" / "winescience.duckdb"
OUT_DIR = DATA_DIR / "processed"

# Registry of grouping methods: name -> what the method means.
METHODS = {
    "npc": "normalized name + producer + color. Bottle volume and descriptions are never in the key.",
}


def norm(col: str) -> str:
    """Normalize a column for use in a key: strip accents, lowercase, collapse whitespace.

    NULL becomes '' so a missing value is a stable part of the key.
    """
    return f"trim(regexp_replace(lower(strip_accents(coalesce({col}, ''))), '\\s+', ' ', 'g'))"


KEY_SQL = {
    "npc": f"{norm('name')} || '|' || {norm('producer')} || '|' || {norm('color')}",
}


def group_wines(db: Path = DB, out_dir: Path = OUT_DIR, method: str = "npc") -> Path:
    """Write the SKU -> wine group mapping for `method` and return its path."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; known: {', '.join(METHODS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"wine_groups_{method}.parquet"
    con = duckdb.connect(str(db), read_only=True)
    try:
        con.execute(
            f"""
            COPY (
                SELECT sku, left(md5(group_key), 16) AS group_id, group_key
                FROM (SELECT sku, {KEY_SQL[method]} AS group_key FROM wines)
                ORDER BY sku
            ) TO '{out}' (FORMAT parquet)
            """
        )
        n_skus, n_groups = con.execute(
            f"SELECT count(*), count(DISTINCT group_id) FROM '{out}'"
        ).fetchone()
    finally:
        con.close()
    print(f"{method}: {n_skus:,} SKUs in {n_groups:,} groups -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--method", choices=sorted(METHODS), default="npc")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    group_wines(args.db, args.out_dir, args.method)
