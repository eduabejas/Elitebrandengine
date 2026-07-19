"""Bundle the site + current demo data into a single self-contained file.

Produces ``web/sandbox.html`` — one HTML file with the CSS, JS and data all
inlined, so it runs by just opening it in a browser (no server, no build, no
network). Handy as an offline demo or to hand someone a clickable sandbox.

    python scripts/build_sandbox.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E"
           "%F0%9F%8F%94%EF%B8%8F%3C/text%3E%3C/svg%3E")


def build() -> Path:
    css = (WEB / "assets/css/styles.css").read_text(encoding="utf-8")
    app = (WEB / "assets/js/app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")

    # Inline the JSON snapshot (trim history to keep the file light).
    meta = json.loads((WEB / "data/meta.json").read_text(encoding="utf-8"))
    products = json.loads((WEB / "data/products.json").read_text(encoding="utf-8"))
    deals = json.loads((WEB / "data/deals.json").read_text(encoding="utf-8"))
    for p in products.get("products", []):
        if isinstance(p.get("history"), list):
            p["history"] = p["history"][-24:]
    data_js = "window.__DATA__ = " + json.dumps(
        {"meta": meta, "products": products, "deals": deals},
        ensure_ascii=False, separators=(",", ":")) + ";"

    # Read inlined DATA instead of fetch()-ing the JSON files.
    app = re.sub(
        r"const \[meta, products, deals\] = await Promise\.all\(\[.*?\]\);",
        "const meta = window.__DATA__.meta;\n"
        "      const products = window.__DATA__.products;\n"
        "      const deals = window.__DATA__.deals;",
        app, count=1, flags=re.DOTALL)

    # Body markup minus the external video layer and the linked script.
    body = re.search(r"<body>(.*)</body>", html, re.DOTALL).group(1)
    body = re.sub(r"<!--\s*data-sources.*?-->", "", body, flags=re.DOTALL)
    body = re.sub(r"<video\b.*?</video>", "", body, flags=re.DOTALL)
    body = re.sub(r'<script src="./assets/js/app.js"[^>]*></script>', "", body).strip()

    out = WEB / "sandbox.html"
    out.write_text(
        "<!doctype html>\n<html lang=\"es\">\n<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "  <title>Elite Brand Engine — Sandbox</title>\n"
        "  <meta name=\"description\" content=\"Sandbox interactivo del motor de comparación de ofertas outdoor.\" />\n"
        f"  <link rel=\"icon\" href=\"{FAVICON}\" />\n"
        "</head>\n<body>\n"
        f"<style>\n{css}\n</style>\n{body}\n"
        f"<script>{data_js}</script>\n<script>\n{app}\n</script>\n"
        "</body>\n</html>\n",
        encoding="utf-8")
    return out


if __name__ == "__main__":
    p = build()
    print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size // 1024} KB)")
