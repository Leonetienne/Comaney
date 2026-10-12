#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py purge_inactive_ai_config

if [ "${DEBUG}" != "TRUE" ]; then
    python manage.py collectstatic --noinput --clear
fi

exec "$@"
