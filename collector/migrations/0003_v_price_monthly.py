"""Monthly aggregate (spec, "Агрегаты и методика"). The floating "today" point is preliminary and stays out."""
from django.db import migrations

CREATE = """
CREATE VIEW v_price_monthly AS
SELECT date_trunc('month', snap_date)::date AS month,
       city_id, contract_type, room_count,
       sum(median_m2_usd * cnt) / nullif(sum(cnt), 0) AS w_avg_m2_usd,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY median_m2_usd) AS med_m2_usd,
       sum(cnt) / count(*) AS avg_cnt
FROM lun_price_snapshot
WHERE NOT is_today
GROUP BY 1, 2, 3, 4;
"""


class Migration(migrations.Migration):
    dependencies = [('collector', '0002_seed_cities')]

    operations = [migrations.RunSQL(CREATE, 'DROP VIEW v_price_monthly;')]
