import csv


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
            row.append("" if value is None else value)
        for _, fn in extra:
            row.append(fn(obj))
        w.writerow(row)
