"""Tests for src.data.build_db, run against a tiny hand-made raw SQLite DB."""

import json
import sqlite3

import duckdb
import pytest

from src.data.build_db import build

RAW_SCHEMA = """
CREATE TABLE products (
    sku TEXT PRIMARY KEY, url TEXT NOT NULL, lastmod TEXT, fetched_at TEXT,
    status INTEGER, is_wine INTEGER, data TEXT, product_id INTEGER
);
CREATE TABLE customer_reviews (
    review_id INTEGER PRIMARY KEY, sku TEXT NOT NULL, rating_pct INTEGER,
    rating REAL, title TEXT, content TEXT, author TEXT, review_date TEXT,
    scraped_at TEXT NOT NULL, language TEXT
);
CREATE TABLE employee_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT NOT NULL, employee_id TEXT,
    employee_name TEXT, store_name TEXT, store_ref TEXT, pick_date TEXT,
    content TEXT, scraped_at TEXT NOT NULL
);
"""

RED = {
    "type": "Vin rouge",
    "categories": ["Vin", "Vin rouge"],
    "name": "Château Test",
    "description": "Vin rouge &quot;test&quot; d&#039;ici &amp; là",
    "price": 24.95,
    "currency": "CAD",
    "availability": "InStock",
    "rating": 4.2,
    "rating_count": 10,
    "attributes": {
        "Pays": "France",
        "Cépage": "Syrah 60 %, Grenache 40 %",
        "Degré d'alcool": "14,5 %",
        "Couleur": "Rouge",
        "Format": "750 ml",
        "Taux de sucre": "< 3 g/L",
        "Particularité": "Produit bio, Vin orange",
        "Producteur": "  Domaine X  ",
        "Région": "",
    },
    "tasting": {
        "Millésime dégusté": "2020",
        "Corps (niveau)": 3,
        "Température de service": "De 16°C à 18°C",
        "Potentiel de garde": "À boire ou à garder 5 ans",
    },
}

WHITE_UNRATED = {
    "type": "Vin blanc",
    "categories": ["Vin", "Vin blanc", "Solde d'inventaire"],
    "name": "Blanc Magnum",
    "price": 99,
    "availability": "OutOfStock",
    "rating": 0.0,
    "rating_count": 0,
    "attributes": {"Degré d'alcool": "12 %", "Format": "1,5 L"},
    "tasting": {"Potentiel de garde": "Prêt à boire"},
}


def _product(sku, data, is_wine=1):
    return (sku, f"https://saq.test/{sku}", None, "2026-10-15T12:00:00+00:00",
            200, is_wine, json.dumps({"sku": sku, **data}), int(sku))


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("build")
    raw, out = tmp / "raw.db", tmp / "out.duckdb"

    db = sqlite3.connect(raw)
    db.executescript(RAW_SCHEMA)
    db.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
        [
            _product("1001", RED),
            _product("1002", WHITE_UNRATED),
            _product("2001", {"type": "Bière", "name": "Not wine"}, is_wine=0),
        ],
    )
    db.executemany(
        "INSERT INTO customer_reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "1001", 90, 4.5, " Bon ", "Très bon", "Marie L.", "2026-01-02", "2026-10-15", "fr"),
            (2, "2001", 50, 2.5, "x", "y", "Bob", "2026-01-02", "2026-10-15", "en"),
        ],
    )
    db.execute(
        "INSERT INTO employee_picks (sku, employee_id, pick_date, content, scraped_at)"
        " VALUES ('1001', 'e1', '2026-02-03', '', '2026-10-15')"
    )
    db.commit()
    db.close()

    build(raw, out)
    c = duckdb.connect(str(out), read_only=True)
    yield c
    c.close()


def wine(con, sku, col):
    return con.execute(f"SELECT {col} FROM wines WHERE sku = ?", [sku]).fetchone()[0]


def test_only_wines_kept(con):
    assert [r[0] for r in con.execute("SELECT sku FROM wines ORDER BY sku").fetchall()] == ["1001", "1002"]


def test_reviews_and_picks_filtered_to_wines(con):
    assert con.execute("SELECT review_id FROM customer_reviews").fetchall() == [("1",)]
    assert con.execute("SELECT count(*) FROM employee_picks").fetchone()[0] == 1


def test_unescape_html_entities(con):
    assert wine(con, "1001", "description") == 'Vin rouge "test" d\'ici & là'


def test_num_parses_french_decimal(con):
    assert wine(con, "1001", "abv") == 14.5
    assert wine(con, "1002", "abv") == 12.0


def test_volume_units(con):
    assert wine(con, "1001", "volume_ml") == 750
    assert wine(con, "1002", "volume_ml") == 1500


def test_empty_and_whitespace_become_null_or_trimmed(con):
    assert wine(con, "1001", "region") is None
    assert wine(con, "1001", "producer") == "Domaine X"
    assert con.execute("SELECT content FROM employee_picks").fetchone()[0] is None
    assert con.execute("SELECT title FROM customer_reviews").fetchone()[0] == "Bon"


def test_rating_zero_is_null(con):
    assert wine(con, "1002", "rating") is None
    assert wine(con, "1001", "rating") == 4.2


def test_derived_columns(con):
    assert wine(con, "1001", "grape_primary") == "Syrah"
    assert wine(con, "1001", "is_organic") is True
    assert wine(con, "1001", "is_orange") is True
    assert wine(con, "1002", "is_organic") is False
    assert wine(con, "1001", "sugar_below_threshold") is True
    assert wine(con, "1001", "serving_temp_min_c") == 16
    assert wine(con, "1001", "serving_temp_max_c") == 18
    assert wine(con, "1001", "keep_years") == 5
    assert wine(con, "1002", "ready_to_drink") is True
    assert wine(con, "1002", "on_clearance") is True
    assert wine(con, "1001", "body_level") == 3
    assert wine(con, "1001", "vintage_tasted") == 2020


def test_price_and_stock(con):
    assert float(wine(con, "1001", "price")) == 24.95
    assert wine(con, "1001", "in_stock") is True
    assert wine(con, "1002", "in_stock") is False
