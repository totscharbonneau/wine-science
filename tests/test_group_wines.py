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


def test_unknown_method_rejected(db, tmp_path):
    with pytest.raises(ValueError, match="nope"):
        group_wines(db, tmp_path / "out", "nope")
