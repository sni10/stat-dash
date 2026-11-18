#!/bin/sh
# Catch up first: if the computer was off at the weekly slot, collect now. A failure here must not stop the
# scheduler (it is alerted and recorded in collect_run), so no `set -e`.
python manage.py collect_lun --if-stale --backup

exec supercronic -passthrough-logs /app/deploy/crontab
