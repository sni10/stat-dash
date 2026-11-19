# Project instructions

Personal dashboard of housing prices on LUN Statistics data (lun.ua/stat): weekly collection into Postgres, then
charts in a TailAdmin-based UI. Spec: `ТЗ Дашборд рынка недвижимости на данных ЛУН Статистики.md` (local, not in git).
Stack and CI mirror `agregator-backend`.

- Stage 1 (done): `collector` app — `collect_lun`, `scheduler` container (supercronic, `deploy/crontab`).
- Stage 2 (done): `dashboard` app — Overview and By rooms pages, `/api/prices`, `/api/monthly`, Django login.
- Data model (`docs/data-model.md`): every LUN answer is archived in `lun_raw`; `collector/parsers.py` parses it into
  one table per entity (series with history + a floating "today" point, snapshots keyed by `snap_date`).
  `manage.py reparse_lun` rebuilds the tables from the archive: run it after changing a parser.
- Extra pages (`dashboard/charts.py`, `views.PAGES`) read those tables. 4+ rooms are not shown anywhere.
- Stage 3: table/CSV, collection status page, anomaly and stale-run alerts.

UI: TailAdmin free (Tailwind v4) theme in `frontend/src/tailadmin.css`. After changing templates or
`dashboard/static/dashboard/js`, run `npm ci && npm run build` in `frontend/` and commit `dashboard/static`
(CI fails on a stale build). LUN's m² median is per city: equal for every room count.

Run locally: `docker compose up -d --build`; tests: `uv run python manage.py test` (needs the `db` service,
127.0.0.1:5435). Real LUN data never goes into the repo: test payloads are synthetic (`collector/tests/factories.py`).

## Commit messages: Conventional Commits, always

```
<type>(<optional scope>)<optional !>: <description>
```

- Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`, `style`, `revert`.
- Scopes: `collector`, `dashboard`, `config`, `deploy`, `ci`.
- Header ≤ 150 chars, lower-case type, no trailing period.
- Breaking change: `!` after the type/scope **and** a `BREAKING CHANGE:` footer.
- No `Co-Authored-By` / "Generated with Claude" lines — the message only.

Messages drive automatic releases on `main` (python-semantic-release, `pyproject.toml`): `fix`/`perf` → patch,
`feat` → minor. Config, Docker, compose, CI or tooling changes are `build`, `ci` or `chore`, never `fix`/`feat`.
`commitlint.config.mjs` checks them.

Commit or push only when the user explicitly asks for it.
