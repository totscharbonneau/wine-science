import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import duckdb
    from src import DATA_DIR

    return DATA_DIR, duckdb, mo


@app.cell
def _(DATA_DIR, duckdb):
    con = duckdb.connect(DATA_DIR / "processed" / "winescience.duckdb", read_only=True)
    return (con,)


@app.cell(hide_code=True)
def _(con, mo, wines):
    _df = mo.sql(
        f"""
        SELECT * FROM wines
        """,
        engine=con
    )
    return


@app.cell
def _(con, mo, wines):
    _df = mo.sql(
        f"""
        SELECT SUM(dup_wines) from( SELECT COUNT(*) as dup_wines , "name"
        FROM wines
        group by "name"
        HAVING COUNT(*) > 1 )
        as total_dupewines


        """,
        engine=con
    )
    return


@app.cell(hide_code=True)
def _(con, mo, wines):
    _df = mo.sql(
        f"""
        SELECT * FROM wines
        WHERE "name" = 'Ornellaia'
        """,
        engine=con
    )
    return


if __name__ == "__main__":
    app.run()
