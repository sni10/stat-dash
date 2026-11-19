# Data model

`lun_raw` is the archive and the source of truth: every answer of the source, kept when its data changed. A parser per endpoint
(`collector/parsers.py`) turns an answer into rows of the tables below with an idempotent upsert on the natural key.
`manage.py reparse_lun` replays the archive (oldest first) and rebuilds the tables.

Two kinds of endpoints:

- **Series** — the source sends the history (monthly points, the 24th or the 1st) plus a floating "today" point
  (`is_today`). The previous "today" rows of the same series are replaced on every collection; when "today" falls on a
  monthly date, the monthly point wins.
- **Snapshots** — the source sends only the current state. The key holds `snap_date` (the date in the answer, or the
  collection date when the answer has none): a new date adds a snapshot, the same date overwrites it. History builds up
  week by week on our side.

Conventions: `room_count = 0` means all room counts; `scope` is `city` or `region` (the oblast); UAH and USD are both
kept when the source sends them; 4+ room flats are stored (the dashboard does not show them).

## Dimension

| Table | Key | Values |
|---|---|---|
| `district` | city, kind (`district` / `settlement` / `microdistrict`), lun_id | name_uk, name_en |

The source numbers districts per city and uses the same ids in every endpoint (Odesa 11–14, Lviv 48–52, Kyiv 1–10). Kyiv's
new-building answer adds suburbs (`isCity`) whose ids collide with district ids, hence `kind`. Ivano-Frankivsk sends
micro-districts with ids ≥ 10 000 000.

## Series

| Table | Endpoint | Key | Values |
|---|---|---|---|
| `flat_price_point` | flat-price-history | snap_date, city, contract type, rooms | medians and m² medians UAH/USD, cnt, is_today |
| `house_price_point` | houses-price-history | city, contract type, scope, date | medians and m² UAH/USD, area, cnt, is_today |
| `exposure_point` | median-exposure | city, contract type, rooms, date | days on the market, cnt, is_today |
| `deal_price_point` | rieltor | city, contract type, rooms, date | listing and deal price (and per m²) UAH/USD, is_today |
| `affordability_point` | salary-history | city, contract type, rooms, date | value (sale: years of salary, rent: % of salary), price, salary, cnt, is_today |
| `rent_payback_point` | sale-in-rent-history | city, rooms, date | years of rent, is_today |
| `primary_class_price` | price | city, scope, class (economy…premium, all), month | average m² price UAH/USD, cnt, is_today |
| `housing_commissioning` | dssu | region (id of the oblast centre; 10000 = Ukraine), year, quarter (0 = the year's total) | all housing m², apartment buildings m² |

## Snapshots

| Table | Endpoint | Key | Values |
|---|---|---|---|
| `district_price` | market-districts | district, contract type, rooms, snap_date | medians (all / renovated / not), m² medians, USD, rate, counts |
| `district_average_price` | districts, parking-districts | district, item (`flat_m2` / `parking`), snap_date | average UAH/USD, cnt |
| `house_district_price` | districts-house-price | district, contract type, snap_date | median and m² median USD, area, cnt |
| `price_bucket` | price-distribution | city, contract type, rooms, currency, snap_date, price_from | price_to (null: open bucket), cnt |
| `profession_affordability` | salary-positions | city, contract type, rooms, profession, snap_date | value, salary, price, work.ua link |
| `parking_class_price` | parking-classes | city, scope, class, snap_date | medians UAH/USD, cnt |
| `developer_rank` | developers-ranking | city, year, developer | place, flats delivered |
| `developer_share` | developers-distribution | city, year, developer | share of flats delivered, % |
| `construction_stat` | sections | city, scope, snap_date | on sale, under construction, preparatory works, built since 2010 |
| `lending_stat` | lending | city, scope, snap_date | installments, єОселя mortgages, credits |
| `pets_rent_share` | pets-rent | city, scope, realty type, snap_date | allowed / by agreement / forbidden / unknown %, cnt |
