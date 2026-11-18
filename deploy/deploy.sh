#!/usr/bin/env bash
# Deploy (or roll back to) an image built by GitHub Actions:
#   DEPLOY_SERVER=deploy@<server> deploy/deploy.sh <full commit sha>
# Copies compose.prod.yaml and the Caddyfile to the server, records the sha in the server's .env (IMAGE_TAG), pulls and restarts the
# stack. Migrations run in the one-shot `migrate` service before web and scheduler start.
# The server address is not in this public repo: pass DEPLOY_SERVER (or export it in your shell profile).
set -euo pipefail

SERVER=${DEPLOY_SERVER:?set DEPLOY_SERVER, e.g. DEPLOY_SERVER=deploy@203.0.113.10}
DIR=${DEPLOY_DIR:-stat-dash}  # relative = in the deploy user's home, like ~/signal
SHA=${1:-}

if [[ ! $SHA =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: DEPLOY_SERVER=user@host $0 <full 40-char commit sha>   (ghcr.io/sni10/stat-dash:<sha> must exist)" >&2
  exit 1
fi

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ssh "$SERVER" mkdir -p "$DIR/backups"
scp -q "$ROOT/compose.prod.yaml" "$SERVER:$DIR/compose.prod.yaml"
scp -q "$ROOT/deploy/Caddyfile" "$SERVER:$DIR/Caddyfile"

ssh "$SERVER" bash -s -- "$DIR" "$SHA" <<'REMOTE'
set -euo pipefail
cd "$1"
[ -f .env ] || { echo "no $1/.env on the server: create it from .env.production.example first" >&2; exit 1; }
if grep -q '^IMAGE_TAG=' .env; then sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$2/" .env; else echo "IMAGE_TAG=$2" >> .env; fi
mkdir -p backups && chmod 0777 backups  # the containers run as uid 1000 and write pg_dump files here
compose() { docker compose -f compose.prod.yaml "$@"; }
compose pull --quiet
compose up -d --remove-orphans
compose ps -a --format '{{.Service}}\t{{.Status}}\t{{.Image}}'
REMOTE
