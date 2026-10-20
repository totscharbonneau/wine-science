import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import marimo as mo
    import duckdb
    import pandas as pd
    from src import DATA_DIR
    from src.data.group_wines import NPC_KEY, GRAPE_LEAD

    return DATA_DIR, GRAPE_LEAD, NPC_KEY, duckdb, json, mo, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Issue #7: some npc keys hold unrelated wines under one name

    An **npc key** is normalized name + producer + color. `npcg` adds the lead grape, which
    separates a few keys that hold different wines, but only as a side effect of their lead
    grapes differing. This notebook traces the cases on the 2026-10-15 snapshot.
    """)
    return


@app.cell
def _(DATA_DIR, duckdb):
    con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
    return (con,)


@app.cell
def _(GRAPE_LEAD, NPC_KEY, con):
    def sku_table(source: str = "wines"):
        """One row per SKU, with the npc key, the lead grape npcg uses and the set of grapes
        (percentages dropped). desc_type is the wine type SAQ writes in the description
        ("Vin rouge", "Vin blanc", ...), to compare against `color`. `source` is a SQL table
        or subquery with the `wines` columns."""
        return con.sql(f"""
            SELECT sku, name, producer, color, price, volume_ml, region, appellation, grapes,
                regexp_extract(description, '^(Vin [a-zéè]+)', 1) AS desc_type,
                {NPC_KEY} AS npc_key,
                {GRAPE_LEAD} AS lead,
                list_sort(list_distinct(list_transform(string_split(coalesce(grapes, ''), ','),
                    x -> trim(lower(regexp_replace(x, '[0-9,. ]*%', '')))))) AS grape_set
            FROM {source}
        """).df()


    w = sku_table()
    w.shape
    return sku_table, w


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## 1. How big is it?
    """)
    return


@app.cell
def _(duckdb, mo, w):
    # Per npc key: how many SKUs, distinct lead grapes and distinct grape sets.
    keys = duckdb.sql("""
        SELECT npc_key, count(*) AS n_skus,
            count(DISTINCT lead) AS n_leads,
            count(DISTINCT grape_set) AS n_sets
        FROM w GROUP BY npc_key
    """).df()
    scale = {
        "npc keys": len(keys),
        "keys with 2+ SKUs": int((keys.n_skus > 1).sum()),
        "keys with 2+ lead grapes (npcg splits them)": int((keys.n_leads > 1).sum()),
        "keys with 2+ grape sets (npcg ignores those with one lead)": int((keys.n_sets > 1).sum()),
    }
    mo.ui.table([{"measure": k, "keys": v} for k, v in scale.items()], selection=None)
    return (keys,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Which of the 81 are really different wines?

    For every pair of SKUs under a key whose lead grapes differ, do their grape sets share at
    least one grape?

    - **A**: no differing pair shares a grape.
    - **B**: some pair shares none, others do.
    - **C**: all differing pairs overlap. A blend shift between vintages, same wine.
    """)
    return


@app.cell
def _(d, duckdb, mo, w):
    def classify_keys(d):
        """Class of every npc key whose SKUs have different, known lead grapes (A, B or C)."""
        pairs = duckdb.sql("""
            SELECT a.npc_key,
                len(list_intersect(a.grape_set, b.grape_set)) = 0 AS no_shared_grape
            FROM d a JOIN d b ON a.npc_key = b.npc_key AND a.sku < b.sku
            WHERE a.lead IS NOT NULL AND b.lead IS NOT NULL AND a.lead <> b.lead
        """).df()
        return (
            pairs.groupby("npc_key").no_shared_grape.agg(["all", "any"])
            .assign(cls=lambda t: t.apply(
                lambda r: "A: no pair shares a grape" if r["all"]
                else "B: some pair shares none" if r["any"]
                else "C: grape sets overlap (blend shift)", axis=1))
            .cls
        )


    key_class = classify_keys(w)
    mo.ui.table(key_class.value_counts().sort_index().rename_axis("class").reset_index(name="keys"), selection=None)
    return classify_keys, key_class


@app.cell
def _(key_class, keys, mo):
    # The 18 keys in A and B, with their SKU counts.
    disjoint_keys = (
        key_class[key_class.str.startswith(("A", "B"))].rename("class").reset_index()
        .merge(keys[["npc_key", "n_skus"]]).sort_values(["class", "n_skus"], ascending=[True, False])
    )
    mo.ui.table(disjoint_keys, selection=None)
    return


@app.cell
def _(mo, w):
    def show_case(title, note, *npc_keys):
        """The SKUs under the given npc keys, grape sets side by side, with a note on what is wrong."""
        cols = ["sku", "color", "desc_type", "volume_ml", "price", "appellation", "grapes", "npc_key"]
        rows = w[w.npc_key.isin(npc_keys)].sort_values(["npc_key", "grapes"])[cols]
        return mo.vstack([mo.md(f"### {title}\n\n{note}"), mo.ui.table(rows, selection=None, page_size=20)])

    return (show_case,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. The cases

    ### Group 1: SAQ's `color` or `grapes` is wrong on a SKU

    The wine is fine, the row is bad. No grouping key can fix this.
    """)
    return


@app.cell
def _(mo, show_case):
    mo.vstack([
        show_case(
            "Les Hauts de Smith (issue example)",
            "SAQ describes every row as `Vin rouge`, yet some are colored `Blanc`. The grapes are "
            "right (the `Sauvignon blanc 100 %` rows are the white wine); the `color` is swapped "
            "on four SKUs. There are two real wines, a red and a white, scrambled by `color`.",
            "les hauts de smith pessac-leognan|chateau smith haut lafite|blanc",
            "les hauts de smith pessac-leognan|chateau smith haut lafite|rouge",
        ),
        show_case(
            "Le Comte de Malartic (blanc)",
            "One white carries `Cabernet-sauvignon 55 %...`, the red's grapes.",
            "le comte de malartic pessac-leognan|famille a&m bonnie|blanc",
        ),
        show_case(
            "Chapoutier Les Granilites",
            "Two rows say `Vin blanc` in the description but are colored `Rouge`. One is Marsanne, "
            "a real white Saint-Joseph.",
            "m. chapoutier les granilites saint-joseph|m. chapoutier|rouge",
        ),
    ])
    return


@app.cell
def _(duckdb, mo, w):
    # How common is a color that contradicts the description's wine type?
    mismatch = duckdb.sql("""
        SELECT color, desc_type, count(*) AS skus FROM w
        WHERE (color = 'Rouge' AND desc_type <> 'Vin rouge')
           OR (color = 'Blanc' AND desc_type NOT IN ('Vin blanc', 'Vin mousseux'))
           OR (color = 'Rosé' AND desc_type NOT IN ('Vin rosé', 'Vin mousseux'))
        GROUP BY ALL ORDER BY skus DESC
    """).df()
    mo.vstack([mo.md("Color vs description type, mismatches only (an empty `desc_type` is a description that does not start with `Vin ...`):"), mo.ui.table(mismatch, selection=None)])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Group 2: truncated grape lists flip the lead of a single wine

    Here `npcg` splits one wine into several groups. This is the opposite error from the issue.
    """)
    return


@app.cell
def _(mo, show_case):
    mo.vstack([
        show_case(
            "Château d'Yquem",
            "`Sémillon 35 %` and `Sauvignon blanc 50 %` list one grape only, so the lead flips "
            "against the full `Sémillon 75 % / Sauvignon blanc 25 %`.",
            "chateau d'yquem y bordeaux|sa du chateau yquem|blanc",
        ),
        show_case(
            "Château Haut-Bailly",
            "`Cabernet-sauvignon 62 %` alone, against complete blends, and a `Merlot 100 %` row "
            "whose lead differs from all of them.",
            "chateau haut-bailly pessac-leognan|chateau haut bailly|rouge",
        ),
        show_case(
            "Luce della Vite",
            "`Merlot 55 %` and `Sangiovese 55 %` list one grape only, next to full 55/45 blends "
            "that lead with Merlot in some rows and Sangiovese in others, plus a 100 % Brunello row.",
            "luce della vite|luce della vite srl|rouge",
        ),
        show_case(
            "Domaine Zind-Humbrecht Pinot blanc",
            "`Pinot auxerrois 50 %` vs `Pinot blanc 50 %`: a tie, broken alphabetically, and each "
            "row lists only one half.",
            "domaine zind-humbrecht pinot blanc|domaine zind-humbrecht|blanc",
        ),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Group 3: a generic name covers genuinely different wines

    Grape set separates them; so would volume or price.
    """)
    return


@app.cell
def _(mo, show_case):
    mo.vstack([
        show_case(
            "Domaine des Tours, vin de pays",
            "A Grenache/Cinsault blend and a 100 % Merlot under one generic name.",
            "domaine des tours vin de pays|domaine des tours|rouge",
        ),
        show_case(
            "Athenais de Béru rosé",
            "Pinot gris 100 % and Pinot noir 100 %.",
            "athenais de beru bourgogne|athenais de beru|rose",
        ),
        show_case(
            "Domaine de Lavoie rosé",
            "Two different hybrid-grape cuvées, one a 250 ml can.",
            "domaine de lavoie|domaine de lavoie|rose",
        ),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Group 4: can't tell without outside knowledge

    Could be a mislisted grape on one SKU or two different cuvées.
    """)
    return


@app.cell
def _(mo, show_case):
    mo.vstack([
        show_case(
            "M. Chapoutier Barbe Rac and Croix de Bois (Châteauneuf-du-Pape)",
            "`Grenache 100 %` next to `Syrah 100 %` under the same cuvée name.",
            "m. chapoutier barbe rac|m. chapoutier|rouge",
            "m. chapoutier barbe rac chateauneuf-du-pape|m. chapoutier|rouge",
            "chapoutier chateauneuf-du-pape croix de bois|m. chapoutier|rouge",
        ),
        show_case(
            "Hummel Villányi Portugieser",
            "The name says Portugieser; one row lists `Blauer Zweigelt 100 %`.",
            "hummel villanyi portugieser|wiengut hummel|rouge",
        ),
        show_case(
            "Domaine Agisson Sancerre Équilibre",
            "`Sauvignac 100 %` (a 1500 ml row) against `Sauvignon blanc 100 %`.",
            "domaine agisson sancerre equilibre|domaine agisson|blanc",
        ),
        show_case(
            "Jean-Louis Chave Hermitage blanc",
            "Marsanne 100 %, Roussanne 80 % alone and Roussanne 80 % / Marsanne 20 %: truncated "
            "lists or different vintages' blends.",
            "jean-louis chave hermitage|domaine jean-louis chave|blanc",
        ),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. What this shows

    - 536 npc keys hold more than one grape set; `npcg` only acts on the 81 whose lead differs.
    - Of those 81, 63 are blend shifts (same wine, split on purpose), and 18 have SKUs that share no grape.
    - The 18 are not one problem: bad SAQ `color` / `grapes` data (group 1), truncated grape lists that make
      `npcg` split one wine (group 2), generic names covering several wines (group 3), and undecidable cases (group 4).
    - Appellation never differs inside a key with several leads; region differs in 2 keys only.
    - Re-fetching the 77 SKUs on 2026-10-20 (section 5): SAQ has fixed 6 of them since our scrape (5 `color`
      values and the Malartic grapes). 4 of the 18 keys stop being a problem; 14 remain, so most of
      the issue is not stale data.
    - The 380 keys `npcg` leaves together despite different grape sets (same lead) look like one wine each:
      80 have a low grape overlap (Jaccard < 0.34), and those are vintage blend shifts or truncated lists
      (Tignanello, Solaia, Latour...), not unrelated wines (section 6).

    **Open question**: flag suspect keys in the grouping report rather than add a new method. A key is
    suspect when its SKUs share no grape, or when `color` contradicts the description's wine type.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. What does SAQ's page say today?

    The grapes of Malartic SKU 15084024 in our scrape (`Cabernet-sauvignon 55 %...`) differ from
    what saq.com shows now (`Sauvignon blanc 78 %, Sémillon 22 %`). The scraper reads the same
    `strong[data-th="Cépage"]` element, so SAQ corrected the page after our 2026-10-01 fetch.

    To see how much of the issue is stale data, the product pages of the 77 SKUs in the 18
    keys were fetched again on 2026-10-20 (one request each, with the scraper's `get` and
    `parse_product`; nothing written to `saq.db`). Only `Cépage` and `Couleur` were kept, in
    `data/processed/issue7_live_check.json`.
    """)
    return


@app.cell
def _(DATA_DIR, json, pd):
    live = json.loads((DATA_DIR / "processed" / "issue7_live_check.json").read_text())
    # The build stores plain spaces; the live page has non-breaking ones ("78&nbsp;%").
    live_df = pd.DataFrame(
        [{"sku": sku, "grapes": (v["grapes"] or "").replace("\xa0", " ") or None, "color": v["color"]}
         for sku, v in live.items() if v["status"] == 200]
    )
    len(live), len(live_df)
    return (live_df,)


@app.cell
def _(duckdb, live_df, mo, sku_table, w):
    # The snapshot with the live color and grapes laid over the 77 re-fetched SKUs.
    LIVE_SOURCE = """(
        SELECT wines.* REPLACE (coalesce(l.grapes, wines.grapes) AS grapes, coalesce(l.color, wines.color) AS color)
        FROM wines LEFT JOIN live_df l USING (sku)
    )"""
    w_live = sku_table(LIVE_SOURCE)
    changed = duckdb.sql("""
        SELECT s.sku, s.name, s.color AS color_snapshot, n.color AS color_live,
            s.grapes AS grapes_snapshot, n.grapes AS grapes_live
        FROM w s JOIN w_live n USING (sku)
        WHERE s.sku IN (SELECT sku FROM live_df)
          AND (s.color IS DISTINCT FROM n.color OR s.grapes IS DISTINCT FROM n.grapes)
        ORDER BY s.name, s.sku
    """).df()
    mo.vstack([
        mo.md(f"**{len(changed)} of {len(live_df)} SKUs differ from the snapshot** "
              f"({len(live_df) - len(changed)} are unchanged):"),
        mo.ui.table(changed, selection=None),
    ])
    return (w_live,)


@app.cell
def _(classify_keys, key_class, mo, pd, w_live):
    live_class = classify_keys(w_live)
    before = key_class.value_counts().rename("snapshot")
    after = live_class.value_counts().rename("with live values")
    fixed = sorted(set(key_class[key_class.str.startswith(("A", "B"))].index)
                   - set(live_class[live_class.str.startswith(("A", "B"))].index))
    mo.vstack([
        mo.ui.table(pd.concat([before, after], axis=1).fillna(0).astype(int).sort_index()
                    .rename_axis("class").reset_index(), selection=None),
        mo.md("Keys no longer in A or B once the live values are used:\n\n" + "\n".join(f"- `{k}`" for k in fixed)),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. The keys `npcg` does not split: same lead, different grape sets

    536 keys hold more than one grape set; 81 of them differ in lead and are covered above. The
    rest share their lead grape, so `npcg` keeps them together even when they may be different
    wines (e.g. a 100 % Merlot next to a Merlot / Grenache blend). For each such key, the lowest
    Jaccard similarity between two SKUs' grape sets (1 = same grapes, 0 = nothing shared).
    Only SKUs with a known lead grape count.
    """)
    return


@app.cell
def _(duckdb, mo, pd, w):
    same_lead_pairs = duckdb.sql("""
        SELECT a.npc_key,
            len(list_intersect(a.grape_set, b.grape_set))
                / len(list_distinct(list_concat(a.grape_set, b.grape_set))) AS jaccard
        FROM w a JOIN w b ON a.npc_key = b.npc_key AND a.sku < b.sku
        WHERE a.lead IS NOT NULL AND a.lead = b.lead AND a.grape_set <> b.grape_set
    """).df()
    same_lead_keys = same_lead_pairs.groupby("npc_key").jaccard.min().rename("min_jaccard").reset_index()
    same_lead_keys["overlap"] = pd.cut(
        same_lead_keys.min_jaccard, [0, 0.34, 0.5, 0.67, 1], right=False,
        labels=["< 0.34", "0.34-0.49", "0.50-0.66", "0.67-0.99"],
    )
    mo.vstack([
        mo.md(f"**{len(same_lead_keys)} keys** share a lead grape but differ in grape set. Lowest overlap per key:"),
        mo.ui.table(same_lead_keys.overlap.value_counts().sort_index().rename_axis("min Jaccard").reset_index(name="keys"), selection=None),
    ])
    return (same_lead_keys,)


@app.cell
def _(duckdb, mo, same_lead_keys, w):
    # The keys with the lowest overlap (min Jaccard < 0.34), biggest first.
    low_keys = same_lead_keys[same_lead_keys.min_jaccard < 0.34].npc_key
    low_skus = w[w.npc_key.isin(low_keys) & w.lead.notna()]
    low_overlap = duckdb.sql("""
        SELECT npc_key, count(*) AS skus, min(price) AS price_min, max(price) AS price_max,
            string_agg(DISTINCT grapes, '  //  ') AS grape_lists
        FROM low_skus GROUP BY npc_key ORDER BY skus DESC
    """).df()
    mo.vstack([
        mo.md(f"The {len(low_overlap)} keys with a min Jaccard under 0.34:"),
        mo.ui.table(low_overlap, selection=None, page_size=10),
    ])
    return (low_skus,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Reading the table.** These are almost all the same wine across vintages: the blend moves
    from year to year (Tignanello, Solaia, Latour, Vega Sicilia Unico, Insignia) or one SKU lists
    only its main grape. Prices span a wide range inside a key because vintages and formats do.
    None of the biggest keys is a different wine under a generic name, so unrelated wines do not
    seem to hide in the keys `npcg` leaves together. That count is **380 keys**, not 455: the 455
    also counted SKUs with no grape listed, which cannot be compared.
    """)
    return


if __name__ == "__main__":
    app.run()
