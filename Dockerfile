FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

# postgresql-client: pg_dump for backups (Debian trixie -> 17, the same major as the db service)
# supercronic: cron for containers (the scheduler service), checksum-pinned
ARG SUPERCRONIC_VERSION=v0.2.51
ARG SUPERCRONIC_SHA256=cc232108374e8e2b537045f2d5eaa1229f619db314c3ba6a14d38b35dc0aa123
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client tzdata curl ca-certificates \
    && curl -fsSL -o /usr/local/bin/supercronic \
       "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lock file changes
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

RUN useradd --system --create-home --uid 1000 app \
    && DJANGO_SECRET_KEY=build-only DB_NAME=- DB_USER=- DB_PASSWORD=- \
       python manage.py collectstatic --noinput --verbosity 0 \
    && chown -R app:app staticfiles
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
