"""Tests for src.data.group_wines, run against a tiny hand-made cleaned `wines` table."""

import duckdb
import pytest

from src.data.group_wines import METHODS, group_wines

# sku, name, producer, color, volume_ml, description
WINES = [
    # vintages of one wine, plus a magnum
    ("1", "Château Test", "Domaine X", "Rouge", 750, "2018"),
    ("2", "Château Test", "Domaine X", "Rouge", 750, "2019"),
    ("3", "Château Test", "Domaine X", "Rouge", 1500, "magnum"),
    # case, whitespace and accent differences
    ("4", "  CHATEAU   test ", "domaine x", "Rouge", 750, None),
    # same name and producer, other color
    ("5", "Château Test", "Domaine X", "Blanc", 750, None),
    # singleton
    ("6", "Lonely Wine", "Solo", "Rosé", 750, None),
    # different producer, same name
    ("7", "Château Test", "Domaine Y", "Rouge", 750, None),
    # missing producer is a valid, stable key part
    ("8", "No Producer", None, "Blanc", 750, None),
    ("9", "No Producer", None, "Blanc", 750, None),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "clean.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE wines (sku VARCHAR, name VARCHAR, producer VARCHAR, color VARCHAR,"
        " volume_ml INTEGER, description VARCHAR)"
    )
    con.executemany("INSERT INTO wines VALUES (?,?,?,?,?,?)", WINES)
    con.close()
    return path


def mapping(db, out_dir, method="npc"):
    out = group_wines(db, out_dir, method)
    rows = duckdb.sql(f"SELECT sku, group_id, group_key FROM '{out}'").fetchall()
    return {sku: (gid, key) for sku, gid, key in rows}, out


def test_every_sku_appears_exactly_once(db, tmp_path):
    m, out = mapping(db, tmp_path / "out")
    assert out.name == "wine_groups_npc.parquet"
    skus = [r[0] for r in duckdb.sql(f"SELECT sku FROM '{out}'").fetchall()]
    assert sorted(skus) == sorted(w[0] for w in WINES)
    assert all(gid and key for gid, key in m.values())


def test_vintages_and_magnum_share_a_group(db, tmp_path):
    m, _ = mapping(db, tmp_path / "out")
    assert m["1"][0] == m["2"][0] == m["3"][0]


def test_different_color_is_separate(db, tmp_path):
    m, _ = mapping(db, tmp_path / "out")
    assert m["1"][0] != m["5"][0]


def test_case_whitespace_accents_do_not_split(db, tmp_path):
    m, _ = mapping(db, tmp_path / "out")
    assert m["4"][0] == m["1"][0]


def test_different_producer_is_separate(db, tmp_path):
    m, _ = mapping(db, tmp_path / "out")
    assert m["7"][0] != m["1"][0]


def test_singleton_and_null_producer_get_groups(db, tmp_path):
    m, _ = mapping(db, tmp_path / "out")
    assert m["6"][0] not in {m[s][0] for s in "12345789"}
    assert m["8"][0] == m["9"][0]


def test_readable_key_is_normalized(db, tmp_path):
    m, _ = mapping(db, tmp_path / "out")
    assert m["4"][1] == "chateau test|domaine x|rouge"


def test_ids_identical_across_runs(db, tmp_path):
    a, _ = mapping(db, tmp_path / "run1")
    b, _ = mapping(db, tmp_path / "run2")
    assert a == b


def test_database_is_not_modified(db, tmp_path):
    before = db.read_bytes()
    mapping(db, tmp_path / "out")
    assert db.read_bytes() == before


def test_stored_columns_untouched(db, tmp_path):
    mapping(db, tmp_path / "out")
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT name FROM wines WHERE sku = '4'").fetchone()[0] == "  CHATEAU   test "


def test_registry_describes_npc():
    assert "npc" in METHODS
    assert METHODS["npc"]


# sku, name, producer, color, grape_primary
GRAPE_WINES = [
    # two grapes under one name/producer/color -> separate groups; variants of one grape merge
    ("g1", "Cuvee", "Dom A", "Rouge", "Merlot"),
    ("g2", "Cuvee", "Dom A", "Rouge", "Merlot"),
    ("g3", "Cuvee", "Dom A", "Rouge", "Syrah"),
    ("g4", "Cuvee", "Dom A", "Rouge", "Cabernet"),
    ("g5", "Cuvee", "Dom A", "Rouge", "Cabernet-sauvignon"),
    ("g6", "Cuvee", "Dom A", "Rouge", " CABERNET  Sauvignon "),
    # NULL grape with exactly one grape among siblings -> attaches
    ("a1", "Attach", "Dom B", "Blanc", "Chardonnay"),
    ("a2", "Attach", "Dom B", "Blanc", None),
    ("a3", "Attach", "Dom B", "Blanc", "chardonnay"),
    # no sibling has a grape -> NULLs stay together
    ("n1", "Nothing", "Dom C", "Rouge", None),
    ("n2", "Nothing", "Dom C", "Rouge", None),
    # siblings disagree -> NULL SKU not attached to either
    ("d1", "Disagree", "Dom D", "Rouge", "Merlot"),
    ("d2", "Disagree", "Dom D", "Rouge", "Syrah"),
    ("d3", "Disagree", "Dom D", "Rouge", None),
    # two NULL SKUs among disagreeing siblings share one sub-group, apart from the grape groups
    ("d4", "Disagree", "Dom D", "Rouge", None),
    # attaching never crosses the base group (other color)
    ("o1", "Attach", "Dom B", "Rouge", "Pinot noir"),
    # more variants of one grape
    ("v1", "Variants", "Dom V", "Rouge", "Syrah"),
    ("v2", "Variants", "Dom V", "Rouge", "Shiraz"),
    ("v3", "Variants", "Dom I", "Rouge", "Sangiovese"),
    ("v4", "Variants", "Dom I", "Rouge", "Sangiovese grosso"),
    ("v5", "Variants", "Dom T", "Rouge", "Tempranillo"),
    ("v6", "Variants", "Dom T", "Rouge", "Tinto fino"),
    ("v7", "Variants", "Dom M", "Blanc", "Macabeo"),
    ("v8", "Variants", "Dom M", "Blanc", "Maccabeu"),
    # junk placeholder is not a grape: it attaches like a NULL
    ("j1", "Junk", "Dom J", "Rouge", "Grenache"),
    ("j2", "Junk", "Dom J", "Rouge", "Autre (s) cépage (s)"),
]

# sku, name, producer, color, grapes. grape_primary is the first grape listed, as in the real data.
BLEND_WINES = [
    # same blend, listed in a different order for a 50/50 tie -> one group
    ("t1", "Tie", "Dom T2", "Rouge", "Merlot 50 %, Syrah 50 %"),
    ("t2", "Tie", "Dom T2", "Rouge", "Syrah 50 %, Merlot 50 %"),
    # the highest percentage leads, wherever it is listed
    ("p1", "Pct", "Dom P", "Rouge", "Syrah 40 %, Merlot 60 %"),
    ("p2", "Pct", "Dom P", "Rouge", "Merlot 55 %, Syrah 45 %"),
    # no percentages: the first grape listed leads; a tie is not needed
    ("f1", "Plain", "Dom F", "Blanc", "Chardonnay"),
    ("f2", "Plain", "Dom F", "Blanc", "Chardonnay 100 %"),
    ("f3", "Plain", "Dom F", "Blanc", "Vidal 100 %, Autre (s) cépage (s)"),
    ("f4", "Plain", "Dom F", "Blanc", "Vidal"),
    # a placeholder with the top percentage means the lead grape is unknown: attach like a NULL
    ("u1", "Unknown lead", "Dom U", "Rouge", "Grenache 100 %"),
    ("u2", "Unknown lead", "Dom U", "Rouge", "Autre (s) cépage (s) 60 %, Mourvèdre 40 %"),
]


@pytest.fixture
def grape_db(tmp_path):
    path = tmp_path / "grapes.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE wines (sku VARCHAR, name VARCHAR, producer VARCHAR, color VARCHAR,"
        " volume_ml INTEGER, description VARCHAR, grape_primary VARCHAR, grapes VARCHAR)"
    )
    con.executemany(
        "INSERT INTO wines VALUES (?,?,?,?,750,NULL,?,NULL)", GRAPE_WINES
    )
    con.executemany(
        "INSERT INTO wines VALUES (?,?,?,?,750,NULL,split_part(?, ' ', 1),?)",
        [(*w, w[4]) for w in BLEND_WINES],
    )
    con.close()
    return path


def npcg_mapping(grape_db, tmp_path):
    return mapping(grape_db, tmp_path / "out", "npcg")[0]


def test_npcg_registered_and_file_named(grape_db, tmp_path):
    assert METHODS["npcg"]
    _, out = mapping(grape_db, tmp_path / "out", "npcg")
    assert out.name == "wine_groups_npcg.parquet"


def test_npcg_different_grapes_split(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["g1"][0] == m["g2"][0]
    assert m["g1"][0] != m["g3"][0]
    assert m["g1"][0] != m["g4"][0]


def test_npcg_grape_variants_do_not_split(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["g4"][0] == m["g5"][0] == m["g6"][0]
    assert m["a1"][0] == m["a3"][0]


def test_npcg_more_grape_variants_merge(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    for a, b in [("v1", "v2"), ("v3", "v4"), ("v5", "v6"), ("v7", "v8")]:
        assert m[a][0] == m[b][0]


def test_npcg_junk_grape_treated_as_missing(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["j2"][0] == m["j1"][0]


def test_npcg_null_attaches_to_single_sibling_grape(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["a2"][0] == m["a1"][0]
    assert m["a2"][1] == m["a1"][1]


def test_npcg_null_stay_together_without_grape_siblings(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["n1"][0] == m["n2"][0]


def test_npcg_null_stays_apart_when_siblings_disagree(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["d3"][0] == m["d4"][0]
    assert m["d3"][0] not in {m["d1"][0], m["d2"][0]}
    assert m["d3"][1] == "disagree|dom d|rouge|"


def test_npcg_tied_blend_does_not_depend_on_listing_order(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["t1"][0] == m["t2"][0]
    assert m["t1"][1] == "tie|dom t2|rouge|merlot"


def test_npcg_highest_percentage_leads(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["p1"][0] == m["p2"][0]
    assert m["p1"][1] == "pct|dom p|rouge|merlot"


def test_npcg_grapes_without_percentage_use_first_listed(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["f1"][0] == m["f2"][0]
    assert m["f3"][0] == m["f4"][0]
    assert m["f1"][0] != m["f3"][0]


def test_npcg_placeholder_lead_is_not_replaced_by_a_minor_grape(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["u2"][0] == m["u1"][0]
    assert m["u2"][1] == m["u1"][1]


def test_npcg_never_merges_across_base_groups(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["o1"][0] != m["a1"][0]


def test_npcg_key_is_npc_key_plus_grape(grape_db, tmp_path):
    m = npcg_mapping(grape_db, tmp_path)
    assert m["g4"][1] == "cuvee|dom a|rouge|cabernet sauvignon"
    assert m["n1"][1] == "nothing|dom c|rouge|"


def test_npcg_reports_no_grape_outcomes(grape_db, tmp_path, capsys):
    mapping(grape_db, tmp_path / "out", "npcg")
    out = capsys.readouterr().out
    # a2, the junk-grape j2 and the placeholder-led u2 attach; n1/n2 stay together; d3/d4 are ambiguous
    assert "3 attached to siblings, 2 kept together, 2 ambiguous" in out


def test_unknown_method_rejected(db, tmp_path):
    with pytest.raises(ValueError, match="nope"):
        group_wines(db, tmp_path / "out", "nope")
