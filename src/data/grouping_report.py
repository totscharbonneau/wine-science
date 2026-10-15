"""Grouping report: lets a wine grouping be checked by eye.

Called by `group_wines` on every run. Writes `wine_groups_<method>_report.md` next to the
mapping, from the temp table `grouped` (sku, group_key, attached, kept_together, ambiguous)
and the `wines` table of the same connection.
"""

import itertools
import re
import unicodedata
from pathlib import Path

import duckdb

TOP_N = 20  # rows in each "largest" / "mixed" list
SAMPLE_SIZE = 25  # groups in the hand-review sample
DIVERGENCE_THRESHOLD = 0.2  # sibling descriptions sharing less than this are flagged
MAX_COMPARED = 30  # SKUs per group whose descriptions are compared pairwise


def _words(text: str) -> set[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return set(re.findall(r"[a-z]{3,}", text))


def _similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def _divergent_groups(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int, float, str, str]]:
    """Groups whose least similar pair of SKU descriptions falls under the threshold.

    Returns (group_key, n_skus, similarity, sku_a, sku_b), least similar first.
    """
    rows = con.execute(
        "SELECT group_key, sku, description FROM members"
        " WHERE group_key IN (SELECT group_key FROM members WHERE description IS NOT NULL"
        "                     GROUP BY group_key HAVING count(*) > 1)"
        " AND description IS NOT NULL ORDER BY group_key, sku"
    ).fetchall()
    out = []
    for key, grp in itertools.groupby(rows, key=lambda r: r[0]):
        words = [(sku, _words(desc)) for _, sku, desc in grp]
        n = len(words)
        worst = min(
            ((_similarity(a, b), sa, sb) for (sa, a), (sb, b) in itertools.combinations(words[:MAX_COMPARED], 2)),
            default=None,
        )
        if worst and worst[0] < DIVERGENCE_THRESHOLD:
            out.append((key, n, worst[0], worst[1], worst[2]))
    return sorted(out, key=lambda r: (r[2], r[0]))


def _cell(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[tuple]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return lines + [""]


def write_report(
    con: duckdb.DuckDBPyConnection, method: str, out_dir: Path, seed: int = 0
) -> Path:
    """Write the report for `method` and return its path. `seed` fixes the review sample."""
    from src.data.group_wines import GRAPE_LEAD, METHODS, norm

    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE members AS
        SELECT g.group_key, g.sku, g.attached, g.ambiguous, w.name, w.description, w.volume_ml,
            nullif({norm('w.region')}, '') AS region, {GRAPE_LEAD} AS grape
        FROM grouped g JOIN wines w USING (sku)"""
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE sizes AS"
        " SELECT group_key, count(*) AS n FROM members GROUP BY group_key"
    )
    n_skus, n_groups = con.execute("SELECT sum(n), count(*) FROM sizes").fetchone()

    md = [
        f"# Grouping report: `{method}`",
        "",
        METHODS[method],
        "",
        f"{n_skus:,} SKUs in {n_groups:,} groups.",
        "",
        "## Group size distribution",
        "",
    ]
    md += _table(
        ["SKUs in group", "groups"],
        con.execute(
            "SELECT CASE WHEN n >= 10 THEN '10+' ELSE n::VARCHAR END AS size, count(*)"
            " FROM sizes GROUP BY ALL ORDER BY min(n)"
        ).fetchall(),
    )

    md += [f"## Largest groups (top {TOP_N})", ""]
    md += _table(
        ["group_key", "SKUs"],
        con.execute(f"SELECT group_key, n FROM sizes ORDER BY n DESC, group_key LIMIT {TOP_N}").fetchall(),
    )

    mixes = {
        "grapes": ("grape", "lead grape"),
        "regions": ("region", "region"),
        "volumes": ("volume_ml", "volume_ml"),
    }
    for title, (col, label) in mixes.items():
        note = " Expected: bottle sizes never split a group." if title == "volumes" else ""
        total = con.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM members GROUP BY group_key"
            f" HAVING count(DISTINCT {col}) > 1)"
        ).fetchone()[0]
        md += [f"## Groups mixing {title}", "", f"{total:,} groups; the {TOP_N} largest.{note}", ""]
        md += _table(
            ["group_key", "SKUs", f"distinct {label}s"],
            con.execute(
                f"SELECT group_key, count(*), string_agg(DISTINCT {col}::VARCHAR, '; ' ORDER BY {col}::VARCHAR)"
                f" FROM members GROUP BY group_key HAVING count(DISTINCT {col}) > 1"
                f" ORDER BY count(*) DESC, group_key LIMIT {TOP_N}"
            ).fetchall(),
        )

    divergent = _divergent_groups(con)
    md += [
        "## Groups with divergent descriptions",
        "",
        f"{len(divergent):,} groups where two SKUs' descriptions share fewer than "
        f"{DIVERGENCE_THRESHOLD:.0%} of their words (Jaccard on words of 3+ letters). "
        "This is evidence the key does not use. Least similar first; the first "
        f"{TOP_N} are shown.",
        "",
    ]
    md += _table(
        ["group_key", "SKUs", "similarity", "SKU pair"],
        [(k, n, f"{s:.2f}", f"{a} / {b}") for k, n, s, a, b in divergent[:TOP_N]],
    )

    if method == "npcg":
        for title, flag, blurb in [
            ("Attached no-grape SKUs", "attached", "joined the one grape their siblings agree on"),
            ("Ambiguous no-grape SKUs", "ambiguous", "left in a sub-group of their own because siblings disagree"),
        ]:
            rows = con.execute(
                f"SELECT sku, name, group_key FROM members WHERE {flag} ORDER BY group_key, sku"
            ).fetchall()
            md += [f"## {title}", "", f"{len(rows):,} SKUs {blurb}.", ""]
            md += _table(["sku", "name", "group_key"], rows)

    sample = con.execute(
        f"""SELECT group_key FROM sizes WHERE n > 1
        ORDER BY md5(group_key || '{int(seed)}') LIMIT {SAMPLE_SIZE}"""
    ).fetchall()
    md += [
        "## Hand-review sample",
        "",
        f"{len(sample)} random groups of 2+ SKUs (seed {int(seed)}; the same seed and data give the "
        "same sample). Check that every SKU in a group is the same wine.",
        "",
    ]
    for (key,) in sample:
        md += [f"### `{key}`", ""]
        md += _table(
            ["sku", "name", "volume_ml", "region", "lead grape", "description"],
            [
                (*r[:5], (r[5] or "")[:120])
                for r in con.execute(
                    "SELECT sku, name, volume_ml, region, grape, description FROM members"
                    " WHERE group_key = ? ORDER BY sku",
                    [key],
                ).fetchall()
            ],
        )

    out = out_dir / f"wine_groups_{method}_report.md"
    out.write_text("\n".join(md))
    return out
