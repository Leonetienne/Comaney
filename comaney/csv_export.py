import csv

# Characters that, when a CSV cell begins with one of them, cause Excel /
# LibreOffice Calc to interpret the cell as a formula (or DDE payload) on open.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """Neutralise formula-triggering string cells for spreadsheet apps.

    A string cell whose first character is a formula trigger gets a leading
    apostrophe, which forces Excel / LibreOffice Calc to treat it as text while
    preserving the visible value. Numbers, dates and benign strings pass
    through untouched.
    """
    if isinstance(value, str) and value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def write_model_csv(buffer, qs, *, skip=(), extra=()):
    """Write a queryset's concrete fields as CSV rows into a text buffer.

    FK fields are written as raw ids (via attname). `extra` is an iterable
    of (header, fn) pairs for additional computed columns.
    """
    fields = [f for f in qs.model._meta.concrete_fields if f.name not in skip]
    w = csv.writer(buffer)
    w.writerow([f.attname for f in fields] + [col for col, _ in extra])
    for obj in qs:
        row = []
        for field in fields:
            value = getattr(obj, field.attname)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            row.append("" if value is None else _csv_safe(value))
        for _, fn in extra:
            row.append(_csv_safe(fn(obj)))
        w.writerow(row)
