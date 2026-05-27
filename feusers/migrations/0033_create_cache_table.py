"""Create the DB cache table used by the shared brute-force rate limiter.

`createcachetable` is idempotent: it skips tables that already exist, so the
reverse operation intentionally drops the table only if present.
"""
from django.core.cache import caches
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias)


def drop_cache_table(apps, schema_editor):
    table = caches["default"]._table
    schema_editor.execute(f"DROP TABLE IF EXISTS {schema_editor.quote_name(table)}")


class Migration(migrations.Migration):

    dependencies = [
        ('feusers', '0032_alter_feuser_unspent_allowance_action'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
