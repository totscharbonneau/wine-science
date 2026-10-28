import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import duckdb
    import pandas as pd
    from src import DATA_DIR

    return DATA_DIR, duckdb, mo, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Issue 11: Training objective, what counts as similar

    **Wayfinder ticket:** *Training objective: what counts as similar* (map #8).

    Question: what should the embedding be trained to make close, and which features are inputs
    versus targets so nothing leaks. This notebook is the trace of the facts checked while grilling.
    Each section records a number that backed (or changed) a recommendation.
    """)
    return


@app.cell(hide_code=True)
def _(DATA_DIR, duckdb):
    con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
    con.sql(
        f"create or replace temp view grp as select * from read_parquet('{DATA_DIR}/processed/wine_groups_npc.parquet')"
    )
    return (con,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Coverage of candidate targets per `npc` group

    A group counts as covered when any of its SKUs has a non-null value. This is the ceiling for any
    loss term that needs that label.
    """)
    return


@app.cell(hide_code=True)
def _(con):
    coverage = con.sql("""
        with x as (
          select grp.group_id, count(*) as n_sku,
            bool_or(color is not null) as color,
            bool_or(country is not null) as country,
            bool_or(region is not null) as region,
            bool_or(grape_primary is not null) as lead_grape,
            bool_or(taste_tag is not null) as taste_tag,
            bool_or(body_level is not null) as tasting_levels,
            bool_or(aromas is not null) as aromas,
            bool_or(abv is not null) as abv,
            bool_or(sugar_g_l is not null) as sugar_g_l,
            bool_or(keep_years is not null) as keep_years,
            bool_or(description is not null or detailed_description is not null) as any_text
          from grp join wines using (sku) group by 1
        )
        select count(*) as n_groups, sum((n_sku > 1)::int) as multi_sku_groups,
          avg(color::int) color, avg(country::int) country, avg(region::int) region,
          avg(lead_grape::int) lead_grape, avg(taste_tag::int) taste_tag,
          avg(tasting_levels::int) tasting_levels, avg(aromas::int) aromas, avg(abv::int) abv,
          avg(sugar_g_l::int) sugar_g_l, avg(keep_years::int) keep_years, avg(any_text::int) any_text
        from x
    """).df().T.rename(columns={0: "value"})
    coverage
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading.** Color, country and `abv` cover every group; region and lead grape about 95%; residual
    sugar 57%; tasting levels, `aromas` and `taste_tag` 25 to 31% (the same quarter of the catalog).
    `keep_years` covers only 1.1%, too thin to be a target. Every group has text. Only 2,655 groups
    (17%) have more than one SKU.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Who are the multi-SKU groups?

    Vintage pairs only exist for groups with 2+ SKUs. If those groups differ from the rest (price,
    reviews, picks, tasting traits), a pair-based loss would train mostly on one kind of wine.
    """)
    return


@app.cell(hide_code=True)
def _(con):
    multi_profile = con.sql("""
        with x as (
          select grp.group_id, count(*) as n_sku, median(price) as price,
            bool_or(rating_count > 0) as has_rating, bool_or(taste_tag is not null) as has_taste_tag,
            bool_or(body_level is not null) as has_levels, any_value(color) as color
          from grp join wines using (sku) group by 1
        ),
        r as (select distinct grp.group_id, true as has_review from grp join customer_reviews using (sku)),
        p as (select distinct grp.group_id, true as has_pick from grp join employee_picks using (sku))
        select (n_sku > 1) as multi_sku, count(*) as n_groups, round(median(price), 1) as median_price,
          round(avg(coalesce(has_review, false)::int), 3) as share_reviewed,
          round(avg(coalesce(has_pick, false)::int), 3) as share_picked,
          round(avg(has_taste_tag::int), 3) as share_taste_tag,
          round(avg(has_levels::int), 3) as share_levels,
          round(avg((color = 'Rouge')::int), 3) as share_red
        from x left join r using (group_id) left join p using (group_id)
        group by 1 order by 1
    """).df()
    multi_profile
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading.** Multi-SKU groups are a different population: median price $136 against $33, 73% red
    against 58%, and far less behavioural or taste coverage (35% reviewed against 64%, 7.5% with a
    `taste_tag` against 29%). A vintage-pair loss would train mostly on expensive reds with little
    taste labelling. Review text is short (median 81 characters, 104k reviews); pick text median 170
    characters (9.6k picks).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Would the extra targets add anything? (Q2)

    For each candidate target we ask three things at group level (first non-null SKU value):

    - **Coverage**: how many groups can score this loss term.
    - **Majority share**: accuracy of always guessing the most common value. A target at 99% is
      nearly constant and teaches nothing.
    - **Leave-one-out lift from the core targets**: guess a group's value from the *other* groups
      with the same country + region + color + lead grape (fall back to the global majority when the
      cell has no other group). If that is already near-perfect, the target is **redundant** with
      fields we predict anyway. If it barely beats the majority guess, the target carries
      **independent** information the embedding would have to learn from elsewhere (text).

    `taste_tag` and `abv` are included as reference rows for targets already in the list.
    """)
    return


@app.cell(hide_code=True)
def _(con):
    group_fields = con.sql("""
        select grp.group_id,
          any_value(color) as color, any_value(country) as country, any_value(region) as region,
          any_value(grape_primary) as grape_primary,
          any_value(taste_tag) as taste_tag,
          any_value(appellation) as appellation,
          any_value(classification) as classification,
          any_value(regulated_designation) as regulated_designation,
          bool_or(is_organic) as is_organic, bool_or(is_natural) as is_natural,
          bool_or(is_biodynamic) as is_biodynamic, bool_or(is_orange) as is_orange,
          bool_or(is_low_alcohol) as is_low_alcohol,
          any_value(ready_to_drink) as ready_to_drink,
          any_value(serving_temp_min_c) as serving_temp_min_c,
          any_value(serving_temp_max_c) as serving_temp_max_c
        from grp join wines using (sku) group by 1
    """).df()
    cell_key = ["country", "region", "color", "grape_primary"]
    return cell_key, group_fields


@app.cell(hide_code=True)
def _(cell_key, group_fields, pd):
    def loo_lift(df, target):
        """Leave-one-out accuracy of guessing `target` from the majority of the other groups sharing cell_key."""
        d = df.dropna(subset=[target]).copy()
        d[cell_key] = d[cell_key].fillna("?")
        d[target] = d[target].astype(str)
        global_major = d[target].mode().iat[0]
        counts = d.groupby(cell_key + [target]).size().rename("n").reset_index()
        hits = 0
        for key, sub in d.groupby(cell_key):
            c = counts
            for k, v in zip(cell_key, key):
                c = c[c[k] == v]
            votes = c.set_index(target)["n"]
            for val in sub[target]:
                v = votes.copy()
                v[val] -= 1
                v = v[v > 0]
                guess = v.idxmax() if len(v) else global_major
                hits += guess == val
        return hits / len(d)


    candidates = [
        "taste_tag", "appellation", "classification", "regulated_designation",
        "is_organic", "is_natural", "is_biodynamic", "is_orange", "is_low_alcohol",
        "ready_to_drink", "serving_temp_min_c", "serving_temp_max_c",
    ]
    rows = []
    for _t in candidates:
        _d = group_fields[_t].dropna()
        rows.append({
            "target": _t,
            "coverage": round(len(_d) / len(group_fields), 3),
            "n_values": _d.nunique(),
            "majority_share": round(_d.astype(str).value_counts(normalize=True).iat[0], 3),
            "loo_from_core": round(loo_lift(group_fields, _t), 3),
        })
    target_report = pd.DataFrame(rows).set_index("target")
    target_report
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading** (flags show 100% coverage because SAQ stores them as false rather than missing, so
    "covered" does not mean "labelled").

    - **Worth adding**: `appellation` (77% coverage, 786 values, only 45% recoverable from
      country/region/color/grape) and `classification` (14% coverage, 44% recoverable) carry origin
      detail the core targets miss. `serving_temp_min/max_c` (30% coverage, 57% recoverable) track
      style (light white versus structured red) and sit on the same quarter as the tasting traits.
      `regulated_designation` (99% coverage, 88% recoverable) mostly repeats origin: low value.
    - **Marginal**: `is_organic` (25% positive, 78% guessable) is the only flag with real variance.
    - **Not worth it**: `is_natural` (10%), `is_biodynamic` (4%), `is_orange` (1.7%) and
      `is_low_alcohol` (0.3%) are nearly constant, so a loss on them is almost all one class.
      `ready_to_drink` covers 3.8% of groups.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Do input texts echo the targets? (leakage)

    If a group's own `name`, `description` or `detailed_description` already spells out the target
    value, a model fed that text can score the target by copying, without learning anything about the
    wine. For each text target we count the share of groups (with that target present) whose text
    contains the value, accent- and case-insensitive. `aromas` and `taste_tag` are not in the list: they
    are separate fields, not free text, and `aromas` is itself a target.
    """)
    return


@app.cell(hide_code=True)
def _(con, pd):
    leak_src = con.sql("""
        select grp.group_id,
          strip_accents(lower(string_agg(distinct coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(detailed_description, ''), ' '))) as txt,
          strip_accents(lower(string_agg(distinct coalesce(name, ''), ' '))) as name_txt,
          any_value(country) as country, any_value(region) as region, any_value(grape_primary) as grape,
          any_value(appellation) as appellation, any_value(classification) as classification,
          any_value(color) as color
        from grp join wines using (sku) group by 1
    """).df()


    def _norm(s):
        return con.sql("select strip_accents(lower(?))", params=[s]).fetchone()[0]


    leak_rows = []
    for _t in ["country", "region", "grape", "appellation", "classification", "color"]:
        _d = leak_src.dropna(subset=[_t])
        _v = _d[_t].map(_norm)
        leak_rows.append({
            "target": _t,
            "groups_with_value": len(_d),
            "in_name": round(sum(v in n for v, n in zip(_v, _d["name_txt"])) / len(_d), 3),
            "in_name_or_description": round(sum(v in n for v, n in zip(_v, _d["txt"])) / len(_d), 3),
        })
    leak_report = pd.DataFrame(leak_rows).set_index("target")
    leak_report
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading.** The `description` field is not free prose at its start. It is a template that spells
    out the structured fields, e.g. *"... vin rose. format : 750 ml. origine : vallee de la loire.
    france. cepage : pinot noir. producteur : sas laporte. pastille de gout : fruite et vif ..."*.
    So country, color and lead grape appear in the name-or-description text for 99% of groups, region
    for 47%, appellation 73%. Even `taste_tag` can appear verbatim ("pastille de gout"). The
    `name` alone echoes the lead grape for 24% and the appellation for 66% of groups.
    Feeding that text in and also asking the model to predict those fields would let it copy. The
    editorial sentences after the template are the real prose; `aromas`, `palate` and the review/pick
    text are separate.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. How many groups have behavioural text at all? (Q3)

    Review text and pick text are the richest taste language, but only some groups have any. This is
    the share that gets which kind, and how much text the reviewed ones carry.
    """)
    return


@app.cell(hide_code=True)
def _(con):
    text_coverage = con.sql("""
        with r as (select grp.group_id, count(*) as n_reviews, sum(length(content)) as review_chars
                   from grp join customer_reviews using (sku) where content is not null group by 1),
             p as (select grp.group_id, count(*) as n_picks from grp join employee_picks using (sku) group by 1),
             base as (select distinct group_id from grp)
        select
          case when r.group_id is not null and p.group_id is not null then 'reviews + picks'
               when r.group_id is not null then 'reviews only'
               when p.group_id is not null then 'picks only'
               else 'neither' end as behavioural_text,
          count(*) as n_groups,
          round(count(*) / sum(count(*)) over (), 3) as share,
          median(r.n_reviews) as median_reviews, median(r.review_chars) as median_review_chars
        from base left join r using (group_id) left join p using (group_id)
        group by 1 order by n_groups desc
    """).df()
    text_coverage
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Decisions reached while grilling (pending user confirmation)

    1. **Stage 1 (core): self-supervised.** Two randomly field-hidden views of the same wine group are
       positives; other groups in the batch are negatives, except near-duplicate groups. Vintages of
       a group are one source of views. Hard negatives are a later option.
    2. **Stage 2 (tested add-on): attribute prediction.** Hide a field, predict it, score only on
       wines that have it. Targets: color, country, region, lead grape, `taste_tag`, the five 0-3
       tasting levels, `abv`, `sugar_g_l`, `aromas` text, `appellation`, `classification`,
       `serving_temp_min/max_c`, `is_organic`. Out: price, stock, rating, `keep_years` (1.1%
       coverage), `regulated_designation`, the near-constant flags, `ready_to_drink`. Kept only if it
       beats stage 1 on signals training never used. Each term is averaged over the wines that have
       its label; term weights are hyperparameters, out of scope.
    3. **Floor:** an untrained off-the-shelf text embedding of the wine's fields. Every stage must beat it.
    4. **Evaluation consequence.** The stage 2 attributes are the held-out probes for stage 1, so
       stage 1 is never trained on them as targets.
    5. **Review and pick text is an input** that is hidden at random, with an agreement penalty
       between the with-text and without-text vectors, plus an optional target that predicts its
       embedding. 40% of groups have neither, so this is an experiment: the fallback is target-only,
       chosen by comparing reviewed and unreviewed wines on the evaluation panel.
    6. **One partial-view mechanism** serves missing text, the leakage rule and the two-view term.
    7. **Leakage rule.** A field is never input and target on the same example. The templated lines of
       `description` (format, origin, cepage, producteur, pastille de gout) are stripped; `name` is
       hidden whenever producer, appellation or grape is a target.
    8. **`rating` and `rating_count`** belong to the review modality: hidden with the reviews, never targets.
    9. **Dropped:** a separate vintage-pair loss, co-review pairs as supervision (#10), and
       employee-pick co-occurrence as a default loss (optional, off).

    Handed to other tickets: price and stock as inputs, held-out splits and producer leakage,
    evaluation metrics, French-text handling.
    """)
    return


@app.cell
def _(con, mo, wines):
    _df = mo.sql(
        f"""
        SELECT * FROM wines
        """,
        engine=con
    )
    return


if __name__ == "__main__":
    app.run()
