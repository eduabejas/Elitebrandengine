"""Validate data/watchlist.json before a run (and in CI).

Errors (exit 1): missing/duplicate id, missing name/brand, wrong field types,
non-positive target_price. Warnings (exit 0): brand not in the flagship set,
so a typo like "Arcteryxx" surfaces instead of silently matching nothing.

    python -m engine.validate
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .config import Config, load_config
from .normalize import canonical_brand


def validate_items(items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    if not isinstance(items, list):
        return ["watchlist 'items' must be a list"], []

    for i, it in enumerate(items):
        where = f"item[{i}]"
        if not isinstance(it, dict):
            errors.append(f"{where}: must be an object")
            continue

        wid = it.get("id")
        where = f"item[{i}] id={wid!r}"
        if not wid or not isinstance(wid, str):
            errors.append(f"{where}: missing/invalid 'id'")
        elif wid in seen_ids:
            errors.append(f"{where}: duplicate 'id'")
        else:
            seen_ids.add(wid)

        if not it.get("name") or not isinstance(it.get("name"), str):
            errors.append(f"{where}: missing/invalid 'name'")

        brand = it.get("brand")
        if not brand or not isinstance(brand, str):
            errors.append(f"{where}: missing/invalid 'brand'")
        elif canonical_brand(brand) is None:
            warnings.append(f"{where}: brand {brand!r} is not a known flagship "
                            f"brand — it won't match API/feed results")

        for field in ("sizes", "colors", "keywords"):
            if field in it and not isinstance(it[field], list):
                errors.append(f"{where}: '{field}' must be a list")

        tp = it.get("target_price")
        if tp is not None and (not isinstance(tp, (int, float)) or tp <= 0):
            errors.append(f"{where}: 'target_price' must be a positive number")

        if "active" in it and not isinstance(it["active"], bool):
            errors.append(f"{where}: 'active' must be true/false")

    return errors, warnings


def load_raw_items(cfg: Config) -> list[dict]:
    p = cfg.path("watchlist")
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("items", data) if isinstance(data, dict) else data


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    try:
        items = load_raw_items(cfg)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[validate] cannot read watchlist: {exc}")
        return 1

    errors, warnings = validate_items(items)
    for w in warnings:
        print(f"  ⚠️  {w}")
    for e in errors:
        print(f"  ❌  {e}")

    n = len(items) if isinstance(items, list) else 0
    if errors:
        print(f"[validate] {len(errors)} error(s), {len(warnings)} warning(s) "
              f"across {n} item(s) — FAIL")
        return 1
    print(f"[validate] {n} item(s) OK ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
