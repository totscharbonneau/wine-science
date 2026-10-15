# Data

Wine data scraped from [saq.com](https://www.saq.com) (the Société des alcools du Québec).
The data files themselves are not committed (see `.gitignore`); this document describes them.

## Layout

```
data/
├── raw/saq.db                       # immutable scrape (SQLite), never edited by hand
├── exports/*.csv                    # flat dumps of the raw DB, regenerable, not used by the pipeline
└── processed/winescience.duckdb     # clean, typed database used for all analysis
```

| Stage | Produced by | Notes |
|---|---|---|
| `raw/saq.db` | `scraper/saq_scraper.py` (local, not in the repo) | Read-only between scrapes. Wine attributes are stored as a JSON blob in `products.data`. |
| `processed/winescience.duckdb` | `uv run python -m src.data.build_db` | Rebuilt from scratch on every run. |

Scrape dates: 2026-09-30 to 2026-10-15. Row counts below are from the 2026-10-15 build and
will change with a re-scrape.

## Collection

- The wine list comes from the search service behind saq.com's own wine listing; each wine's
  product page is then parsed for details, tasting notes, employee picks and customer reviews.
- The scraper is rate limited and slows down on HTTP 429.
- Only wines are kept (`produits/vin`). Spirits, beer and other categories are not included.
- The data is a **snapshot**: prices, stock and ratings are as of the scrape date.

## `winescience.duckdb`

Three tables, joined on `sku`:

| Table | Rows | One row per |
|---|---|---|
| `wines` | ~21,300 | wine (primary key `sku`) |
| `customer_reviews` | ~104,800 | customer review (`review_id`) |
| `employee_picks` | ~9,650 | employee "coup de coeur" (`pick_id`) |

Open it read-only so notebooks can't modify it:

```python
import duckdb
from src import DATA_DIR

con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
con.sql("SELECT color, count(*), median(price) FROM wines GROUP BY color").show()
```

### What the build does

1. **Flattens** the raw JSON `data` column (including the nested `attributes` and `tasting`
   objects) into one typed column each.
2. **Parses types**: `"14,5 %"` to `abv = 14.5`, `"1,5 L"` to `volume_ml = 1500`, `"<1,2 g/L"` to
   `sugar_g_l = 1.2` (with `sugar_below_threshold`), prices to `DECIMAL`, dates to `DATE`, scrape
   times to `TIMESTAMPTZ`.
3. **Cleans**: empty strings become `NULL`, text is trimmed, HTML entities are unescaped,
   column names are translated from French to English snake_case, and IDs are stored as `VARCHAR`.
4. **Filters**: only wines, and only reviews and picks that belong to one of those wines.
5. **De-duplicates reviews**: reviews with the same `sku`, `author`, `review_date` and `content`
   collapse to one row, keeping the lowest `review_id`. The build prints how many it dropped
   (386 on the 2026-10-15 snapshot). Reviews with the same author, sku and date but different
   text are all kept.
6. **Derives** a few convenience columns (see below).

### `wines`

| Column(s) | Type | Description |
|---|---|---|
| `sku`, `product_id` | VARCHAR | SAQ product code and internal id. `sku` is the join key. |
| `url`, `image_url` | VARCHAR | Product page and image. |
| `name` | VARCHAR | Product name as shown on saq.com. |
| `color` | VARCHAR | `Rouge`, `Blanc` or `Rosé`. Use this for wine color. |
| `saq_type` | VARCHAR | SAQ's own type. Includes `Vin nature`, which is **not** a color. |
| `price`, `currency` | DECIMAL(10,2), VARCHAR | Price in CAD. `NULL` when not listed (mostly out of stock). |
| `in_stock` | BOOLEAN | Online availability at scrape time. |
| `rating`, `rating_count` | DOUBLE, INTEGER | Average customer rating (0-5) and number of ratings. `rating` is `NULL` when there are no ratings (SAQ stores 0.0). |
| `taste_tag` | VARCHAR | SAQ's "pastille de goût" label (e.g. `Fruité et léger`). |
| `description`, `detailed_description` | VARCHAR | Short description and longer editorial text (French). |
| `country`, `region`, `appellation`, `regulated_designation`, `classification` | VARCHAR | Origin and quality designations (French). |
| `producer`, `agent` | VARCHAR | Producer and Québec importer/agent. |
| `grapes`, `grape_primary` | VARCHAR | Raw grape string (`"Merlot 60 %, Syrah 40 %"`) and the first grape named. |
| `abv` | DOUBLE | Alcohol by volume, in percent. |
| `volume_ml` | INTEGER | Bottle size in millilitres. |
| `sugar_g_l`, `sugar_below_threshold` | DOUBLE, BOOLEAN | Residual sugar in g/L. `true` when SAQ reports `"<1,2 g/L"`. |
| `features`, `is_organic`, `is_natural`, `is_biodynamic`, `is_orange` | VARCHAR, BOOLEAN | Raw "particularité" text and flags parsed from it. |
| `is_quebec`, `on_clearance`, `is_low_alcohol` | BOOLEAN | Québec product, online clearance, 0.5 % alcohol or less. |
| `upc` | VARCHAR | Barcode (Code CUP). |
| `aromas`, `palate`, `body`, `acidity`, `sweetness`, `oak` | VARCHAR | Tasting notes as text (French). |
| `palate_level`, `body_level`, `acidity_level`, `sweetness_level`, `oak_level` | TINYINT | The matching 0-3 intensity scale. |
| `serving_temp_min_c`, `serving_temp_max_c` | TINYINT | Serving temperature range in degrees C. |
| `ready_to_drink`, `keep_years` | BOOLEAN, TINYINT | Aging potential: drink now, or years to keep after the vintage. |
| `vintage_tasted` | SMALLINT | Vintage the SAQ tasters reviewed. Not necessarily the bottle on the shelf. |
| `scraped_at` | TIMESTAMPTZ | When this wine's page was fetched. |

### `customer_reviews`

| Column | Type | Description |
|---|---|---|
| `review_id` | VARCHAR | Primary key. |
| `sku` | VARCHAR | Foreign key to `wines`. |
| `rating`, `rating_pct` | DOUBLE, TINYINT | Star rating (out of 5) and the same value as a percentage. |
| `title`, `content`, `author` | VARCHAR | Review text. Authors appear as first name plus initial. |
| `review_date` | DATE | Date posted, as published. Unreliable on the two bulk-import days (see `is_bulk_import_date`). |
| `is_bulk_import_date` | BOOLEAN | `true` when `review_date` is 2021-07-15 or 2021-10-18, days on which SAQ bulk-imported older reviews. Those dates are the import day, not when the review was written. `review_date` itself is left unchanged. |
| `language` | VARCHAR | `fr` (about 90 %) or `en`. |
| `scraped_at` | TIMESTAMPTZ | Fetch time. |

### `employee_picks`

| Column | Type | Description |
|---|---|---|
| `pick_id` | VARCHAR | Primary key. |
| `sku` | VARCHAR | Foreign key to `wines`. |
| `employee_id`, `employee_name` | VARCHAR | SAQ employee who recommended the wine. |
| `store_name`, `store_ref` | VARCHAR | Their store and its id. |
| `pick_date` | DATE | Date of the pick. |
| `content` | VARCHAR | The recommendation text (French). |
| `scraped_at` | TIMESTAMPTZ | Fetch time. |

## Known limitations

- **Missingness is structural.** Tasting traits exist for about a quarter of wines, residual sugar
  for about half, and ratings for under half. Don't impute these blindly.
- **No reliable vintage.** Only `vintage_tasted` (about 20 % of wines) is captured. The year is
  not parseable from names or descriptions.
- **Possible duplicates.** The same wine can appear under several SKUs (formats, vintages).
  Group by producer and name before splitting data for modeling, to avoid leakage.
- **Prices describe the catalog**, not just what is on the shelf: most listed wines are out of
  stock at any given time.
- **Text is mostly French**; reviews are about 90 % French.
- **Values are not normalized.** Country, region and grape spellings are as SAQ publishes them.
- **No database constraints** (primary and foreign keys) are declared yet.
- Customer review authors are shown as first name and initial; handle them with care.
