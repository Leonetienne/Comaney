#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "comaney.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed?"
        ) from exc
    try:
        execute_from_command_line(sys.argv)
    except Exception as exc:
        from django.core.exceptions import ImproperlyConfigured
        if isinstance(exc, ImproperlyConfigured):
            print(f"\nFATAL: {exc}\n", file=sys.stderr)
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
