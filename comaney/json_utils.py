import json


def safe_json(obj) -> str:
    """Serialize obj to JSON with <, >, & escaped so the output is safe
    to embed in a <script> block via Django's |safe filter without
    breaking out of the script element."""
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
