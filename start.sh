#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# One scheduler per container; the database window lock prevents duplicate
# syncs when Liara runs more than one container.
(
  while :; do
    python manage.py run_website_price_scheduler
    echo 'Website price scheduler stopped; restarting in 5 seconds.' >&2
    sleep 5
  done
) &

exec gunicorn Sefro_Clinic.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
