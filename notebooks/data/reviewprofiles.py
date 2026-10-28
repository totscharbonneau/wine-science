import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import duckdb
    import numpy as np
    import pandas as pd
    from src import DATA_DIR, ROOT

    return DATA_DIR, ROOT, duckdb, mo, np, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Review profiles: one profile per wine group and vocabulary group

    First pass at turning customer reviews into per-wine descriptions: taste, grape and style, food pairing, occasion.

    For each `npc` wine group: of its French reviews, what share mention each word of a chosen vocabulary
    group (`taste`, `grape_style_origin`, `food_pairing`, `occasion`)? Words come from `docs/research/review-vocabulary-labels.csv`, with spelling
    variants folded into one form. Reviews only for now; employee picks come later.
    """)
    return


@app.cell(hide_code=True)
def _(DATA_DIR, duckdb):
    con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
    con.sql(
        f"create or replace temp view grp as select * from read_parquet('{DATA_DIR}/processed/wine_groups_npc.parquet')"
    )
    return (con,)


@app.cell
def _(ROOT, con, pd):
    # Which vocabulary groups to profile. Any other group of the csv (ageing, appearance, ...) can be added here.
    profile_categories = ["taste", "grape_style_origin", "food_pairing", "occasion"]

    vocab = pd.read_csv(ROOT / "docs" / "research" / "review-vocabulary-labels.csv", keep_default_na=False)
    # The csv lists, per word, the spelling variants that were folded into it.
    variant_map = pd.DataFrame(
        [(v, w) for w, vs in zip(vocab.word, vocab.variants_merged_into_it) for v in vs.split()],
        columns=["variant", "canonical"],
    )
    con.register("vocab", vocab[["word", "category"]])
    con.register("variant_map", variant_map)
    vocab.category.value_counts().to_frame("words")
    return (profile_categories,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Build the profiles

    One row per (wine group, vocabulary group, word): `n_with_word` French reviews of the group that contain the word, out of
    `n_reviews`; `share` is the ratio. A review counts once per word however many times it repeats it. Only
    words of the chosen vocabulary groups are kept.
    """)
    return


@app.cell
def _(con, profile_categories):
    profile_long = con.sql("""
        with fr as (
          select r.review_id, g.group_id, lower(r.content) as text
          from customer_reviews r join grp g using (sku)
          where r.language = 'fr'
        ),
        group_size as (select group_id, count(*) as n_reviews from fr group by group_id),
        hits as (
          select distinct t.review_id, t.group_id, coalesce(m.canonical, t.word) as word
          from (
            select review_id, group_id,
              unnest(regexp_extract_all(text, '[a-zàâäçéèêëîïôöûùüœ]+')) as word
            from fr
          ) t
          left join variant_map m on m.variant = t.word
        )
        select h.group_id, v.category, h.word, count(*) as n_with_word, s.n_reviews, count(*) * 1.0 / s.n_reviews as share
        from hits h
        join vocab v on v.word = h.word and list_contains(?, v.category)
        join group_size s on s.group_id = h.group_id
        group by h.group_id, v.category, h.word, s.n_reviews
    """, params=[profile_categories]).df()
    profile_long.head()
    return (profile_long,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. How complete are the profiles

    Per group, by how many French reviews it has: how many distinct words of each vocabulary group were found, and the share of
    groups with at least one. A group with few reviews cannot have a rich profile.
    """)
    return


@app.cell
def _(con, mo, pd, profile_categories, profile_long):
    reviewed_groups = con.sql("""
        select g.group_id, count(*) as n_reviews
        from customer_reviews r join grp g using (sku)
        where r.language = 'fr' group by g.group_id
    """).df()
    per_group = (
        profile_long.groupby(["group_id", "category"]).word.nunique().unstack("category")
        .reindex(columns=profile_categories)
    )
    coverage = reviewed_groups.merge(per_group, on="group_id", how="left").fillna(0)
    coverage["reviews"] = pd.cut(
        coverage.n_reviews, [0, 1, 2, 4, 9, 29, 100000], labels=["1", "2", "3-4", "5-9", "10-29", "30+"]
    )
    _by = coverage.groupby("reviews", observed=True)
    coverage_summary = mo.vstack([
        mo.md("**Share of groups with at least one word**"),
        pd.concat([_by.size().rename("groups"), _by[profile_categories].agg(lambda s: (s > 0).mean())], axis=1).round(2),
        mo.md("**Median distinct words per group**"),
        _by[profile_categories].median(),
    ])
    coverage_summary
    return coverage, reviewed_groups


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Example profiles

    Six random groups with 30+ French reviews: for each vocabulary group, the 6 words with the highest share of reviews. Look at whether
    the words match what you would expect for the wine.
    """)
    return


@app.cell
def _(con, coverage, profile_categories, profile_long, reviewed_groups):
    wine_names = con.sql("""
        select g.group_id, any_value(w.name) as name, any_value(w.color) as color, median(w.price) as price
        from wines w join grp g using (sku) group by 1
    """).df()
    _ids = coverage[coverage.n_reviews >= 30].sample(6, random_state=0).group_id
    _top = (
        profile_long[profile_long.group_id.isin(_ids)]
        .sort_values(["group_id", "category", "share"], ascending=[True, True, False])
        .groupby(["group_id", "category"])
        .head(6)
    )
    example_profiles = (
        _top.assign(txt=lambda d: d.word + " " + d.share.round(2).astype(str))
        .groupby(["group_id", "category"]).txt.agg(", ".join)
        .unstack("category").reindex(columns=profile_categories).fillna("")
        .reset_index()
        .merge(wine_names, on="group_id")
        .merge(reviewed_groups, on="group_id")[["name", "color", "price", "n_reviews", *profile_categories]]
    )
    example_profiles
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Comparing two profiles: which formula separates best

    We need a number for "how alike are two wines' taste profiles". Test: take each wine with 10+ French
    reviews, split its reviews at random into two halves and build a profile from each. A good formula should
    rate a wine's own other half as much closer than a random wine.

    Per formula: the average similarity of **random pairs** (floor), of **the same wine's two halves**
    (ceiling), how often the own half beats a random wine, and how often it is in the top 10 of about 2,000
    (chance would be 0.5 %).
    """)
    return


@app.cell
def _(con, coverage, np, pd):
    rich_groups = coverage.loc[coverage.n_reviews >= 10, ["group_id"]]
    con.register("rich_groups", rich_groups)
    half_reviews = con.sql("""
        select r.review_id, g.group_id
        from customer_reviews r join grp g using (sku)
        where r.language = 'fr' and g.group_id in (select group_id from rich_groups)
    """).df()
    half_hits = con.sql("""
        select distinct t.review_id, coalesce(m.canonical, t.word) as word
        from (
          select r.review_id, unnest(regexp_extract_all(lower(r.content), '[a-zàâäçéèêëîïôöûùüœ]+')) as word
          from customer_reviews r join grp g using (sku)
          where r.language = 'fr' and g.group_id in (select group_id from rich_groups)
        ) t
        left join variant_map m on m.variant = t.word
        join vocab v on v.word = coalesce(m.canonical, t.word) and v.category = 'taste'
    """).df()

    _rng = np.random.default_rng(0)
    half_reviews["half"] = half_reviews.groupby("group_id").review_id.transform(
        lambda s: _rng.permutation(len(s)) % 2
    )
    _hits = half_hits.merge(half_reviews, on="review_id")
    _counts = _hits.groupby(["group_id", "half", "word"]).size().unstack("word", fill_value=0)
    _sizes = half_reviews.groupby(["group_id", "half"]).size()
    _idx = pd.MultiIndex.from_product([sorted(half_reviews.group_id.unique()), [0, 1]], names=["group_id", "half"])
    _share = _counts.reindex(_idx, fill_value=0).div(_sizes.reindex(_idx), axis=0)
    half_a, half_b = _share.xs(0, level="half"), _share.xs(1, level="half")
    # a profile with no taste word at all cannot be compared
    _ok = (half_a.sum(axis=1) > 0) & (half_b.sum(axis=1) > 0)
    n_groups_dropped = int((~_ok).sum())
    half_a, half_b = half_a[_ok], half_b[_ok]
    pd.Series({"groups compared": len(half_a), "dropped (a half has no taste word)": n_groups_dropped, "taste words": half_a.shape[1]})
    return half_a, half_b


@app.cell
def _(half_a, half_b, mo, np, pd, profile_long):
    common_words = (
        profile_long[profile_long.category == "taste"].groupby("word").group_id.nunique().nlargest(15).index.tolist()
    )


    def _cosine(a, b):
        a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
        b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
        return a @ b.T


    def _top8(df):
        m = df.to_numpy()
        out = np.zeros_like(m)
        np.put_along_axis(out, np.argsort(-m, axis=1)[:, :8], 1.0, axis=1)
        return out * (m > 0)


    def _score(sim):
        n = len(sim)
        diag = np.diag(sim)[:, None]
        off = ~np.eye(n, dtype=bool)
        ties = ((sim == diag) & off).sum(axis=1)
        beats = ((sim < diag) & off).sum(axis=1) + 0.5 * ties
        rank = ((sim > diag) & off).sum(axis=1) + 0.5 * ties
        return {
            "random pair (floor)": sim[off].mean(),
            "same wine, other half (ceiling)": diag.mean(),
            "own half beats a random wine": (beats / (n - 1)).mean(),
            "own half in top 10": (rank < 10).mean(),
        }


    _A, _B = half_a.to_numpy(), half_b.to_numpy()
    _keep = ~half_a.columns.isin(common_words)
    _sims = {
        "top-8 overlap": _top8(half_a) @ _top8(half_b).T,
        "cosine, all words": _cosine(_A, _B),
        "cosine, 15 most common words removed": _cosine(_A[:, _keep], _B[:, _keep]),
    }
    formula_results = pd.DataFrame({k: _score(v) for k, v in _sims.items()}).T.round(3)
    mo.vstack([formula_results, mo.md("Removed in the third formula: " + ", ".join(common_words))])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Not done yet

    - **Employee picks are not in the profiles.** Everything above is built from customer reviews only
      (`customer_reviews`, French). Picks (`employee_picks`, 3,497 groups, longer and more taste-heavy text) were
      deliberately left out of this first pass and should be added as a second source later.
    - Vocabulary groups not profiled: `ageing`, `appearance`, `price_value`, `praise`, `criticism`, `other`.
    - English reviews (about 10 %) are not used.
    - Spelling variants are folded with a hand-written list only; unlisted forms and typos are missed.
    """)
    return


if __name__ == "__main__":
    app.run()
