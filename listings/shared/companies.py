"""
Loads per-source company lists from data/companies/*.yml.

To add or remove a company for a source, edit the corresponding YAML file
in `data/companies/` — no code change needed. Each file is a list of dicts
whose keys match what the source's fetcher expects (e.g. Greenhouse uses
`board_token`, Lever/Ashby use `slug`).
"""
from functools import lru_cache
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "companies"


@lru_cache(maxsize=None)
def load_companies(source: str) -> list[dict]:
    path = _DATA_DIR / f"{source}.yml"
    if not path.exists():
        raise FileNotFoundError(f"No company list for source '{source}' at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a YAML list, got {type(data).__name__}")
    return data
