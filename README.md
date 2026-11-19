# stat-dash

[![CI](https://github.com/sni10/stat-dash/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sni10/stat-dash/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/sni10/stat-dash?sort=semver)](https://github.com/sni10/stat-dash/releases)
[![Tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fsni10%2Fstat-dash%2Fbadges%2Ftests.json)](https://github.com/sni10/stat-dash/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fsni10%2Fstat-dash%2Fbadges%2Fcoverage.json)](https://github.com/sni10/stat-dash/actions/workflows/ci.yml)
[![Docker image](https://img.shields.io/badge/image-ghcr.io%2Fsni10%2Fstat--dash-2496ED?logo=docker&logoColor=white)](https://github.com/sni10/stat-dash/pkgs/container/stat-dash)
[![Last commit](https://img.shields.io/github/last-commit/sni10/stat-dash)](https://github.com/sni10/stat-dash/commits/main)

[![Python](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-6.1-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![uv](https://img.shields.io/badge/uv-managed-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Tailwind CSS](https://img.shields.io/badge/tailwind_css-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![TailAdmin](https://img.shields.io/badge/ui-TailAdmin-465FFF)](https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template)

Housing prices in Ukraine at a glance: 22 cities, sale and rent, updated every week.

**Demo:** [https://185-25-117-74.sslip.io](https://185-25-117-74.sslip.io) (sign-in required)

Login: `superme`, password: `superme`.

## What you can see

- **Overview** — the median price per m², how it changed over a month and a year, the number of listings, and the
  whole history since 2023.
- **By rooms** — prices of 1-, 2- and 3-room flats over time.
- **Districts** — prices by district, with or without renovation; new buildings and parking by district.
- **Market** — how fast flats sell or rent, the most common prices, the asking price next to the real deal price.
- **Affordability** — a flat's price in years of salary, the share of salary that goes to rent, by profession.
- **New buildings** — starting prices by class, top developers, parking, construction activity, installments and
  mortgages.
- **Houses** — house prices in the city and its region.

Pick a city, sale or rent, and USD or UAH. The interface is in Ukrainian, with a light and a dark theme.

## Where the numbers come from

The data comes from a public real-estate statistics service and is refreshed once a week, on Monday night. These are prices of **listings**,
not of completed deals (except the realtors' deal prices on the Market page). The project is personal and
non-commercial; no collected data is published in this repository.

## Run it yourself

You need [Docker](https://www.docker.com/).

```sh
cp .env.example .env                                         # then set a secret key and a database password
docker compose up -d --build
docker compose exec web python manage.py createsuperuser     # your login
docker compose exec scheduler python manage.py collect_lun   # first data now, instead of waiting for Monday
```

Open http://localhost:8010 and sign in. The first collection takes about 20–25 minutes for all cities.

## For developers

```sh
docker compose up -d db && uv sync && uv run python manage.py test     # tests
(cd frontend && npm ci && npm run build)                               # after changing templates
DEPLOY_SERVER=deploy@<server> bash deploy/deploy.sh <commit sha>       # deploy a CI image to a server
docker compose exec web python manage.py reparse_lun                   # rebuild the tables from the raw archive
```

Every answer of the source is archived raw and parsed into one table per entity: see [docs/data-model.md](docs/data-model.md).

Every push to `main` is tested, released (version tag + GitHub Release) and built into a Docker image automatically.
Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/). UI theme:
[TailAdmin](https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template) (MIT).
