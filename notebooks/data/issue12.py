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

    return DATA_DIR, duckdb, mo, pd, re


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Issue 12: Evaluation, how do we judge an embedding

    **Wayfinder ticket:** *Evaluation: how do we judge an embedding* (map #8).

    Grilling so far: reviews and employee picks look like the best description of taste in the data, so
    the evaluation should be able to use them as an answer key without removing them from training.
    Before deciding, this notebook records what the text really contains: size, topics, how many wines it
    can describe, and which wines it describes. Numbers are from the 2026-10-15 snapshot, `npc` groups.

    Caveat: the taste-word list in section 2 is a first draft and has not been checked by reading reviews.
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
    ## 1. Size, length and language

    Reviews are short (median about 80 characters). Picks are twice as long and written by 1,502 SAQ employees.
    """)
    return


@app.cell
def _(con, mo):
    reviews_by_lang = con.sql("""
        select language, count(*) as n, median(length(content)) as median_len,
          quantile_cont(length(content), 0.1) as p10_len, quantile_cont(length(content), 0.9) as p90_len,
          count(*) filter (where length(content) < 40) as under_40_chars
        from customer_reviews group by 1
    """).df()
    picks_size = con.sql("""
        select count(*) as n, count(distinct employee_id) as employees, count(distinct sku) as skus,
          median(length(content)) as median_len,
          quantile_cont(length(content), 0.1) as p10_len, quantile_cont(length(content), 0.9) as p90_len
        from employee_picks
    """).df()
    rating_dist = con.sql("select rating, count(*) as n from customer_reviews group by 1 order by 1").df()
    mo.vstack([reviews_by_lang, picks_size, rating_dist])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. What the text talks about

    Share of texts that match each theme (French reviews only, lowercased regex). **Taste** is the draft
    word list: fruit and flavour words, texture, acidity, sweetness, structure. **Price**, **occasion** and
    **praise** are the noise we would need to filter out. Reviews mention taste in a minority of cases;
    picks mostly do. Longer reviews are more likely to describe taste.
    """)
    return


@app.cell
def _(con, pd, re):
    THEMES = {
        "taste": r"fruit|fruité|cerise|cassis|framboise|fraise|mûre|pomme|agrume|citron|pêche|épic|poivr|vanill|boisé|tannin|acid|fraîch|frais|sec\b|doux|moelleux|rond|souple|corsé|puissan|léger|structur|long|finale|bouche|nez|arôme|arome|minéral|floral|miel|réglisse|torréf|fumé|chêne|vif|équilibr|onctu|velout|charnu|ample|astringen",
        "price": r"rapport qualit|prix|pas cher|abordable|bon marché|\$|aubaine|économique",
        "occasion/pairing": r"apéro|repas|accompagn|viande|poisson|fromage|bbq|barbecue|pâtes|pizza|grill|fête|cadeau|soirée|souper|dessert|plat",
        "generic praise": r"excellent|très bon|bon vin|super|délicieux|j'adore|j.aime|recommand|coup de c|parfait|meilleur|magnifique",
        "negative": r"déce|déçu|mauvais|bouchon|trop acide|trop sucré|aigre|pas aimé|bof|fade|oxyd",
    }
    fr_reviews = [r[0] for r in con.sql("select lower(content) from customer_reviews where language = 'fr'").fetchall()]
    pick_texts = [r[0] for r in con.sql("select lower(content) from employee_picks").fetchall()]


    def theme_shares(texts):
        return {k: sum(1 for t in texts if re.search(p, t)) / len(texts) for k, p in THEMES.items()}


    theme_table = pd.DataFrame({"reviews (fr)": theme_shares(fr_reviews), "picks": theme_shares(pick_texts)}).round(2)
    theme_table
    return THEMES, fr_reviews


@app.cell
def _(THEMES, fr_reviews, pd, re):
    _rx = re.compile(THEMES["taste"])
    _bins = [(0, 40), (40, 100), (100, 250), (250, 100000)]
    taste_by_length = pd.DataFrame(
        [
            {
                "chars": f"{lo}-{hi}" if hi < 100000 else f"{lo}+",
                "n_reviews": len(_s := [t for t in fr_reviews if lo <= len(t) < hi]),
                "share_with_taste_word": round(sum(1 for t in _s if _rx.search(t)) / len(_s), 2),
            }
            for lo, hi in _bins
        ]
    )
    taste_by_length
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. How many wines can get a taste profile

    Per `npc` group, counting reviews and picks that contain a taste word. A stable profile needs several
    such texts, so the usable set is about 2,700 to 4,100 groups, far fewer than the 9,163 with any review.
    """)
    return


@app.cell
def _(THEMES, con):
    con.sql(f"""
        create or replace temp table txt as
        select g.group_id, 'review' as src, regexp_matches(lower(content), '{THEMES["taste"]}') as has_taste
        from customer_reviews r join grp g using (sku)
        union all
        select g.group_id, 'pick', regexp_matches(lower(content), '{THEMES["taste"]}')
        from employee_picks p join grp g using (sku)
    """)
    con.sql("""
        create or replace temp table group_text as
        select group_id,
          count(*) filter (where src = 'review') as n_rev,
          count(*) filter (where src = 'review' and has_taste) as n_rev_taste,
          count(*) filter (where src = 'pick') as n_pick,
          count(*) filter (where src = 'pick' and has_taste) as n_pick_taste
        from txt group by 1
    """)
    coverage = con.sql("""
        select count(*) as groups_with_any_text,
          count(*) filter (where n_rev > 0) as any_review,
          count(*) filter (where n_pick > 0) as any_pick,
          count(*) filter (where n_rev > 0 and n_pick > 0) as review_and_pick,
          count(*) filter (where n_rev_taste + n_pick_taste >= 1) as taste_texts_1plus,
          count(*) filter (where n_rev_taste + n_pick_taste >= 3) as taste_texts_3plus,
          count(*) filter (where n_rev_taste + n_pick_taste >= 5) as taste_texts_5plus,
          count(*) filter (where n_rev_taste + n_pick_taste >= 10) as taste_texts_10plus
        from group_text
    """).df()
    coverage
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Which wines the text describes

    Groups split by how much taste-bearing text they have. Wines with no text at all (40% of groups) have a
    median price near $99 and almost no tasting traits or `taste_tag`. The wines that have text are the
    cheaper, popular ones. Every candidate answer key (reviews, picks, `taste_tag`, tasting traits) covers
    the same slice, so an exam built on them says little about expensive wines. Report results by price band.
    """)
    return


@app.cell
def _(con, mo):
    text_skew = con.sql("""
        with w as (
          select g.group_id, median(price) as price,
            bool_or(body_level is not null or acidity_level is not null) as has_trait,
            bool_or(taste_tag is not null) as has_tag,
            any_value(color) as color
          from wines x join grp g using (sku) group by 1
        )
        select case when coalesce(n_rev_taste + n_pick_taste, 0) >= 3 then '3+ taste texts'
                    when coalesce(n_rev + n_pick, 0) > 0 then '1-2 texts or none about taste'
                    else 'no text' end as text_class,
          count(*) as n_groups, round(median(price), 1) as median_price,
          round(avg(has_trait::int), 2) as share_with_tasting_traits,
          round(avg(has_tag::int), 2) as share_with_taste_tag,
          round(avg((color = 'Rouge')::int), 2) as share_red
        from w left join group_text using (group_id) group by 1 order by 1
    """).df()
    taste_tag_values = con.sql("select taste_tag, count(*) as n_skus from wines group by 1 order by 2 desc").df()
    mo.vstack([text_skew, taste_tag_values])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. What this means for the ticket

    - Reviews are mostly not about taste (about 58% of French reviews have no taste word); picks are cleaner (84% have one).
    - Price, occasion and pairing talk has to be filtered or neighbours get matched on "good for an apéro".
    - A taste profile per wine needs several taste-bearing texts: about 2,700 to 4,100 groups qualify.
    - 40% of groups have no text and are expensive. Any text-based exam must be reported by price band.
    - `taste_tag` has 10 values and covers about 20% of SKUs: a coarse label, useful only to separate very different wines.

    Open: check the word list against about 50 hand-read reviews; read the English reviews.
    """)
    return


@app.cell
def _(con):
    banned_words = [
        # articles and prepositions
        "de", "un", "une", "des", "du", "le", "la", "les", "au", "aux", "en", "dans", "sur", "par", "pour", "avec", "sans",
        # conjunctions and pronouns
        "et", "ou", "mais", "ce", "cette", "ces", "je", "il", "on", "nous", "qui", "que", "ça", "se", "y", "si", "ne", "pas",
        # verbs "être" and "avoir"
        "est", "a", "ai", "à", "fait",
        # apostrophe fragments (l', j', d', c', s', n', qu')
        "l", "j", "d", "c", "s", "n", "qu",
        # very generic
        "très", "bien", "plus", "vin", "trop", "bon",
        # unrelated to taste
        "prix",
        # english words (about 10 % of reviews)
        "the", "and", "wine", "it", "this", "i", "with", "to", "of",
        # more function words
        "tout", "peu", "mon", "comme", "vous", "son", "même", "été", "mes",
        # praise and price
        "excellent", "qualité", "belle", "rapport", "parfait", "aime", "recommande",
        # more function words
        "tous", "toujours", "être", "moi", "m", "ma", "me", "aussi", "assez", "peut", "avons", "suis", "était", "moins",
        "sa", "celui", "sont", "juste",
        # more praise
        "vraiment", "beaucoup", "agréable", "adore", "délicieux", "bonne", "super", "beau", "meilleur", "aimé",
        # colour and grape (already in the catalog fields)
        "blanc", "rouge", "rosé", "pinot",
    ]

    review_word_counts = con.sql("""
        select word, count(*) as n_uses, count(distinct review_id) as n_reviews
        from (
          select review_id,
            unnest(regexp_extract_all(lower(content), '[a-zàâäçéèêëîïôöûùüœ]+')) as word
          from customer_reviews
          where language = 'fr'
        )
        where not list_contains(?, word)
        group by word
        order by n_uses desc
        limit 100
    """, params=[banned_words]).df()
    review_word_counts
    return


@app.cell
def _():
    return


@app.cell
def _():
    from stop_words import get_stop_words

    french_stop_words = get_stop_words("french")
    len(french_stop_words)
    return (french_stop_words,)


@app.cell
def _(con, pd):
    # Spelling variants of the same word (accent, plural, gender) mapped to one form before counting.
    # Different words are NOT merged: sucre/sucré, beurre/beurré, fondue/fondus, oranges/orange, mûres/mûrs.
    spelling_variants = {
        "fraicheur": "fraîcheur",
        "tannins": "tanins",
        "aromes": "arômes",
        "gout": "goût",
        "rosés": "rosé",
        "rose": "rosé",
        "pinots": "pinot",
        "blancs": "blanc",
        "blanches": "blanc",
        "rouges": "rouge",
        "américains": "américain",
        "vignobles": "vignoble",
        "minérale": "minéral",
        "vins": "vin",
        "secs": "sec",
        "pêches": "pêche",
        "pommes": "pomme",
        "sushis": "sushi",
        "belle": "beau",
        "belles": "beau",
        "beaux": "beau",
        "bel": "beau",
        "producteurs": "producteur",
        "fraises": "fraise",
        "framboises": "framboise",
        "espagnols": "espagnol",
        "cerises": "cerise",
        "carafé": "carafe",
        "carafer": "carafe",
        "millésimes": "millésime",
        "charnus": "charnu",
        "viandes": "viande",
        "vertes": "verte",
        "complexes": "complexe",
        "poires": "poire",
        "cépages": "cépage",
        "grands": "grand",
        "poissons": "poisson",
        "fines": "fin",
        "fins": "fin",
        "boisées": "boisé",
        "boisée": "boisé",
        "florales": "floral",
        "ronde": "rond",
        "charcuteries": "charcuterie",
        "années": "année",
        "petits": "petit",
        "prunes": "prune",
        "intenses": "intense",
        "courte": "court",
        "confits": "confit",
        "épicée": "épicé",
        "épicées": "épicé",
        "florale": "floral",
        "fraîche": "frais",
        "légère": "léger",
        "agrume": "agrumes",
    }
    variant_map = pd.DataFrame(list(spelling_variants.items()), columns=["variant", "canonical"])
    con.register("variant_map", variant_map)
    len(spelling_variants)
    return


@app.cell
def _(con, french_stop_words):
    # Option 2, second try: only wines with 10+ French reviews, so "used for every wine" becomes measurable.
    # For each word: share of a wine's reviews that contain it, then how much that share varies from wine to wine.
    # dispersion = variance / what pure chance would give. About 1 = same rate everywhere (filler),
    # well above 1 = some wines are described with the word and others are not (candidate taste word).
    word_spread = con.sql("""
        with fr as (
          select r.review_id, g.group_id, lower(r.content) as text
          from customer_reviews r join grp g using (sku)
          where r.language = 'fr'
        ),
        big as (
          select group_id, count(*) as n_rev from fr group by group_id having count(*) >= 10
        ),
        tokens as (
          select distinct review_id, group_id, word
          from (
            select f.review_id, f.group_id,
              unnest(regexp_extract_all(f.text, '[a-zàâäçéèêëîïôöûùüœ]+')) as word
            from fr f join big using (group_id)
          )
        ),
        kept as (
          select distinct t.review_id, t.group_id, coalesce(m.canonical, t.word) as word
          from tokens t left join variant_map m on m.variant = t.word
          where not list_contains(?, t.word)
        ),
        group_word as (
          select k.word, k.group_id, count(*) * 1.0 / b.n_rev as share
          from kept k join big b using (group_id)
          group by k.word, k.group_id, b.n_rev
        ),
        totals as (select count(*) as n_groups, avg(n_rev) as avg_n_rev from big)
        select word,
          count(*) as n_groups_using,
          round(sum(share) / n_groups, 3) as mean_share,
          round(sqrt(sum(share * share) / n_groups - power(sum(share) / n_groups, 2)), 3) as std_share,
          round((sum(share * share) / n_groups - power(sum(share) / n_groups, 2))
                / ((sum(share) / n_groups) * (1 - sum(share) / n_groups) / avg_n_rev), 2) as dispersion
        from group_word, totals
        group by word, n_groups, avg_n_rev
        having sum(share) / n_groups >= 0.001 and count(*) >= 20
        order by dispersion desc
        limit 500
    """, params=[french_stop_words]).df()
    word_spread
    return


if __name__ == "__main__":
    app.run()
