import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import duckdb
    import pandas as pd
    import re
    from src import DATA_DIR

    return DATA_DIR, duckdb, mo, pd


@app.cell(hide_code=True)
def _(DATA_DIR, duckdb):
    con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
    con.sql(
        f"create or replace temp view grp as select * from read_parquet('{DATA_DIR}/processed/wine_groups_npc.parquet')"
    )
    con.sql("create or replace temp view w as select w.*, g.group_id from wines w join grp g using(sku)")
    n_groups = con.sql("select count(distinct group_id) from w").fetchall()[0][0]
    return (con,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Issue 13: Structured catalog features, which, encoded how, missing how

    **Wayfinder ticket:** *Structured catalog features: which, encoded how, missing how* (map #8).

    This notebook checks the decisions of the grilling against the data (2026-10-15 snapshot, `npc` groups):
    how rare each label is, how often the SKUs of a group disagree, how the missing values cluster, and how many
    groups each rule affects. Decisions are in the last section.
    """)
    return


@app.cell
def _(con, pd):
    label_fields = ["country", "region", "appellation", "regulated_designation", "classification", "producer", "agent", "grape_primary", "taste_tag"]
    rarity = pd.concat([
        con.sql(f"""
            with c as (select {_f} v, count(distinct group_id) n from w where {_f} is not null group by 1)
            select '{_f}' as field, count(*) as labels, count(*) filter (where n < 5) as labels_under_5_groups,
              coalesce(sum(n) filter (where n < 5), 0) as groups_on_rare_labels,
              (select count(distinct group_id) from w where {_f} is not null) as groups_with_value
            from c
        """).df()
        for _f in label_fields
    ], ignore_index=True)
    rarity["share_of_groups_falling_back"] = (rarity.groups_on_rare_labels / rarity.groups_with_value).round(3)
    return (rarity,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Labels seen in fewer than 5 groups fall back to "other"

    Decision: a label in fewer than 5 groups falls back up the ladder (appellation, region, country) or to "other"
    (producer, agent, grape). Country, region and appellation lose little. **Producer does not:** 4,655 of 5,527
    producers are rare, and 7,929 groups (about half) end up as "other producer". The fingerprint only helps for the
    872 producers with 5 groups or more.
    """)
    return


@app.cell(hide_code=True)
def _(rarity):
    rarity
    return


@app.cell
def _(con, pd):
    multi_sku_groups = con.sql("select count(*) from (select group_id from w group by 1 having count(*) > 1)").fetchall()[0][0]
    disagree_fields = ["color", "country", "region", "appellation", "grapes", "abv", "sugar_g_l", "palate_level", "body_level",
                       "acidity_level", "sweetness_level", "oak_level", "serving_temp_min_c", "taste_tag", "is_organic", "is_natural", "is_quebec"]
    disagreement = pd.DataFrame([
        (_f, con.sql(f"select count(*) from (select group_id from w where {_f} is not null group by 1 having count(*) > 1 and count(distinct {_f}) > 1)").fetchall()[0][0])
        for _f in disagree_fields
    ], columns=["field", "multi_sku_groups_that_disagree"])
    disagreement["share_of_multi_sku_groups"] = (disagreement.multi_sku_groups_that_disagree / multi_sku_groups).round(3)
    return (disagreement,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Do the SKUs of a group disagree?

    2,655 groups have several SKUs. Colour and country never disagree and origin almost never, so "most common value"
    is safe. `abv` disagrees in 37% of multi-SKU groups and `grapes` in 19%: the median and the longest-list rules
    matter. Flags such as `is_organic` change between vintages (179 groups), which is why a flag is true if any SKU is true.
    """)
    return


@app.cell(hide_code=True)
def _(disagreement):
    disagreement
    return


@app.cell
def _(con, pd):
    tasting = con.sql("""
        select group_id,
          bool_or(palate_level is not null) as palate, bool_or(body_level is not null) as body, bool_or(acidity_level is not null) as acidity,
          bool_or(sweetness_level is not null) as sweetness, bool_or(oak_level is not null) as oak, bool_or(serving_temp_min_c is not null) as serving_temp,
          bool_or(taste_tag is not null) as taste_tag, bool_or(sugar_g_l is not null) as sugar, bool_or(price is not null) as price,
          bool_or(rating is not null) as rating, bool_or(appellation is not null) as appellation, bool_or(grapes is not null) as grapes
        from w group by 1
    """).df()
    _levels = tasting[["palate", "body", "acidity", "sweetness", "oak"]]
    tasting_block = pd.Series({
        "all five levels present": int(_levels.all(axis=1).sum()),
        "none present": int((~_levels.any(axis=1)).sum()),
        "some but not all": int((_levels.any(axis=1) & ~_levels.all(axis=1)).sum()),
        "serving temp but no levels": int((tasting.serving_temp & ~_levels.any(axis=1)).sum()),
        "levels but no serving temp": int((_levels.any(axis=1) & ~tasting.serving_temp).sum()),
        "taste_tag but no levels": int((tasting.taste_tag & ~_levels.any(axis=1)).sum()),
        "no grapes, appellation, tasting or sugar": int(((~tasting.grapes) & (~tasting.appellation) & (~_levels.any(axis=1)) & (~tasting.sugar)).sum()),
    }, name="groups").to_frame()
    field_coverage = (tasting.drop(columns="group_id").mean().round(3)).rename("share_of_groups_with_value").to_frame()
    return field_coverage, tasting_block


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Missing values

    The five levels come and go together: 4,610 groups have all five, 10,853 have none, only 171 have some. Serving temperature
    follows them but not perfectly (46 groups have levels and no temperature), so the shared "has tasting" marker is right for
    about 99% of groups and wrong for a few; a per-field marker would cost nothing. `taste_tag` exists alone for 385 groups.
    Only 26 groups lack grapes, appellation, tasting and sugar together: nearly every group has something beyond colour and country.
    """)
    return


@app.cell(hide_code=True)
def _(field_coverage, mo, tasting_block):
    mo.hstack([tasting_block, field_coverage])
    return


@app.cell
def _(con):
    price_rule = con.sql("""
        with a as (select group_id, bool_or(volume_ml = 750) as has_750 from w where price is not null group by 1)
        select count(*) as groups_with_price, count(*) filter (where has_750) as with_750_sku,
               count(*) filter (where not has_750) as need_scaling_from_other_size
        from a
    """).df()
    sugar_stats = con.sql("""
        select count(*) filter (where sugar_g_l is not null) as skus_with_sugar, count(*) filter (where sugar_below_threshold) as below_threshold,
               median(sugar_g_l) as median_g_l, quantile_cont(sugar_g_l, 0.99) as p99_g_l, max(sugar_g_l) as max_g_l
        from wines
    """).df()
    review_groups = con.sql("""
        with n as (select g.group_id, count(*) as k from customer_reviews r join grp g using(sku) where r.language = 'fr' group by 1)
        select case when k = 1 then '1' when k = 2 then '2' when k < 5 then '3-4' when k < 10 then '5-9' when k < 30 then '10-29' else '30+' end as french_reviews,
               count(*) as groups
        from n group by 1 order by min(k)
    """).df()
    return price_rule, review_groups, sugar_stats


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Price, sugar and review profiles

    - **Price per 750 ml:** 14,118 of 14,753 priced groups have a 750 ml SKU; 635 need scaling from another size.
    - **Sugar:** a log scale is needed (median 2.1 g/L, 99th percentile 28, maximum 270). 971 SKUs are "<1,2".
    - **Review profiles:** 8,914 groups (57%) have a French review, so 43% of groups get the missing marker (the earlier "40%" was rounded down).
      2,293 of the profiles rest on one review, so the log review count as a reliability marker matters.
    """)
    return


@app.cell(hide_code=True)
def _(mo, price_rule, review_groups, sugar_stats):
    mo.vstack([price_rule, sugar_stats, review_groups])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Decisions

    **In** (one vector per `npc` group): `color` (not `saq_type`), country, region, appellation, `regulated_designation`, `classification`,
    grapes, `abv`, sugar, the five tasting levels, serving temperature, `keep_years`, `ready_to_drink`, the flags (organic, natural,
    biodynamic, orange, low-alcohol, Québec), `taste_tag`, price, average rating, producer, agent, name, review profiles.
    **Out:** `in_stock`, `on_clearance`, `rating_count`, `volume_ml`, `vintage_tasted`, `upc`.

    **Encoding**
    - Country, region, appellation, producer, agent: learned fingerprints. A label in fewer than 5 groups falls back up the ladder
      (appellation, region, country). **Producer and agent: cut-off 2** (producer: 2,638 groups on "other producer", 17%, against 51% at 5). Case, accent and space folding only.
    - Grapes: percentage-weighted average of grape fingerprints (equal weights without percentages); rare grapes and SAQ's placeholder are "other grape".
    - Name: text through the text model, hidden at random in training.
    - Numbers: `abv` and serving temperature rescaled; sugar on a log scale (`"<1,2"` is 1.2 plus the flag); tasting levels and `keep_years` ordered numbers; flags 0/1.
    - Price: log of the price per 750 ml. Rating: average weighted by `rating_count`, rescaled to 0-1.
    - `taste_tag`: label fingerprint. Review profiles: shares per vocabulary word (four groups, one block), plus the log of the French review count.

    **Missing values:** no imputation; neutral value plus a **marker per field** (the tasting levels and serving temperature each get their own: 171 groups have some levels but not all).
    Hiding a field in training (#11) is the same state as missing.

    **Group collapse:** labels take the most common SKU value (ties to the newest scrape); numbers the median; grapes the longest list; flags true if any SKU is true;
    price from the 750 ml SKU; rating weighted by `rating_count`.

    **Hidden whenever reviews are hidden** (training, #11, and the exam, #12): `rating`, `taste_tag`, review profiles and the review count.
    At the exam, every score is also computed with price, rating, producer, agent and name hidden; the gap shows how much of "similar" is commercial.
    Held-out producers get the "other producer" fingerprint.

    **Scope:** all 15,634 groups. Restricting to wines with French reviews (8,914 groups, median price $27.70 against $98 for the rest) is kept in mind as a later experiment.
    **Left open:** employee-pick profiles (a later experiment).
    """)
    return


if __name__ == "__main__":
    app.run()
