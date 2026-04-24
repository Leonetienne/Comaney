#!/bin/sh
set -e

python manage.py migrate --noinput

if [ "${DEBUG}" != "TRUE" ]; then
    python manage.py collectstatic --noinput --clear
fi

exec "$@"
