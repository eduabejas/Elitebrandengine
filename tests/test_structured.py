"""Unit tests for the JSON-LD / schema.org structured-data parser.

Runnable with pytest, or directly: ``python -m tests.test_structured``.
"""

from __future__ import annotations

from engine.config import DEFAULTS, Config
from engine.connectors.structured import (
    StructuredDataConnector,
    _region_from_url,
    _source_label,
    extract_offers_from_jsonld,
)
from engine.models import WatchItem

HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Arc'teryx Beta AR Jacket",
 "brand":{"@type":"Brand","name":"Arc'teryx"},"gtin13":"1234567890123","sku":"X1",
 "image":"https://x/img.jpg",
 "offers":{"@type":"Offer","price":"399.00","priceCurrency":"USD",
           "availability":"https://schema.org/InStock","url":"https://www.rei.com/p/x"}}
</script>
<script type="application/ld+json">
{"@type":"Product","name":"Rab Microlight Alpine Down Jacket",
 "offers":{"@type":"AggregateOffer","lowPrice":"180.00","priceCurrency":"EUR",
           "availability":"https://schema.org/OutOfStock","url":"https://www.bergfreunde.eu/p/y"}}
</script>
</head></html>
"""


def test_extract_single_offer():
    offers = extract_offers_from_jsonld(HTML)
    beta = [o for o in offers if "Beta" in o["name"]][0]
    assert beta["price"] == 399.0 and beta["currency"] == "USD"
    assert beta["availability"] == "in_stock" and beta["gtin"] == "1234567890123"


def test_aggregate_offer_lowprice():
    rab = [o for o in extract_offers_from_jsonld(HTML) if "Rab" in o["name"]][0]
    assert rab["price"] == 180.0 and rab["availability"] == "out_of_stock"


def test_graph_wrapper():
    html = ('<script type="application/ld+json">{"@graph":[{"@type":"Product",'
            '"name":"P","offers":{"@type":"Offer","price":"10","priceCurrency":"USD"}}]}'
            '</script>')
    offers = extract_offers_from_jsonld(html)
    assert len(offers) == 1 and offers[0]["price"] == 10.0


def test_bad_or_missing_json_is_safe():
    assert extract_offers_from_jsonld('<script type="application/ld+json">{oops}</script>') == []
    assert extract_offers_from_jsonld("<html>no structured data</html>") == []


def test_region_and_source_helpers():
    assert _region_from_url("https://www.bergfreunde.eu/p") == "EU"
    assert _region_from_url("https://www.mec.ca/p") == "CA"
    assert _region_from_url("https://www.rei.com/p") == "US"
    assert _source_label("https://www.backcountry.com/x") == "backcountry.com"


def test_connector_parses_watch_urls():
    conn = StructuredDataConnector(Config(raw=DEFAULTS), {})
    conn.fetch = lambda url: HTML                       # stub the network
    w = WatchItem(id="x", brand="Arc'teryx", name="Beta AR Jacket",
                  urls=["https://www.rei.com/p/x"])
    offers = conn.search(w)
    # only the matching product survives; the Rab item is filtered by brand
    assert len(offers) == 1
    assert offers[0].price == 399.0 and offers[0].region == "US"
    assert offers[0].availability == "in_stock"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
