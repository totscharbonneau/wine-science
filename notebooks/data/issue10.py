import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import duckdb
    import matplotlib.pyplot as plt
    import pandas as pd
    from src import DATA_DIR

    return DATA_DIR, duckdb, mo, pd, plt


@app.cell
def _(plt):
    # Palette slots from the dataviz reference: blue / orange for the series, neutral grey for baselines.
    BLUE, ORANGE, GREY, INK = "#2a78d6", "#eb6834", "#9a9992", "#6b6a66"


    def new_axes(title, width=7, height=3.2, ncols=1):
        """Transparent figure with the recessive axes used by every chart here."""
        fig, axes = plt.subplots(1, ncols, figsize=(width, height))
        for ax in (axes if ncols > 1 else [axes]):
            ax.set_title(title if ncols == 1 else "", loc="left", fontsize=11, color=INK)
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(GREY)
            ax.tick_params(colors=INK, length=0)
            ax.set_facecolor("none")
        fig.patch.set_alpha(0)
        return fig, axes

    return BLUE, GREY, INK, ORANGE, new_axes


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Can pseudo-user reviews and employee picks supply a training signal?

    **Wayfinder ticket:** *Explore pseudo-user co-reviews and employee picks as signal*
    **Snapshot:** SAQ scrape of 2026-10-15, `npc` wine groups (one vector per group).

    The embedding is meant to encode *what a wine is*. One way to teach it that is behaviour:
    wines that the same people review, or that the same SAQ employee picks, should end up close.
    There are no real user ids, so a **pseudo-user** is a review author ("Michel B." = first name
    plus initial) and a **picker** is an employee id.

    This notebook asks four things, in order:

    1. Who are the pseudo-users, and can we trust them as people?
    2. How many wine groups end up with a usable neighbour?
    3. Is the signal biased towards a particular kind of wine?
    4. Does it say anything about taste: do co-reviewed wines look alike?

    A **neighbour** of a wine group is another group that shares at least `m` users with it.
    Users who touched a single group give no link, and users with more than 200 groups are
    dropped as too generic to say anything about one wine.
    """)
    return


@app.cell
def _(DATA_DIR, duckdb):
    con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
    con.sql("""create temp view g as
        select * from read_parquet('data/processed/wine_groups_npc.parquet')""")

    # one row per (user, wine group): who reviewed it, who picked it
    con.sql("""create temp table rv as
        select distinct r.author as user_id, g.group_id
        from customer_reviews r join g using (sku) where r.author is not null""")
    con.sql("""create temp table pk as
        select distinct p.employee_id as user_id, g.group_id
        from employee_picks p join g using (sku) where p.employee_id is not null""")

    # one row per wine group, with the traits we will compare neighbours on
    con.sql("""create temp table attr as
        select g.group_id, any_value(w.color) color, any_value(w.country) country,
               any_value(w.taste_tag) taste_tag
        from wines w join g using (sku) group by 1""")
    return (con,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Who are the pseudo-users?

    Authors are the first name plus an initial, so several real people can share one name.
    We cannot prove a merge, but a few signs hint at it: an author with hundreds of groups, many
    reviews on one day, or posts in both languages.
    """)
    return


@app.cell
def _(con):
    authors_by_size = con.sql("""
        with a as (select user_id, count(*) n from rv group by 1)
        select case when n = 1 then '1 group' when n <= 4 then '2-4' when n <= 19 then '5-19'
                    when n <= 99 then '20-99' else '100+' end as groups_reviewed,
               count(*) as authors, sum(n) as author_group_pairs
        from a group by 1 order by min(n)""").df()
    authors_by_size
    return (authors_by_size,)


@app.cell
def _(BLUE, INK, authors_by_size, new_axes):
    _fig, _ax = new_axes("Authors by number of wine groups reviewed")
    _bars = _ax.barh(authors_by_size.groups_reviewed, authors_by_size.authors, color=BLUE, height=0.6)
    _ax.invert_yaxis()
    _ax.set_xticks([])
    _ax.spines["bottom"].set_visible(False)
    for _bar, _n in zip(_bars, authors_by_size.authors):
        _ax.text(_bar.get_width(), _bar.get_y() + _bar.get_height() / 2, f"  {_n:,}", va="center", color=INK, fontsize=9)
    _ax.set_xlim(0, authors_by_size.authors.max() * 1.15)
    _fig.tight_layout()
    _fig
    return


@app.cell
def _(con):
    top_authors = con.sql("""
        select author, count(distinct group_id) as n_groups, count(*) as reviews,
               count(distinct review_date) as n_days,
               min(review_date) as first_review, max(review_date) as last_review
        from customer_reviews r join g using (sku)
        group by 1 order by n_groups desc limit 8""").df()
    top_authors
    return


@app.cell
def _(con):
    suspicious = con.sql("""
        select
          (select count(distinct author) from (
              select author, review_date, count(*) n from customer_reviews
              where not is_bulk_import_date group by 1, 2 having n >= 10)) as authors_10plus_reviews_in_a_day,
          (select count(*) from (select author from customer_reviews
              group by 1 having count(distinct language) > 1)) as authors_in_both_languages,
          (select count(distinct employee_id) from employee_picks) as employee_ids,
          (select count(distinct employee_name) from employee_picks) as employee_names""").df()
    suspicious
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading it.** Roughly half of the authors reviewed a single group, so they link nothing.
    A tail of heavy reviewers exists (the top one covers hundreds of groups over six years):
    plausible for one enthusiast, or for several people who share a name. Employee ids are
    cleaner (1,502 ids; 253 of them span more than one store), but 1,290 distinct names against
    1,502 ids means ids and names do not map one to one, and this was not checked further.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. How many wine groups get a neighbour?

    For each source and each threshold `m`, count the groups that have at least one neighbour,
    and how many neighbour pairs that gives.
    """)
    return


@app.cell
def _(con, pd):
    def pairs_cte(tab, min_shared, max_groups=200):
        """SQL CTE `p(g1, g2)`: group pairs sharing at least `min_shared` users."""
        return f"""with u as (select user_id from {tab} group by 1
                             having count(*) between 2 and {max_groups}),
            e as (select t.user_id, t.group_id from {tab} t join u using (user_id)),
            p as (select a.group_id g1, b.group_id g2 from e a join e b
                  on a.user_id = b.user_id and a.group_id < b.group_id
                  group by 1, 2 having count(*) >= {min_shared})"""

    def neighbour_coverage(tab, min_shared):
        return con.sql(pairs_cte(tab, min_shared) + f"""
            select (select count(distinct group_id) from {tab}) as groups_with_signal,
                   count(distinct gid) as groups_with_neighbour,
                   (select count(*) from p) as neighbour_pairs
            from (select g1 as gid from p union all select g2 from p)""").df()

    coverage = pd.concat(
        [neighbour_coverage(tab, m).assign(source=name, min_shared_users=m)
         for name, tab in [("reviews", "rv"), ("picks", "pk")] for m in (1, 2, 3)],
        ignore_index=True,
    )[["source", "min_shared_users", "groups_with_signal", "groups_with_neighbour", "neighbour_pairs"]]
    total_groups = con.sql("select count(distinct group_id) from g").fetchone()[0]
    coverage.assign(share_of_all_groups=(coverage.groups_with_neighbour / total_groups).round(3))
    return coverage, pairs_cte, total_groups


@app.cell
def _(BLUE, GREY, INK, ORANGE, coverage, new_axes, total_groups):
    _fig, _ax = new_axes("Share of all wine groups with at least one neighbour", width=7, height=3.6)
    _cats = [1, 2, 3]
    _w = 0.36
    for _i, (_src, _color, _label) in enumerate([("reviews", BLUE, "reviews"), ("picks", ORANGE, "employee picks")]):
        _rows = coverage[coverage.source == _src].sort_values("min_shared_users")
        _share = _rows.groups_with_neighbour.to_numpy() / total_groups * 100
        _x = [c + (_i - 0.5) * _w for c in _cats]
        _bars = _ax.bar(_x, _share, width=_w - 0.04, color=_color, label=_label)
        for _b, _s in zip(_bars, _share):
            _ax.text(_b.get_x() + _b.get_width() / 2, _b.get_height() + 0.8, f"{_s:.0f}%", ha="center", color=INK, fontsize=9)
    _ax.set_xticks(_cats, ["share 1+ user", "share 2+ users", "share 3+ users"])
    _ax.set_yticks([])
    _ax.spines["bottom"].set_color(GREY)
    _ax.set_ylim(0, 65)
    _ax.legend(frameon=False, labelcolor=INK, loc="upper right")
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading it.** Requiring only one shared reviewer gives almost every reviewed group a
    neighbour, but that is a loose link. Asking for 2 or 3 shared reviewers, a better guarantee
    that the link is not a coincidence, roughly halves and then quarters the coverage. Employee
    picks collapse faster: they are sparse, so strong links (2+ shared employees) reach only a
    few hundred groups.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Which wines carry the signal?

    If the wines with behaviour are a particular kind of wine, an embedding trained on it may
    learn that kind of wine instead of taste.
    """)
    return


@app.cell
def _(con):
    signal_profile = con.sql("""
        with grp as (
            select g.group_id, bool_or(w.in_stock) in_stock, median(w.price) price
            from wines w join g using (sku) group by 1),
        f as (select grp.*, group_id in (select group_id from rv) as has_reviews,
                            group_id in (select group_id from pk) as has_picks from grp)
        select has_reviews, has_picks, count(*) as n_groups,
               round(avg(in_stock::int), 2) as share_in_stock,
               round(median(price), 1) as median_price_cad
        from f group by 1, 2 order by 1, 2""").df()
    signal_profile
    return (signal_profile,)


@app.cell
def _(BLUE, INK, new_axes, signal_profile):
    _labels = [f"{'reviews' if r else 'no reviews'},\n{'picks' if p else 'no picks'}"
               for r, p in zip(signal_profile.has_reviews, signal_profile.has_picks)]
    _fig, _axes = new_axes("", width=9, height=3.4, ncols=2)
    for _ax, _col, _title, _fmt in [
        (_axes[0], "median_price_cad", "Median price (CAD)", "${:.0f}"),
        (_axes[1], "share_in_stock", "Share of groups in stock", "{:.0%}"),
    ]:
        _bars = _ax.bar(_labels, signal_profile[_col], color=BLUE, width=0.6)
        _ax.set_title(_title, loc="left", fontsize=11, color=INK)
        _ax.set_yticks([])
        _ax.tick_params(axis="x", labelsize=8)
        for _b, _v in zip(_bars, signal_profile[_col]):
            _ax.text(_b.get_x() + _b.get_width() / 2, _b.get_height(), _fmt.format(_v), ha="center", va="bottom", color=INK, fontsize=9)
        _ax.set_ylim(0, signal_profile[_col].max() * 1.15)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading it.**

    - **Price is the clear skew.** Wines with no review have a median price around $99, three to
      four times the $24 to $31 of wines that have reviews. The signal comes from the cheaper,
      more mainstream part of the catalog.
    - **Stock is not driven by reviews.** 16% of unreviewed groups are in stock against 14% of
      reviewed-but-unpicked ones. Only groups with both reviews and picks stand out (44% in stock),
      so the employee-pick signal sits on the wines that are on the shelf.
    - So "has behavioural signal" tracks *cheaper and mainstream*, and for picks also *on the
      shelf*. An embedding enriched with behaviour risks encoding a price tier. This feeds the
      later ticket on rich versus catalog-only vectors.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Does the signal say anything about taste?

    The test: take pairs of wine groups that share users, and compare how often they match on
    **color**, **country** and SAQ's **taste tag** with how often *random* pairs match. If shared
    users really pick similar wines, linked pairs should match more often than random ones.

    The random baseline is a seeded sample of 3,000 reviewed groups, so the comparison is against
    other reviewed wines and not against the whole catalog.
    """)
    return


@app.cell
def _(con, pairs_cte, pd):
    TRAITS = """count(*) as n_pairs,
        avg((a.color = b.color)::int) as same_color,
        avg((a.country = b.country)::int) as same_country,
        avg((a.taste_tag = b.taste_tag)::int) as same_taste_tag"""
    FROM_PAIRS = """from {src} x join attr a on a.group_id = x.g1 join attr b on b.group_id = x.g2
        where a.taste_tag is not null and b.taste_tag is not null"""

    def linked_pairs(label, tab, min_shared, max_groups=200):
        row = con.sql(pairs_cte(tab, min_shared, max_groups)
                      + "select " + TRAITS + " " + FROM_PAIRS.format(src="p")).df()
        return row.assign(pairs=label)

    baseline = con.sql("""
        with s as (select distinct group_id from rv using sample reservoir(3000 rows) repeatable (0))
        select """ + TRAITS + """ from (
            select s1.group_id g1, s2.group_id g2 from s s1, s s2 where s1.group_id < s2.group_id) x
        join attr a on a.group_id = x.g1 join attr b on b.group_id = x.g2
        where a.taste_tag is not null and b.taste_tag is not null""").df().assign(pairs="random pairs (baseline)")

    lift = pd.concat([
        baseline,
        linked_pairs("reviews: share 1+ author", "rv", 1),
        linked_pairs("reviews: share 2+ authors", "rv", 2),
        linked_pairs("reviews: share 3+ authors", "rv", 3),
        linked_pairs("reviews: 2+ authors, authors with <=30 groups", "rv", 2, 30),
        linked_pairs("picks: share 1+ employee", "pk", 1),
        linked_pairs("picks: share 2+ employees", "pk", 2),
    ], ignore_index=True).set_index("pairs").round(3)
    lift
    return (lift,)


@app.cell
def _(BLUE, GREY, INK, ORANGE, lift, new_axes):
    _traits = [("same_color", "same color"), ("same_country", "same country"), ("same_taste_tag", "same taste tag")]
    _series = [
        ("random pairs (baseline)", GREY, "random pairs"),
        ("reviews: share 3+ authors", BLUE, "share 3+ reviewers"),
        ("picks: share 2+ employees", ORANGE, "share 2+ employees"),
    ]
    _fig, _ax = new_axes("How often two wine groups match, by how they are linked", width=8, height=3.8)
    _w = 0.26
    for _i, (_key, _color, _label) in enumerate(_series):
        _vals = [lift.loc[_key, t] for t, _ in _traits]
        _x = [j + (_i - 1) * _w for j in range(len(_traits))]
        _bars = _ax.bar(_x, _vals, width=_w - 0.03, color=_color, label=_label)
        for _b, _v in zip(_bars, _vals):
            _ax.text(_b.get_x() + _b.get_width() / 2, _b.get_height() + 0.008, f"{_v:.2f}", ha="center", color=INK, fontsize=9)
    _ax.set_xticks(range(len(_traits)), [name for _, name in _traits])
    _ax.set_yticks([])
    _ax.set_ylim(0, 0.62)
    _ax.legend(frameon=False, labelcolor=INK, loc="upper right", ncols=3, bbox_to_anchor=(1, 1.02))
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading it.**

    - Co-reviewed pairs are only a hair above random: same color 0.48 to about 0.53, same country
      0.17 to 0.18, same taste tag 0.16 to 0.18. More shared reviewers helps a little for color and
      barely for the rest.
    - Part of even that small lift is probably popularity: popular wines get reviewed by everyone,
      so they pair with each other far more than their taste would explain. This test does not
      remove that effect.
    - Employee picks show a clearer lift on country (0.17 to 0.21-0.23) and taste tag (0.16 to
      0.20-0.22), but the strong version (2+ shared employees) rests on about 2,500 pairs.
    - Matching on color, country and taste tag is a crude proxy for taste, so a flat result here
      is evidence of a weak signal, not proof of none.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Verdict (proposed, for the user to confirm)

    - **Reviews as supervision:** weak. Authors are noisy pseudo-users, 41% of groups have no
      review, and linked pairs barely beat random on the traits we can check.
    - **Employee picks as supervision:** the more credible of the two behavioural signals
      (stable ids, clearer lift), but it reaches few groups, so at best an optional extra.
    - **Review and pick *text*** is a separate question: it may describe taste well and belongs to
      the text-features ticket, not to this one.
    - **Price skew** is real (behaviour sits on cheaper, mainstream wines; picks also on in-stock
      wines) and has to be handled in the rich-versus-catalog-only ticket.

    **Not tested here:** whether the co-review graph helps once popularity is controlled for,
    and whether review *content* (not just who wrote it) agrees between neighbours.
    """)
    return


if __name__ == "__main__":
    app.run()
