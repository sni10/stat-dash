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

Cities are seeded from lun.ua/stat (22, LUN `cityId`); only Odesa is enabled. Enable more in the admin.

## Develop

```sh
docker compose up -d db
uv sync
uv run python manage.py test
```

Commits follow Conventional Commits: releases (`vX.Y.Z` tags, GitHub Releases, `ghcr.io` images) are made by CI
from them.
