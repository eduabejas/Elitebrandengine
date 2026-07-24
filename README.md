# 🏔️ Elite Brand Engine

**A focused price-comparison and deal-alert engine for outdoor / mountaineering
gear.** It tracks a curated watchlist of products from a fixed set of flagship
brands, collects offers from multiple **legitimate** sources, detects genuine
price drops against stored history, reports them by **email**, and publishes a
searchable comparison **website** — all running **for free** on GitHub Actions +
GitHub Pages.

> Built for a US company that buys made-to-order outdoor gear for a niche
> audience (mountaineers, alpinists, explorers, botanists, agronomists,
> photographers…). Narrowing the search to a defined brand universe is exactly
> what makes matching accurate and the whole thing cheap to run.

- 📊 **Live demo data included** — clone, run one command, open the site.
- 📧 **Email alerts** showing *product name, size, website, direct link, price*.
- 🔎 **Multi-store comparison** with size / colour / brand awareness.
- 🧭 **Scoped to 30 flagship brands** for precision and efficiency.
- ⚖️ **Legal by design** — official APIs + affiliate datafeeds + polite,
  robots.txt-respecting fetching. **No CAPTCHA/anti-bot evasion.**

---

## Why "legal by design"? (and how apps like Honey really work)

The brief asked how deal apps like **Honey** manage to do this. The important,
often-misunderstood answer: **Honey does not defeat anti-bot systems.** It runs
as a **browser extension inside the user's own logged-in session**, so it never
faces CAPTCHAs, and its price/coupon data comes from **affiliate partnerships**
and crowdsourced codes — not mass scraping. ([Wikipedia][honey-wiki], [Snopes][honey-snopes])

So this engine follows the same sustainable playbook instead of trying to evade
protections (which violates Terms of Service / the CFAA / DMCA §1201, breaks
constantly, and gets your IPs banned):

| Source | How we read prices — legitimately |
| --- | --- |
| **eBay** | Official **Browse API** (OAuth client-credentials). ([docs][ebay]) |
| **Amazon** | Official **Product Advertising API 5.0** (Associates + SigV4). |
| **REI / Backcountry / Patagonia / brand DTC** | **Affiliate product datafeeds** via AvantLink / Impact / CJ — explicitly meant for comparison sites. ([AvantLink][avantlink]) |
| **Other stores** | *Polite* HTML fetching that honours `robots.txt`, rate-limits, identifies itself, and **backs off** on any challenge. |

👉 Full rationale in **[docs/ENFOQUE-LEGAL-Y-COMO-LO-HACE-HONEY.md](docs/ENFOQUE-LEGAL-Y-COMO-LO-HACE-HONEY.md)** (Español).

---

## How it works

```mermaid
flowchart LR
  subgraph GitHub Actions (cron, free)
    A[watchlist.json] --> B[Connectors]
    B -->|eBay API| B
    B -->|Amazon PA-API| B
    B -->|Affiliate feeds| B
    B -->|sample demo| B
    B --> C[Normalize + match<br/>brand / size / colour]
    C --> D[Deal detector<br/>vs target & price history]
    D --> E[(data/ = the database<br/>committed back to git)]
    D --> F[📧 Email alerts]
    E --> G[web/data/*.json snapshot]
  end
  G --> H[[GitHub Pages<br/>static comparison site]]
```

On the free tier there is no database — **the git repo is the store.** Each
scheduled run commits updated prices back, so price history (and therefore deal
detection) survives between runs, and the diff doubles as an audit log.

---

## Quick start (local)

```bash
pip install -r requirements.txt

# optional: seed ~30 days of demo price history so sparklines look real
python scripts/seed_demo.py 30

# run one collection cycle (uses the built-in demo source; no keys needed)
python -m engine.run --no-email

# preview the website
cd web && python -m http.server 8000     # open http://localhost:8000
```

**Instant sandbox:** open **`web/sandbox.html`** directly in a browser — a single
self-contained file with demo data, search, brand filter and price comparison
baked in (no server, no build). Regenerate it after changing data with
`python scripts/build_sandbox.py`.

Run the tests:

```bash
python -m tests.test_normalize
python -m tests.test_dealdetector
python -m tests.test_http
python -m tests.test_validate
# or, if you have pytest:  pytest -q
```

**Backend tooling**

```bash
python -m engine.validate                 # check data/watchlist.json (ids, brands, types)
python -m engine.probe sample --id arcteryx_beta_ar_jacket   # inspect one source
python -m engine.probe ebay --brand "Patagonia" --name "Nano Puff"  # (needs eBay keys)
```

`engine.probe` prints exactly what a single connector returns (or a clear
"missing credential" message) — use it to validate eBay/Amazon/feeds right after
adding secrets, before enabling them for scheduled runs. API connectors go
through a shared resilient HTTP layer (retries + backoff + per-host rate
limiting). A **CI** workflow runs the tests, `validate`, and a demo smoke run on
every push.

---

## Deploy on GitHub (100% free tier)

1. **Push this repo** to GitHub (public repo = unlimited Actions minutes).
2. **Enable Pages**: *Settings → Pages → Build and deployment → Source =
   **GitHub Actions***. The **Deploy site** workflow publishes `web/`.
3. **Enable the schedule**: the **Collect deals** workflow runs every 6 hours
   (and on demand from the Actions tab). It collects, emails new deals, and
   commits fresh prices — which re-triggers the site deploy.
4. **Configure email + sources** with repository *Secrets* and *Variables*
   (below). With none set, it runs in safe **dry-run** mode.

That's it — no servers, no database, no paid services.

---

## Configuration

### Watchlist — `data/watchlist.json`
The products you track. Empty `sizes`/`colors` mean *any variant*.
`target_price` (USD) triggers an alert at or below it; omit it to rely on
statistical drop detection.

```json
{
  "id": "arcteryx_beta_ar_jacket",
  "brand": "Arc'teryx",
  "name": "Beta AR Jacket",
  "category": "Hardshell",
  "sizes": ["M", "L"],
  "colors": ["black", "blue"],
  "target_price": 449.00,
  "keywords": ["gore-tex", "pro", "shell"]
}
```

### Settings — `config.yml`
Brands, detection thresholds, which sources are on, email options. Secrets are
**never** stored here — they come from the environment. See the inline comments.

Key detection knobs:
- `min_discount_pct` (15) / `suspect_discount_pct` (68) — the objective band is
  **15–60%** off; above ~68% is treated as *suspect* (likely a wrong match or a
  price error) and only surfaces on a near-certain product match.
- `baseline_percentile` (85) — the *regular* (non-sale) price is a high
  percentile of recent prices plus MSRP / believable "was" price, so a
  sale-heavy item's median can't fake a discount.
- `require_in_stock`, `include_used`, `max_offer_age_days` — only compare
  "the same article, new, in stock, fresh".
- `min_match_score` (0.6) / `suspect_min_match_score` (0.9), `alert_ttl_days` (7).

**Identity graph & regional scope.** Offers are clustered into the same canonical
article across channels — new / **outlet** / **refurbished** / used (used excluded
by default) — and across regions. **Model lineage** (`lineage` on a watch item)
lets previous-season/renamed SKUs resolve to the same product, so last-year's
colourway counts. Search runs in two scopes: **standard** (US) or **expanded**
(US + Canada + Europe). European brands (Peak Performance, Helly Hansen, Norrøna,
Rab, Mammut, Scarpa…) and Arc'teryx (Canada) are often cheapest in their **home
market**, which expanded scope surfaces and flags — international shipping is the
buyer's known cost and is deliberately *not* penalised. Toggle with
`search.scope` or `python -m engine.run --scope expanded`.

**Effective landed cost (rank by what you actually pay).** The detector doesn't
compare sticker prices — it computes each offer's *effective* price after
stacking every legitimate lever (coupon + cashback + gift-card discount +
shipping + tax − loyalty rewards) and ranks by that. A 10%-off sale plus a 15%
coupon, 6% cashback and free shipping can beat a flashier 25%-off elsewhere.
Retailer modifiers and active coupons live in `data/promos.json` (delete it to
disable stacking). The *suspect* guard stays on the raw price, so a legitimately
stacked discount is never mistaken for a price error.

**Seasonality (buy off-season).** In summer, winter gear (down / hardshell /
mountaineering) hits end-of-season clearance — and vice-versa. The engine infers
each product's season from its category (or an explicit `season` on the item),
knows the current season for your `hemisphere`, and **ranks off-season deals
higher** (surfacing them a bit earlier too). Every deal gets a 0–100 **score**
and a **tier** (good / great / excellent / suspect) so you act on the best first;
it also tags known sale windows (Black Friday, REI Anniversary, end-of-season).

**Performance & observability.** Sources are fetched **concurrently**
(`performance.max_workers`) with a per-source **time budget** (a slow source
stops being called instead of stalling the run), on top of the resilient HTTP
layer. Every run writes `data/status.json` (durations, per-source health, counts).

**Reliable extra source (no API gate).** `sources.structured` reads the
**schema.org JSON-LD** a retailer publishes on the product pages you list on a
watch item (`urls`) — authoritative price/availability/GTIN, fetched politely
(robots.txt + rate limits). **Community signals** are handled *with tweezers*:
they are low-trust **leads that must be corroborated by a real observed price**
before they count (see `engine/community.py`), and are off by default.

**Decision brain — don't manufacture illusions.** A deep discount isn't always
an opportunity. Believability depends on **brand tier × channel × depth**: a
cult/niche brand (Peak Performance, Helly Hansen, Mammut, Arc'teryx…) shown −50%
*new* on a **resale marketplace** is almost certainly not genuine/new — it's
flagged **suspect** and never presented as a buy. A **mass** brand (The North
Face, Columbia, REI Co-op) *can* legitimately be dumped cheap on resale, so it
stays credible. On top of credibility the brain reads the item's price history
and returns **Buy / Wait / Hold** with a confidence, and marks legit cult/premium
authorized deals **⚡ flash** (they sell out fast). Suspect and "hold" deals are
kept **out of the email by default** (they still show on the site, flagged) so
alerts never create false hopes.

### Turning on real sources
Set `enabled: true` under `sources.<name>` in `config.yml` and provide the
credentials as environment variables / GitHub Secrets:

| Source | Env vars |
| --- | --- |
| eBay | `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` |
| Amazon | `AMAZON_ACCESS_KEY`, `AMAZON_SECRET_KEY`, `AMAZON_PARTNER_TAG` |
| Affiliate feeds | add `feeds:` entries (feed URL + column mapping) — no secret needed if the feed URL is tokenised |

**eBay (production-ready).** Create a free app at
[developer.ebay.com](https://developer.ebay.com/) (Application keysets → Client
ID + Secret), add the two secrets, and set `sources.ebay.enabled: true`. Then:

```bash
python -m engine.probe ebay --id arcteryx_beta_ar_jacket   # verify creds live
```

Because eBay is a **marketplace**, each listing is mapped to `new` / `used` /
`refurbished` (eBay's "New other", "Like new" and refurbished tiers are *not*
treated as genuine new), and tagged with its region + currency. This feeds the
cautious brain directly: a cult brand shown "−55% new" on eBay is flagged
**suspect → HOLD** and kept out of email, while a mass brand at the same price
stays a credible **BUY**. With `search.scope: expanded` the connector
auto-queries several eBay sites (US + GB + DE + CA) so home-market deals surface.

### Email transport (auto-detected from env, first match wins)

| Transport | Env vars |
| --- | --- |
| **Gmail** (simplest) | `GMAIL_USER`, `GMAIL_APP_PASSWORD` |
| SMTP | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` |
| SendGrid | `SENDGRID_API_KEY` (+ `ALERT_EMAIL_FROM`) |
| Resend | `RESEND_API_KEY` (+ `ALERT_EMAIL_FROM`) |

Recipients: `email.to` in `config.yml`, or the `ALERT_EMAIL_TO` variable
(comma-separated). With Gmail configured and no explicit recipient, alerts go to
`GMAIL_USER` (your own inbox). With no transport/recipients it renders the email
to `dist/last_email.html` instead of sending.

**Gmail in 2 steps** (alerts land in your inbox, free):

1. Enable 2-Step Verification, then create an **App Password** at
   <https://myaccount.google.com/apppasswords> (a 16-char password, *not* your
   login password).
2. Repo → *Settings → Secrets and variables → Actions → New repository secret*:
   `GMAIL_USER` = your address, `GMAIL_APP_PASSWORD` = the App Password.

### Storage stays bounded (the repo is the database)

Because every run commits data back to git, the stores are self-limiting so the
repo never bloats and cron diffs stay small:

- **Price history** is trimmed on every write — one observation per source per
  day (`history_daily_downsample`), dropped after `history_retention_days` (180),
  with a hard `history_max_points` ceiling. Repeated runs the same day don't grow
  the file.
- **Alert ledger** keeps only a rolling `alert_ttl_days` window; expired keys
  (which no longer suppress re-alerts) are pruned instead of piling up forever.
- Writes are **atomic** (temp file + `os.replace`), so a killed run can't corrupt
  the store. HTTP is stateless — no sessions or cookies accumulate.

---

## Covered brands

The North Face · Black Diamond · Patagonia · Ansilta · Deuter · Outdoor
Research · Mammut · Arc'teryx · Mountain Hardwear · Marmot · Rab · Fjällräven ·
Norrøna · Salewa · Ortovox · Montbell · Columbia · Helly Hansen · Petzl · La
Sportiva · Peak Performance · Osprey · Gregory · Exped · Scarpa · Salomon ·
Lowa · Asolo · Montagne

Each brand ships with alias/misspelling handling (e.g. `arcteryx` → *Arc'teryx*,
`scaroa` → *Scarpa*, `fjallraven` → *Fjällräven*). Add or edit brands in
`engine/normalize.py`.

---

## Project structure

```
engine/                 Python collection engine
  models.py             dataclasses: WatchItem, Offer, Deal, PricePoint
  normalize.py          brand/size/colour normalisation + fuzzy matching
  config.py             config.yml loader (+ env overrides for secrets)
  store.py              JSON store, price history, website snapshot
  dealdetector.py       scored, seasonal, effective-cost detection (v3)
  seasons.py            off-season logic + sale windows (buy counter-seasonal)
  pricing.py            robust "regular price" + currency normalisation
  effective.py          landed-cost stacking (coupon+cashback+gift-card+ship+tax)
  identity.py           product identity graph: channel/region + model lineage
  http.py               shared resilient HTTP (retries, backoff, rate-limit)
  metrics.py            thread-safe run metrics + per-source time budgets
  community.py          community signals as corroborated leads (anti fake-news)
  credibility.py        brand-tier × channel × depth believability ("no ilusionar")
  brain.py              Buy / Wait / Hold decision + confidence + flash
  run.py                orchestrator + CLI (concurrent; python -m engine.run)
  probe.py              inspect a single source (python -m engine.probe)
  validate.py           watchlist validation (python -m engine.validate)
  connectors/           sample · ebay · amazon · affiliate_feed · structured · polite_html
  notify/email.py       Gmail / SMTP / SendGrid / Resend / dry-run alerts
data/                   watchlist.json + committed price history (the "database")
web/                    static GitHub Pages site (search / compare / deals)
scripts/seed_demo.py    generate backdated demo history
tests/                  unit tests for normalisation & detection
.github/workflows/      collect.yml (cron) + deploy-pages.yml + ci.yml (tests)
docs/                   operator guide · legal/Honey explainer · autonomous-engine
                        architecture & grey-zone strategy (Español)
```

---

## Limitations & honest notes

- The **demo source is synthetic** — turn on eBay/Amazon/affiliate feeds for
  real prices. The site shows a *"Modo demo"* badge until you do.
- The **Amazon** connector's SigV4 signing is implemented to spec but should be
  validated the first time against your live keys.
- Affiliate feeds require you to be an **approved affiliate** of each program.
- Matching is deliberately conservative (`min_match_score`); tune per source.

---

## License

MIT — see `LICENSE`. Retailer names/brands belong to their respective owners;
this tool only reads pricing you're authorised to access.

[honey-wiki]: https://en.wikipedia.org/wiki/PayPal_Honey
[honey-snopes]: https://www.snopes.com/news/2024/12/30/honey-browser-extension-scam/
[ebay]: https://developer.ebay.com/api-docs/buy/browse/overview.html
[avantlink]: https://support.avantlink.com/hc/en-us/articles/4404406207501-Datafeed-Manager-Affiliate-User-Guide-Product-Datafeeds
