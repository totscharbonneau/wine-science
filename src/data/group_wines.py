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
    "npcg": "npc + normalized primary grape. A SKU without a grape joins its siblings' grape when they agree on exactly one.",
}


def norm(col: str) -> str:
    """Normalize a column for use in a key: strip accents, lowercase, collapse whitespace.

    NULL becomes '' so a missing value is a stable part of the key.
    """
    return f"trim(regexp_replace(lower(strip_accents(coalesce({col}, ''))), '\\s+', ' ', 'g'))"


NPC_KEY = f"{norm('name')} || '|' || {norm('producer')} || '|' || {norm('color')}"

# Spelling variants of one grape, after norm() and hyphens -> spaces.
GRAPE_ALIASES = {
    "cabernet": "cabernet sauvignon",
    "shiraz": "syrah",
    "sangiovese grosso": "sangiovese",
    "tinto fino": "tempranillo",
    "maccabeu": "macabeo",
}

# Placeholder values that are not a grape; treated as missing.
JUNK_GRAPES = ("autre (s) cepage (s)",)


# Normalized primary grape, NULL when absent (hyphens count as spaces).
GRAPE_NORMALIZED = "nullif(" + norm("replace(grape_primary, '-', ' ')") + ", '')"


def _grape_alias(col: str) -> str:
    """SQL expression mapping spelling variants in `col` to one canonical grape."""
    junk = ", ".join(f"'{j}'" for j in JUNK_GRAPES)
    whens = " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in GRAPE_ALIASES.items())
    return f"CASE WHEN {col} IN ({junk}) THEN NULL ELSE CASE {col} {whens} ELSE {col} END END"


# Per-method SQL producing (sku, group_key, attached, kept_together, ambiguous). The last three
# describe NULL-grape SKUs only: `attached` joined the one grape their siblings (same npc key)
# agree on, `kept_together` have no grape-bearing sibling, `ambiguous` have siblings that
# disagree and so sit in a sub-group of their own.
SELECT_SQL = {
    "npc": f"""
        SELECT sku, {NPC_KEY} AS group_key,
            false AS attached, false AS kept_together, false AS ambiguous
        FROM wines
    """,
    "npcg": f"""
        WITH normalized AS (
            SELECT sku, {NPC_KEY} AS npc_key, {GRAPE_NORMALIZED} AS normalized_grape FROM wines
        ), base AS (
            SELECT sku, npc_key, {_grape_alias('normalized_grape')} AS grape FROM normalized
        ), sib AS (
            SELECT *,
                count(DISTINCT grape) OVER (PARTITION BY npc_key) AS n_grapes,
                min(grape) OVER (PARTITION BY npc_key) AS only_grape
            FROM base
        )
        SELECT sku,
            npc_key || '|' || CASE
                WHEN grape IS NOT NULL THEN grape
                WHEN n_grapes = 1 THEN only_grape
                ELSE '' END AS group_key,
            grape IS NULL AND n_grapes = 1 AS attached,
            grape IS NULL AND n_grapes = 0 AS kept_together,
            grape IS NULL AND n_grapes > 1 AS ambiguous
        FROM sib
    """,
}


def group_wines(db: Path = DB, out_dir: Path = OUT_DIR, method: str = "npc") -> Path:
    """Write the SKU -> wine group mapping for `method` and return its path."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; known: {', '.join(METHODS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"wine_groups_{method}.parquet"
    con = duckdb.connect(str(db), read_only=True)
    try:
        # Temp tables live in memory, so this works on a read-only connection.
        con.execute(f"CREATE TEMP TABLE grouped AS {SELECT_SQL[method]}")
        con.execute(
            f"""
            COPY (
                SELECT sku, left(md5(group_key), 16) AS group_id, group_key
                FROM grouped
                ORDER BY sku
            ) TO '{out}' (FORMAT parquet)
            """
        )
        n_skus, n_groups, n_attached, n_together, n_ambiguous = con.execute(
            "SELECT count(*), count(DISTINCT group_key), count(*) FILTER (WHERE attached),"
            " count(*) FILTER (WHERE kept_together), count(*) FILTER (WHERE ambiguous)"
            " FROM grouped"
        ).fetchone()
    finally:
        con.close()
    msg = f"{method}: {n_skus:,} SKUs in {n_groups:,} groups -> {out}"
    if n_attached or n_together or n_ambiguous:
        msg += (
            f" (no-grape SKUs: {n_attached:,} attached to siblings, "
            f"{n_together:,} kept together, {n_ambiguous:,} ambiguous)"
        )
    print(msg)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--method", choices=sorted(METHODS), default="npc")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    group_wines(args.db, args.out_dir, args.method)
