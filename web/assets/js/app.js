/* Elite Brand Engine — front-end. Zero dependencies; reads the JSON snapshot
   the Python engine writes to ./data/. Search-first: predictive suggestions +
   an exclusive brand filter that scopes the whole dataset to one brand. */

(() => {
  "use strict";

  const state = {
    meta: null,
    products: [],
    deals: [],
    byId: new Map(),
    view: "deals",
    search: "",
    brand: null,        // exclusive brand filter (null = all brands)
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const deburr = (s) =>
    (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  const money = (n, cur) => {
    if (n == null) return "—";
    try {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: cur || (state.meta && state.meta.currency) || "USD" }).format(n);
    } catch { return `$${Number(n).toFixed(2)}`; }
  };

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
      hydrateChrome();
      buildBrandMenu();
      render();
    } catch (err) {
      $("#grid").innerHTML =
        `<div class="empty">No se pudieron cargar los datos (${err}).<br>
         Ejecutá <code>python -m engine.run</code> para generar <code>web/data/*.json</code>.</div>`;
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
      $("#updated").textContent = "Actualizado " + d.toLocaleString("es", { dateStyle: "medium", timeStyle: "short" });
    }
    $("#deals-count").textContent = m.deal_count ?? state.deals.length;
    const srcs = (m.sources || []);
    $("#foot-stats").textContent =
      `${m.product_count ?? state.products.length} productos · ${m.offer_count ?? "—"} precios comparados · ${srcs.filter((s) => s.available).length} tiendas`;
    $("#sources").innerHTML = srcs
      .map((s) => `<span class="source-pill ${s.available ? "" : "off"}">${s.name}${s.available ? ` · ${s.offers}` : " · off"}</span>`)
      .join("") || "—";
  }

  // --- Brand filter (exclusive) ------------------------------------------- //
  function buildBrandMenu() {
    const counts = new Map();
    for (const p of state.products) counts.set(p.brand, (counts.get(p.brand) || 0) + 1);
    const brands = Array.from(counts.keys()).sort();
    const menu = $("#brand-menu");
    const item = (label, brand, n) =>
      `<li role="option" data-brand="${brand === null ? "" : escapeAttr(brand)}" class="${state.brand === brand ? "is-active" : ""}">
        <span>${escapeHtml(label)}</span>${n != null ? `<span class="n">${n}</span>` : ""}</li>`;
    menu.innerHTML =
      item("Todas las marcas", null, state.products.length) +
      brands.map((b) => item(b, b, counts.get(b))).join("");
    $$("#brand-menu li").forEach((li) =>
      li.addEventListener("click", () => selectBrand(li.dataset.brand || null)));
  }

  function selectBrand(brand) {
    state.brand = brand;
    $("#brand-btn-label").textContent = brand || "Todas las marcas";
    $("#brand-btn").classList.toggle("is-set", !!brand);
    closeBrandMenu();
    buildBrandMenu();            // refresh active highlight
    renderSuggestions();         // scope predictions to the brand
    render();
  }

  function toggleBrandMenu(force) {
    const menu = $("#brand-menu");
    const open = force != null ? force : menu.hidden;
    menu.hidden = !open;
    $("#brand-btn").setAttribute("aria-expanded", String(open));
  }
  const closeBrandMenu = () => toggleBrandMenu(false);

  // --- Predictive suggestions --------------------------------------------- //
  function computeSuggestions(q) {
    q = deburr(q.trim());
    if (!q) return [];
    let pool = state.products;
    if (state.brand) pool = pool.filter((p) => p.brand === state.brand);
    const scored = [];
    for (const p of pool) {
      const hay = deburr(`${p.brand} ${p.name} ${p.category} ${(p.keywords || []).join(" ")}`);
      const idx = hay.indexOf(q);
      if (idx >= 0) scored.push([idx, p]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name));
    return scored.slice(0, 10).map((s) => s[1]);
  }

  function renderSuggestions() {
    const box = $("#suggestions");
    const q = $("#search").value;
    const items = computeSuggestions(q);
    if (!q.trim() || items.length === 0) { box.hidden = true; box.innerHTML = ""; $("#search").setAttribute("aria-expanded", "false"); return; }
    box.hidden = false;
    box.innerHTML = items
      .map((p) => `<button class="sugg" data-pick="${escapeAttr(p.id)}">
          <span class="sugg-brand">${escapeHtml(p.brand)}</span> <b>${escapeHtml(p.name)}</b></button>`)
      .join("");
    $$(".sugg", box).forEach((el) => el.addEventListener("click", () => pickSuggestion(el.dataset.pick)));
    $("#search").setAttribute("aria-expanded", "true");
  }

  function pickSuggestion(id) {
    const p = state.byId.get(id);
    if (!p) return;
    $("#search").value = p.name;
    state.search = deburr(p.name);
    $("#search-clear").hidden = false;
    $("#suggestions").hidden = true;
    render();
    openModal(id);               // deliver the payoff: the price comparison
  }

  // --- Filtering / rendering ---------------------------------------------- //
  const matchesSearch = (text) => !state.search || deburr(text).includes(state.search);
  const inBrand = (b) => !state.brand || b === state.brand;

  function bestDiscount(p) {
    let best = 0;
    for (const d of state.deals) if (d.watch_id === p.id && d.discount_pct) best = Math.max(best, d.discount_pct);
    return best;
  }

  function currentItems() {
    if (state.view === "deals") {
      return state.deals
        .filter((d) => inBrand(d.brand) && matchesSearch(`${d.brand} ${d.product_name} ${d.source} ${d.size || ""} ${d.color || ""}`))
        .sort((a, b) => (b.discount_pct || 0) - (a.discount_pct || 0));
    }
    return state.products
      .filter((p) => inBrand(p.brand) && matchesSearch(`${p.brand} ${p.name} ${p.category} ${(p.keywords || []).join(" ")}`))
      .sort((a, b) => bestDiscount(b) - bestDiscount(a) || a.brand.localeCompare(b.brand));
  }

  function render() {
    const grid = $("#grid");
    const items = currentItems();
    const noun = state.view === "deals" ? "oferta" : "producto";
    $("#result-info").textContent =
      `${items.length} ${noun}${items.length === 1 ? "" : "s"}` + (state.brand ? ` · ${state.brand}` : "");
    grid.innerHTML = state.view === "deals" ? items.map(dealCard).join("") : items.map(productCard).join("");
    $$("[data-open]", grid).forEach((el) => el.addEventListener("click", () => openModal(el.dataset.open)));
    renderEmpty(items.length);
  }

  function catalogMatchCount() {
    return state.products.filter((p) =>
      inBrand(p.brand) && matchesSearch(`${p.brand} ${p.name} ${p.category} ${(p.keywords || []).join(" ")}`)).length;
  }

  function renderEmpty(count) {
    const empty = $("#empty");
    if (count > 0) { empty.hidden = true; return; }
    empty.hidden = false;
    // Browsing "Ofertas" with a query that matches products but has no active
    // deal: guide the user to the catalog instead of a dead end.
    if (state.view === "deals" && state.search) {
      const n = catalogMatchCount();
      if (n > 0) {
        empty.innerHTML = `Sin ofertas activas para tu búsqueda. <button class="btn btn-ghost" id="goto-catalog">Ver ${n} en el catálogo →</button>`;
        $("#goto-catalog").addEventListener("click", () => switchView("catalog"));
        return;
      }
    }
    empty.textContent = "Sin resultados. Probá con otro nombre o cambiá la marca.";
  }

  function switchView(v) {
    state.view = v;
    $$(".view-link").forEach((t) => t.classList.toggle("is-active", t.dataset.view === v));
    render();
  }

  function dealCard(d) {
    const was = d.reference_price ? `<span class="price-was">${money(d.reference_price, d.currency)}</span>` : "";
    const disc = d.discount_pct ? `<div class="discount-tag">-${Math.round(d.discount_pct)}%</div>` : "";
    const cond = d.condition && d.condition !== "new" ? `<span class="cond-used">${d.condition}</span>` : "";
    const variant = [d.size ? `Talla <b>${escapeHtml(d.size)}</b>` : "", d.color ? cap(escapeHtml(d.color)) : ""].filter(Boolean).join(" · ");
    return `
    <article class="card">
      <div class="card-media" style="background:${brandArt(d.brand)}">
        ${disc}<span class="card-cat">${escapeHtml(catOf(d.watch_id))}</span>
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
        ${tag}<span class="card-cat">${escapeHtml(p.category || "")}</span>
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

  const catOf = (id) => { const p = state.byId.get(id); return p ? p.category : ""; };
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

  // --- Modal -------------------------------------------------------------- //
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
      ? `<div class="reason" style="margin:2px 0 12px">🔥 ${dealsFor.length} oferta(s) activa(s) — ${escapeHtml(dealsFor.map((d) => d.reason).sort()[0] || "")}</div>` : "";
    $("#modal-body").innerHTML = `
      <h3 class="modal-title" id="modal-title">${escapeHtml(p.brand)} — ${escapeHtml(p.name)}</h3>
      <div class="modal-sub">${escapeHtml(p.category || "")}${best ? ` · mejor precio ${money(best.price, best.currency)} en ${escapeHtml(best.source)}` : ""}</div>
      ${dealNote}
      <table class="offer-table">
        <thead><tr><th>Tienda</th><th>Talla</th><th>Color</th><th>Precio</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5">Sin ofertas registradas.</td></tr>`}</tbody>
      </table>
      ${sparkline(p.history)}`;
    $("#modal").hidden = false;
    document.body.style.overflow = "hidden";
  }
  function closeModal() { $("#modal").hidden = true; document.body.style.overflow = ""; }

  function sparkline(history) {
    const pts = (history || []).filter((h) => typeof h.price === "number");
    if (pts.length < 2) return "";
    const w = 560, h = 60, pad = 6;
    const prices = pts.map((p) => p.price);
    const min = Math.min(...prices), max = Math.max(...prices), span = max - min || 1;
    const step = (w - pad * 2) / (pts.length - 1);
    const coords = pts.map((p, i) => [pad + i * step, pad + (h - pad * 2) * (1 - (p.price - min) / span)]);
    const path = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const area = `${path} L${coords[coords.length - 1][0].toFixed(1)},${h - pad} L${coords[0][0].toFixed(1)},${h - pad} Z`;
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

  // --- Escaping ----------------------------------------------------------- //
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const escapeAttr = (s) => escapeHtml(s).replace(/`/g, "&#96;");

  // --- Wiring ------------------------------------------------------------- //
  function wire() {
    $$(".view-link").forEach((tab) =>
      tab.addEventListener("click", () => switchView(tab.dataset.view)));

    const input = $("#search");
    let t;
    input.addEventListener("input", () => {
      $("#search-clear").hidden = !input.value;
      clearTimeout(t);
      t = setTimeout(() => { state.search = deburr(input.value.trim()); renderSuggestions(); render(); }, 110);
    });
    input.addEventListener("focus", renderSuggestions);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = computeSuggestions(input.value)[0];
        if (first) { e.preventDefault(); pickSuggestion(first.id); }
      } else if (e.key === "Escape") { $("#suggestions").hidden = true; }
    });
    $("#search-clear").addEventListener("click", () => {
      input.value = ""; state.search = ""; $("#search-clear").hidden = true;
      $("#suggestions").hidden = true; render(); input.focus();
    });

    $("#brand-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleBrandMenu(); });

    // Close menus/suggestions on outside click.
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".brand-select")) closeBrandMenu();
      if (!e.target.closest(".search-input-wrap") && !e.target.closest(".suggestions"))
        $("#suggestions").hidden = true;
    });

    $$("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeBrandMenu(); } });
  }

  wire();
  load();
})();
