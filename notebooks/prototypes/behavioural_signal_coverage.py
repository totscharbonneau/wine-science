"""PROTOTYPE, throwaway (wayfinder ticket: behavioural signal). Run: uv run python -I notebooks/prototypes/behavioural_signal_coverage.py"""
import duckdb
con=duckdb.connect("data/processed/winescience.duckdb",read_only=True)
con.sql("create temp view g as select * from read_parquet('data/processed/wine_groups_npc.parquet')")
con.sql("""create temp table rv as select distinct r.author, g.group_id from customer_reviews r join g using(sku) where r.author is not null""")
con.sql("""create temp table pk as select distinct p.employee_id author, g.group_id from employee_picks p join g using(sku) where p.employee_id is not null""")
def show(t,q): print("\n##",t); con.sql(q).show(max_width=200)
# author sanity
show("review-author count per author buckets", """with a as (select author,count(*) n from rv group by 1) select case when n=1 then '1' when n<=4 then '2-4' when n<=19 then '5-19' when n<=99 then '20-99' else '100+' end b,count(*) authors,sum(n) author_group_pairs from a group by 1 order by min(n)""")
show("top authors", """select author, count(distinct group_id) n_groups, count(*) reviews, count(distinct review_date) n_days, min(review_date) first_d, max(review_date) last_d from customer_reviews r join g using(sku) group by 1 order by 2 desc limit 8""")
show("same-day multi-review authors (>=10 reviews on one day)", """select count(*) author_days, count(distinct author) authors from (select author, review_date, count(*) n from customer_reviews where not is_bulk_import_date group by 1,2 having n>=10)""")
show("authors posting in both languages", """select count(*) from (select author from customer_reviews group by 1 having count(distinct language)>1)""")
# neighbours via shared authors
for name,tab,mins in [("reviews","rv",[1,2,3]),("picks","pk",[1,2,3])]:
    for m in mins:
        show(f"{name}: groups with >=1 neighbour sharing >={m} {'author' if name=='reviews' else 'employee'}(s) (users with <=200 groups)", f"""
        with u as (select author from {tab} group by 1 having count(*) between 2 and 200),
        e as (select t.author,t.group_id from {tab} t join u using(author)),
        p as (select a.group_id g1,b.group_id g2,count(*) shared from e a join e b on a.author=b.author and a.group_id<b.group_id group by 1,2 having shared>={m}),
        deg as (select g1 gid from p union all select g2 from p)
        select count(distinct gid) groups_with_neighbour, (select count(distinct group_id) from {tab}) groups_with_signal, (select count(*) from g_all) total_groups, count(*) /count(distinct gid) avg_edges_per_node from deg""" if False else f"""
        with u as (select author from {tab} group by 1 having count(*) between 2 and 200),
        e as (select t.author,t.group_id from {tab} t join u using(author)),
        p as (select a.group_id g1,b.group_id g2,count(*) shared from e a join e b on a.author=b.author and a.group_id<b.group_id group by 1,2 having count(*)>={m}),
        deg as (select g1 gid from p union all select g2 from p)
        select count(distinct gid) groups_with_neighbour, (select count(distinct group_id) from {tab}) groups_with_signal, round(count(*)*1.0/count(distinct gid),1) avg_edges, (select count(*) from p) pairs from deg""")
# concentration on availability
show("review/pick coverage vs availability & price", """
with grp as (select g.group_id, bool_or(w.in_stock) in_stock, median(w.price) price, max(w.rating_count) rc from wines w join g using(sku) group by 1),
f as (select grp.*, group_id in (select group_id from rv) has_rev, group_id in (select group_id from pk) has_pick from grp)
select has_rev, has_pick, count(*) n_groups, round(avg(in_stock::int),2) frac_in_stock, round(median(price),1) med_price, round(avg((rc>0)::int),2) frac_rated from f group by 1,2 order by 1,2""")
show("reviews per group among reviewed groups", """select quantile_cont(n,[0.25,0.5,0.75,0.9,0.99]) q, max(n) mx from (select group_id,count(*) n from rv group by 1)""")
show("picks vs reviews group overlap", """select (select count(distinct group_id) from rv) rv, (select count(distinct group_id) from pk) pk, (select count(*) from (select group_id from rv intersect select group_id from pk)) both_""")
show("pick employee store spread", """select count(*) emp, round(avg(stores),1) avg_stores, count(*) filter(where stores>1) multi_store from (select employee_id, count(distinct store_ref) stores from employee_picks group by 1)""")
show("employee_id vs employee_name consistency", """select count(distinct employee_id) ids, count(distinct employee_name) names, count(distinct (employee_id,employee_name)) pairs from employee_picks""")
