# stat-dash

A personal dashboard of housing price dynamics in Ukraine built on [LUN Statistics](https://lun.ua/stat) data.
Once a week it collects listing prices (sale and rent, by room count) into Postgres and keeps the history.

> Prices are of **listings**, not deals. LUN's API is undocumented and unofficial: this is for personal use, and no
> collected data is published here.

## How it works

- `collect_lun` (Django management command) fetches `flat-price-history` (sale + rent) and `price` for every
  enabled city, stores raw answers in `lun_raw` (only when the data changed), validates them (pydantic) and
  upserts the series into `lun_price_snapshot`. Each run leaves a row in `collect_run`.
- The series is monthly (the 24th) plus one floating "today" point; it is replaced on every run and stays out of
  the monthly aggregate `v_price_monthly`.
- The `scheduler` container runs it with supercronic: Monday 04:17 Europe/Kyiv, plus a daily catch-up that collects
  only if the last success is older than 7 days. A `pg_dump` follows every successful run (8 kept, `./backups`).
- Errors (blocking, schema changes, failed runs) are alerted to Telegram if a bot token is set.

## Run

```sh
cp .env.example .env        # set the secret key and the DB password
docker compose up -d --build
docker compose exec web python manage.py createsuperuser   # admin: http://localhost:8010/admin/
docker compose exec scheduler python manage.py collect_lun # collect now instead of waiting for Monday
```

Dashboard: http://localhost:8010/ (log in with the superuser): Overview (m² median, month and year change, number of
listings, the whole history), By rooms (object price per room count, period filter), and pages built from LUN's
other endpoints: Districts, Market (days on market, price distribution, listing vs deal price), Affordability
(price in years of salary, rent share of salary, by profession, price in years of rent), New buildings (prices by
class, developers, parking, construction, installments, housing put into service) and Houses. 1–3 room flats only:
4+ rooms are collected but not shown. JSON:
`/api/prices?city=odesa&deal=sale&rooms=1,2&from=YYYY-MM&to=YYYY-MM&cur=usd` and `/api/monthly` with the same params.

Cities are seeded from lun.ua/stat (22, LUN `cityId`); all are collected: 18 endpoints per city plus
4 global ones (`collector/lun/endpoints.py`), about 400 requests and 20–25 minutes per run with the pauses and listed in the dashboard's city filter; Odesa is the default
(`DASHBOARD_DEFAULT_CITY`). Switch a city off in the admin.

## Deploy

A small VPS is enough (1 CPU, ~1.6 GB RAM shared with other stacks): `compose.prod.yaml` runs the CI image
`ghcr.io/sni10/stat-dash:<sha>` with db, migrate, web and scheduler; `.env.production.example` is the server's `.env`.
No domain and no reverse proxy: the web port is published on the server's Tailscale IP (or 127.0.0.1 + SSH tunnel),
never on a public address without HTTPS. The weekly collection runs with 10–20 s pauses there (~1.5–2 hours).

```sh
DEPLOY_SERVER=deploy@<server> bash deploy/deploy.sh <full commit sha>   # deploy or roll back
```

The server-specific steps live in a local, untracked `DEPLOY.md`.

## Develop

```sh
docker compose up -d db
uv sync
uv run python manage.py test
(cd frontend && npm ci && npm run build)   # after changing templates: rebuilds dashboard/static (committed)
```

UI theme: [TailAdmin](https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template) free, MIT.

Commits follow Conventional Commits: releases (`vX.Y.Z` tags, GitHub Releases, `ghcr.io` images) are made by CI
from them.
