"""Build the clean DuckDB database from the raw SAQ SQLite scrape.

    uv run python -m src.data.build_db

Reads  data/raw/saq.db            (immutable raw scrape)
Writes data/processed/winescience.duckdb
"""

import argparse
from pathlib import Path

import duckdb

from src import DATA_DIR

RAW_DB = DATA_DIR / "raw" / "saq.db"
OUT_DB = DATA_DIR / "processed" / "winescience.duckdb"


def attr(key: str) -> str:
    """Extract a string from the 'attributes' JSON object (empty string -> NULL)."""
    path = f'$.attributes."{key}"'.replace("'", "''")
    return f"nullif(trim(json_extract_string(j, '{path}')), '')"


def tasting(key: str) -> str:
    path = f'$.tasting."{key}"'.replace("'", "''")
    return f"nullif(trim(json_extract_string(j, '{path}')), '')"


def num(expr: str) -> str:
    """Parse a French-formatted number out of a string ('14,5 %' -> 14.5)."""
    return f"try_cast(replace(regexp_extract({expr}, '(\\d+(?:,\\d+)?)', 1), ',', '.') AS DOUBLE)"


def level(key: str) -> str:
    return f"try_cast({tasting(key + ' (niveau)')} AS TINYINT)"


def unescape(expr: str) -> str:
    for ent, ch in (("&#039;", "''"), ("&amp;", "&"), ("&quot;", '"')):
        expr = f"replace({expr}, '{ent}', '{ch}')"
    return expr


WINES_SQL = f"""
CREATE OR REPLACE TABLE wines AS
WITH src AS (
    SELECT sku, product_id, url, lastmod, fetched_at, json(data) AS j
    FROM raw.products WHERE is_wine = 1
), parsed AS (
    SELECT
        sku,
        product_id::VARCHAR                                           AS product_id,
        url,
        json_extract_string(j, '$.name')                              AS name,
        {attr('Couleur')}                                              AS color,
        json_extract_string(j, '$.type')                              AS saq_type,
        json_extract_string(j, '$.categories') LIKE '%Solde d''inventaire%' AS on_clearance,
        json_extract_string(j, '$.categories') LIKE '%d''alcool et moins%'  AS is_low_alcohol,
        try_cast(json_extract_string(j, '$.price') AS DECIMAL(10, 2)) AS price,
        json_extract_string(j, '$.currency')                          AS currency,
        json_extract_string(j, '$.availability') = 'InStock'          AS in_stock,
        try_cast(json_extract_string(j, '$.rating_count') AS INTEGER) AS rating_count,
        try_cast(json_extract_string(j, '$.rating') AS DOUBLE)        AS rating_raw,
        json_extract_string(j, '$.pastille_gout')                     AS taste_tag,
        {unescape("json_extract_string(j, '$.description')")}         AS description,
        {unescape("json_extract_string(j, '$.detailed_description')")} AS detailed_description,
        json_extract_string(j, '$.image')                             AS image_url,

        {attr('Pays')}                                                 AS country,
        {attr('Région')}                                               AS region,
        {attr("Appellation d'origine")}                                AS appellation,
        {attr('Désignation réglementée')}                              AS regulated_designation,
        {attr('Classification')}                                       AS classification,
        {attr('Producteur')}                                           AS producer,
        {attr('Agent promotionnel')}                                   AS agent,
        {attr('Cépage')}                                               AS grapes,
        {attr("Degré d'alcool")}                                       AS abv_raw,
        {attr('Format')}                                               AS format_raw,
        {attr('Taux de sucre')}                                        AS sugar_raw,
        {attr('Particularité')}                                        AS features,
        {attr('Produit du Québec')}                                    AS quebec_raw,
        {attr('Code CUP')}                                             AS upc,

        {tasting('Arômes')}                                            AS aromas,
        {tasting('Bouche')}                                            AS palate,
        {level('Bouche')}                                              AS palate_level,
        {tasting('Corps')}                                             AS body,
        {level('Corps')}                                               AS body_level,
        {tasting('Acidité')}                                           AS acidity,
        {level('Acidité')}                                             AS acidity_level,
        {tasting('Sucrosité')}                                         AS sweetness,
        {level('Sucrosité')}                                           AS sweetness_level,
        {tasting('Bois')}                                              AS oak,
        {level('Bois')}                                                AS oak_level,
        {tasting('Température de service')}                            AS serving_temp_raw,
        {tasting('Potentiel de garde')}                                AS aging_raw,
        try_cast({tasting('Millésime dégusté')} AS SMALLINT)           AS vintage_tasted,
        fetched_at
    FROM src
)
SELECT
    sku, product_id, url, name, color, saq_type,
    on_clearance, is_low_alcohol,
    price, currency, in_stock,
    -- SAQ stores 0.0 for "never rated"; treat as missing
    CASE WHEN rating_count > 0 THEN rating_raw END                    AS rating,
    rating_count,
    taste_tag, description, detailed_description, image_url,
    country, region, appellation, regulated_designation, classification,
    producer, agent, grapes,
    trim(regexp_replace(split_part(grapes, ',', 1), '\\s*\\d+\\s*%.*$', '')) AS grape_primary,
    {num('abv_raw')}                                                   AS abv,
    CASE
        WHEN format_raw ILIKE '%ml'  THEN {num('format_raw')}
        WHEN format_raw ILIKE '%cl'  THEN {num('format_raw')} * 10
        WHEN format_raw ILIKE '% L'  THEN {num('format_raw')} * 1000
    END::INTEGER                                                       AS volume_ml,
    {num('sugar_raw')}                                                 AS sugar_g_l,
    coalesce(sugar_raw LIKE '<%', false)                               AS sugar_below_threshold,
    features,
    coalesce(features LIKE '%Produit bio%', false)                     AS is_organic,
    coalesce(features LIKE '%Nature%', false)                          AS is_natural,
    coalesce(features LIKE '%Biodynamique%', false)                    AS is_biodynamic,
    coalesce(features LIKE '%Vin orange%', false)                      AS is_orange,
    quebec_raw IS NOT NULL                                             AS is_quebec,
    upc,
    aromas, palate, palate_level, body, body_level, acidity, acidity_level,
    sweetness, sweetness_level, oak, oak_level,
    try_cast(regexp_extract(serving_temp_raw, '(\\d+)\\D+(\\d+)', 1) AS TINYINT) AS serving_temp_min_c,
    try_cast(regexp_extract(serving_temp_raw, '(\\d+)\\D+(\\d+)', 2) AS TINYINT) AS serving_temp_max_c,
    aging_raw = 'Prêt à boire'                                         AS ready_to_drink,
    try_cast(regexp_extract(aging_raw, '(\\d+) ans', 1) AS TINYINT)    AS keep_years,
    vintage_tasted,
    try_cast(fetched_at AS TIMESTAMPTZ)                                AS scraped_at
FROM parsed;
"""

BULK_IMPORT_DATES = ("2021-07-15", "2021-10-18")

REVIEWS_SQL = f"""
CREATE OR REPLACE TABLE customer_reviews AS
WITH cleaned AS (
    SELECT
        review_id                          AS review_num,
        review_id::VARCHAR                 AS review_id,
        sku,
        rating_pct::TINYINT                AS rating_pct,
        rating::DOUBLE                     AS rating,
        nullif(trim(title), '')            AS title,
        nullif(trim(content), '')          AS content,
        nullif(trim(author), '')           AS author,
        try_cast(review_date AS DATE)      AS review_date,
        language,
        try_cast(scraped_at AS TIMESTAMPTZ) AS scraped_at
    FROM raw.customer_reviews
    WHERE sku IN (SELECT sku FROM wines)
)
SELECT
    * EXCLUDE (review_num),
    -- two days when old reviews were bulk-imported; review_date is not the real posting date
    coalesce(review_date IN ({', '.join(f"DATE '{d}'" for d in BULK_IMPORT_DATES)}), false)
                                           AS is_bulk_import_date
FROM cleaned
-- exact duplicates (same sku, author, date, content) collapse to the lowest review id
QUALIFY row_number() OVER (
    PARTITION BY sku, author, review_date, content ORDER BY review_num
) = 1;
"""

PICKS_SQL = """
CREATE OR REPLACE TABLE employee_picks AS
SELECT
    id::VARCHAR                        AS pick_id,
    sku,
    employee_id,
    employee_name,
    store_name,
    store_ref,
    try_cast(pick_date AS DATE)        AS pick_date,
    nullif(trim(content), '')          AS content,
    try_cast(scraped_at AS TIMESTAMPTZ) AS scraped_at
FROM raw.employee_picks
WHERE sku IN (SELECT sku FROM wines);
"""


def build(raw_db: Path = RAW_DB, out_db: Path = OUT_DB) -> None:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    out_db.unlink(missing_ok=True)
    con = duckdb.connect(str(out_db))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{raw_db}' AS raw (TYPE sqlite, READ_ONLY)")
    for sql in (WINES_SQL, REVIEWS_SQL, PICKS_SQL):
        con.execute(sql)
    wine_reviews = con.execute(
        "SELECT count(*) FROM raw.customer_reviews WHERE sku IN (SELECT sku FROM wines)"
    ).fetchone()[0]
    con.execute("DETACH raw")
    for t in ("wines", "customer_reviews", "employee_picks"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n:,} rows")
        if t == "customer_reviews":
            print(f"{wine_reviews - n:,} duplicate reviews dropped")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=RAW_DB)
    ap.add_argument("--out", type=Path, default=OUT_DB)
    args = ap.parse_args()
    build(args.raw, args.out)
