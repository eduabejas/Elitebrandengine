/* Elite Brand Engine — front-end. Zero dependencies; reads the JSON snapshot
   the Python engine writes to ./data/. Runs entirely client-side on GitHub Pages. */

(() => {
  "use strict";

  const state = {
    meta: null,
    products: [],
    deals: [],
    byId: new Map(),
    view: "deals",
    search: "",
    brands: new Set(),   // active brand filters (empty = all)
    sort: "discount",
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const deburr = (s) =>
    (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  let fmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const money = (n, cur) => {
    if (n == null) return "—";
    try {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(n);
    } catch { return `$${Number(n).toFixed(2)}`; }
  };

  // Deterministic alpine-ish gradient per brand (used as placeholder art).
  function brandArt(brand) {
    let h = 0;
    for (const c of brand) h = (h * 31 + c.charCodeAt(0)) % 360;
    const h2 = (h + 40) % 360;
    return `linear-gradient(135deg, hsl(${h} 45% 24%), hsl(${h2} 50% 16%)),
            radial-gradient(120px 60px at 78% 120%, hsl(${h} 55% 40% / .5), transparent)`;
  }

  // --- Data load ---------------------------------------------------------- //
  async function load() {
    try {
      const [meta, products, deals] = await Promise.all([
        fetch("./data/meta.json").then((r) => r.json()),
        fetch("./data/products.json").then((r) => r.json()),
        fetch("./data/deals.json").then((r) => r.json()),
      ]);
      state.meta = meta;
      state.products = products.products || [];
      state.deals = deals.deals || [];
      state.byId = new Map(state.products.map((p) => [p.id, p]));
      if (meta.currency) fmt = new Intl.NumberFormat("en-US", { style: "currency", currency: meta.currency });
      hydrateChrome();
      renderBrandChips();
      render();
    } catch (err) {
      $("#grid").innerHTML =
        `<div class="empty">No se pudieron cargar los datos (${err}).<br>
         Ejecuta <code>python -m engine.run</code> para generar <code>web/data/*.json</code>.</div>`;
    }
  }

  function hydrateChrome() {
    const m = state.meta || {};
    if (m.site) {
      $("#site-title").textContent = m.site.title || "Elite Brand Engine";
      $("#site-tagline").textContent = m.site.tagline || "";
    }
    $("#demo-badge").hidden = !m.demo;
    if (m.generated_at) {
      const d = new Date(m.generated_at);
      $("#updated").textContent = "Actualizado " + d.toLocaleString("es", {
        dateStyle: "medium", timeStyle: "short",
      });
    }
    $("#stat-products").textContent = m.product_count ?? state.products.length;
    $("#stat-deals").textContent = m.deal_count ?? state.deals.length;
    $("#stat-offers").textContent = m.offer_count ?? "—";
    const srcs = (m.sources || []).filter((s) => s.available);
    $("#stat-sources").textContent = srcs.length || "—";
    $("#sources").innerHTML = (m.sources || [])
      .map((s) => `<span class="source-pill ${s.available ? "" : "off"}">${s.name}${
        s.available ? ` · ${s.offers}` : " · off"}</span>`)
      .join("") || "—";
  }

  function renderBrandChips() {
    const counts = new Map();
    for (const p of state.products) counts.set(p.brand, (counts.get(p.brand) || 0) + 1);
    const brands = Array.from(counts.keys()).sort();
    $("#brand-filters").innerHTML = brands
      .map((b) => `<button class="chip" data-brand="${b}">${b}</button>`)
      .join("");
    $$("#brand-filters .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const b = chip.dataset.brand;
        if (state.brands.has(b)) state.brands.delete(b);
        else state.brands.add(b);
        chip.classList.toggle("is-on");
        render();
      });
    });
  }

  // --- Filtering / sorting ------------------------------------------------ //
  function matchesSearch(text) {
    if (!state.search) return true;
    return deburr(text).includes(state.search);
  }

  function filteredDeals() {
    let items = state.deals.filter((d) => {
      if (state.brands.size && !state.brands.has(d.brand)) return false;
      return matchesSearch(`${d.brand} ${d.product_name} ${d.source} ${d.size || ""} ${d.color || ""}`);
    });
    return sortItems(items, (d) => d.discount_pct || 0, (d) => d.price, (d) => d.brand);
  }

  function filteredProducts() {
    let items = state.products.filter((p) => {
      if (state.brands.size && !state.brands.has(p.brand)) return false;
      return matchesSearch(`${p.brand} ${p.name} ${p.category} ${(p.keywords || []).join(" ")}`);
    });
    return sortItems(items, (p) => bestDiscount(p), (p) => p.best_price ?? Infinity, (p) => p.brand);
  }

  function sortItems(items, discountFn, priceFn, brandFn) {
    const s = state.sort;
    const arr = items.slice();
    if (s === "discount") arr.sort((a, b) => discountFn(b) - discountFn(a));
    else if (s === "price_asc") arr.sort((a, b) => priceFn(a) - priceFn(b));
    else if (s === "price_desc") arr.sort((a, b) => priceFn(b) - priceFn(a));
    else if (s === "brand") arr.sort((a, b) => brandFn(a).localeCompare(brandFn(b)));
    return arr;
  }

  function bestDiscount(p) {
    let best = 0;
    for (const d of state.deals) if (d.watch_id === p.id && d.discount_pct) best = Math.max(best, d.discount_pct);
    return best;
  }

  // --- Rendering ---------------------------------------------------------- //
  function render() {
    const grid = $("#grid");
    const items = state.view === "deals" ? filteredDeals() : filteredProducts();
    $("#empty").hidden = items.length > 0;
    grid.innerHTML = state.view === "deals"
      ? items.map(dealCard).join("")
      : items.map(productCard).join("");
    $$("[data-open]", grid).forEach((el) =>
      el.addEventListener("click", () => openModal(el.dataset.open)));
  }

  function dealCard(d) {
    const was = d.reference_price ? `<span class="price-was">${money(d.reference_price, d.currency)}</span>` : "";
    const disc = d.discount_pct ? `<div class="discount-tag">-${Math.round(d.discount_pct)}%</div>` : "";
    const cond = d.condition && d.condition !== "new" ? `<span class="cond-used">${d.condition}</span>` : "";
    const variant = [d.size ? `Talla <b>${d.size}</b>` : "", d.color ? cap(d.color) : ""].filter(Boolean).join(" · ");
    return `
    <article class="card">
      <div class="card-media" style="background:${brandArt(d.brand)}">
        ${disc}
        <span class="card-cat">${escapeHtml(catOf(d.watch_id))}</span>
        <span class="card-brand">${escapeHtml(d.brand)}</span>
      </div>
      <div class="card-body">
        <h3 class="card-name">${escapeHtml(d.product_name)}</h3>
        <div class="variant">${variant || "&nbsp;"} ${cond}</div>
        <div class="reason">${escapeHtml(d.reason || "")}</div>
        <div class="price-row">
          <span class="price">${money(d.price, d.currency)}</span> ${was}
          <span class="src-badge">${escapeHtml(d.source)}</span>
        </div>
        <div class="card-actions">
          <a class="btn btn-primary" href="${escapeAttr(d.url)}" target="_blank" rel="noopener">Ver oferta →</a>
          <button class="btn btn-ghost" data-open="${escapeAttr(d.watch_id)}">Comparar</button>
        </div>
      </div>
    </article>`;
  }

  function productCard(p) {
    const disc = bestDiscount(p);
    const tag = disc ? `<div class="discount-tag">-${Math.round(disc)}%</div>` : "";
    return `
    <article class="card">
      <div class="card-media" style="background:${brandArt(p.brand)}">
        ${tag}
        <span class="card-cat">${escapeHtml(p.category || "")}</span>
        <span class="card-brand">${escapeHtml(p.brand)}</span>
      </div>
      <div class="card-body">
        <h3 class="card-name">${escapeHtml(p.name)}</h3>
        <div class="variant">${p.offer_count} oferta(s)${p.best_source ? ` · mejor en <b>${escapeHtml(p.best_source)}</b>` : ""}</div>
        <div class="price-row">
          <span class="price">${money(p.best_price, p.currency)}</span>
          ${p.target_price ? `<span class="src-badge">objetivo ${money(p.target_price, p.currency)}</span>` : ""}
        </div>
        <div class="card-actions">
          <button class="btn btn-primary" data-open="${escapeAttr(p.id)}">Comparar precios</button>
        </div>
      </div>
    </article>`;
  }

  function catOf(id) { const p = state.byId.get(id); return p ? p.category : ""; }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  // --- Modal (per-product comparison) ------------------------------------- //
  function openModal(id) {
    const p = state.byId.get(id);
    if (!p) return;
    const offers = (p.offers || []).slice().sort((a, b) => a.price - b.price);
    const best = offers[0];
    const rows = offers.map((o, i) => `
      <tr class="${i === 0 ? "best" : ""}">
        <td>${escapeHtml(o.source)}${o.condition && o.condition !== "new" ? ` <span class="cond-used">(${o.condition})</span>` : ""}</td>
        <td>${o.size ? escapeHtml(o.size) : "—"}</td>
        <td>${o.color ? cap(escapeHtml(o.color)) : "—"}</td>
        <td class="offer-price">${money(o.price, o.currency)}${o.list_price ? ` <span class="price-was">${money(o.list_price, o.currency)}</span>` : ""}</td>
        <td><a class="mini-link" href="${escapeAttr(o.url)}" target="_blank" rel="noopener">Abrir →</a></td>
      </tr>`).join("");

    const dealsFor = state.deals.filter((d) => d.watch_id === id);
    const dealNote = dealsFor.length
      ? `<div class="reason" style="margin:2px 0 12px">🔥 ${dealsFor.length} oferta(s) activa(s) — mejor: ${escapeHtml(dealsFor.map(d=>d.reason).sort()[0]||"")}</div>`
      : "";

    $("#modal-body").innerHTML = `
      <h3 class="modal-title" id="modal-title">${escapeHtml(p.brand)} — ${escapeHtml(p.name)}</h3>
      <div class="modal-sub">${escapeHtml(p.category || "")}${best ? ` · mejor precio ${money(best.price, best.currency)} en ${escapeHtml(best.source)}` : ""}</div>
      ${dealNote}
      <table class="offer-table">
        <thead><tr><th>Tienda</th><th>Talla</th><th>Color</th><th>Precio</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5">Sin ofertas registradas.</td></tr>`}</tbody>
      </table>
      ${sparkline(p.history)}`;
    const modal = $("#modal");
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    $("#modal").hidden = true;
    document.body.style.overflow = "";
  }

  function sparkline(history) {
    const pts = (history || []).filter((h) => typeof h.price === "number");
    if (pts.length < 2) return "";
    const w = 560, h = 60, pad = 6;
    const prices = pts.map((p) => p.price);
    const min = Math.min(...prices), max = Math.max(...prices);
    const span = max - min || 1;
    const step = (w - pad * 2) / (pts.length - 1);
    const coords = pts.map((p, i) => {
      const x = pad + i * step;
      const y = pad + (h - pad * 2) * (1 - (p.price - min) / span);
      return [x, y];
    });
    const path = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const area = `${path} L${coords[coords.length-1][0].toFixed(1)},${h-pad} L${coords[0][0].toFixed(1)},${h-pad} Z`;
    const last = coords[coords.length - 1];
    return `
      <div class="hist-wrap">
        <h4>Historial de precio (${money(min)} – ${money(max)})</h4>
        <svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Historial de precio">
          <path d="${area}" fill="rgba(46,163,111,.14)" />
          <path d="${path}" fill="none" stroke="#2ea36f" stroke-width="2" />
          <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" fill="#2ea36f" />
        </svg>
      </div>`;
  }

  // --- Escaping helpers --------------------------------------------------- //
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/`/g, "&#96;"); }

  // --- Wiring ------------------------------------------------------------- //
  function wire() {
    $$(".tab").forEach((tab) =>
      tab.addEventListener("click", () => {
        $$(".tab").forEach((t) => t.classList.remove("is-active"));
        tab.classList.add("is-active");
        state.view = tab.dataset.view;
        render();
      }));
    let t;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { state.search = deburr(e.target.value.trim()); render(); }, 130);
    });
    $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; render(); });
    $$("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  }

  wire();
  load();
})();
