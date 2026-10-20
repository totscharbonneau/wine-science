"""PROTOTYPE, throwaway (wayfinder ticket: behavioural signal). Do co-reviewed / co-picked pairs share traits more than random pairs?"""
import duckdb
con=duckdb.connect("data/processed/winescience.duckdb",read_only=True)
con.sql("create temp view g as select * from read_parquet('data/processed/wine_groups_npc.parquet')")
con.sql("""create temp table attr as select g.group_id, any_value(w.color) color, any_value(w.country) country, any_value(w.taste_tag) taste_tag, any_value(w.grape_primary) grape from wines w join g using(sku) group by 1""")
con.sql("""create temp table rv as select distinct r.author, g.group_id from customer_reviews r join g using(sku) where r.author is not null""")
con.sql("""create temp table pk as select distinct p.employee_id author, g.group_id from employee_picks p join g using(sku) where p.employee_id is not null""")
def pairs(tab,m,cap=200):
    return f"""with u as (select author from {tab} group by 1 having count(*) between 2 and {cap}),
    e as (select t.author,t.group_id from {tab} t join u using(author)),
    p as (select a.group_id g1,b.group_id g2 from e a join e b on a.author=b.author and a.group_id<b.group_id group by 1,2 having count(*)>={m})"""
def rate(label,sql):
    r=con.sql(sql).fetchone(); print(f"{label:55s} n={r[0]:>8}  same_color={r[1]:.3f} same_country={r[2]:.3f} same_taste_tag={r[3]:.3f}")
sel="""select count(*), avg((a.color=b.color)::int), avg((a.country=b.country)::int), avg((a.taste_tag=b.taste_tag)::int) from {src} x join attr a on a.group_id=x.g1 join attr b on b.group_id=x.g2 where a.taste_tag is not null and b.taste_tag is not null"""
rate("baseline: random group pairs (reviewed groups)", """select count(*), avg((a.color=b.color)::int), avg((a.country=b.country)::int), avg((a.taste_tag=b.taste_tag)::int) from (select r1.group_id g1, r2.group_id g2 from (select distinct group_id from rv using sample 3000 rows) r1, (select distinct group_id from rv using sample 3000 rows) r2 where r1.group_id<r2.group_id) x join attr a on a.group_id=x.g1 join attr b on b.group_id=x.g2 where a.taste_tag is not null and b.taste_tag is not null""")
for m in (1,2,3):
    rate(f"reviews: pairs sharing >={m} authors", pairs("rv",m)+sel.format(src="p"))
rate("picks: pairs sharing >=1 employee", pairs("pk",1)+sel.format(src="p"))
rate("picks: pairs sharing >=2 employees", pairs("pk",2)+sel.format(src="p"))
# heavy reviewers excluded vs included
rate("reviews, >=2 shared, authors with <=30 groups only", pairs("rv",2,30)+sel.format(src="p"))
print(con.sql("select count(distinct employee_id) ids, count(distinct employee_name) nm from employee_picks").fetchone())
