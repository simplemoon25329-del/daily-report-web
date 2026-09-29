"""Load optional recognition hints without imposing a whitelist."""
import json
from pathlib import Path


def load_dictionaries(path=None):
    empty = {"professions": [], "people": []}
    path = Path(path) if path is not None else Path(__file__).resolve().parent / "config" / "dictionaries.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return empty
        result = {}
        for key in empty:
            values = payload.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                return empty
            result[key] = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        return result
    except (OSError, UnicodeError, ValueError):
        return empty
