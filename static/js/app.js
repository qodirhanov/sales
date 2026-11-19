/* Narx kuzatuvchi — shared front-end helpers (window.NK).
   One place for formatting, API calls, favorites/cart storage, search and the trend chart,
   so pages never re-implement them and failures are always shown to the user. */
(function () {
  "use strict";

  var UNIT_LABEL = { kg: "kg", g: "g", l: "litr", ml: "ml", piece: "dona" };
  var TYPE_LABEL = { bazaar: "Bozor", shop: "Do'kon" };

  /* ---------- formatting / safety ---------- */
  function money(n) { return String(Math.round(Number(n))).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : "#"; }
  function cookie(name) {
    var m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  function ago(iso) {
    var mins = Math.floor((Date.now() - new Date(iso)) / 60000);
    if (mins < 1) return "hozirgina";
    if (mins < 60) return mins + " daqiqa oldin";
    var h = Math.floor(mins / 60);
    if (h < 24) return h + " soat oldin";
    return Math.floor(h / 24) + " kun oldin";
  }

  /* ---------- network ---------- */
  /* Resolves with parsed JSON. Rejects with Error whose .status is the HTTP code
     (0 = no connection) and .data the parsed error body, so callers can tell the cases apart. */
  function request(url, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    if (opts.method && opts.method !== "GET") opts.headers["X-CSRFToken"] = cookie("csrftoken");
    if (opts.json !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { var e = new Error("HTTP " + r.status); e.status = r.status; e.data = data; throw e; }
        return data;
      });
    }, function () { var e = new Error("offline"); e.status = 0; e.data = {}; throw e; });
  }
  /* GET /api/<path>, unwrapping DRF pagination. */
  function api(path) {
    return request("/api/" + path).then(function (d) { return Array.isArray(d) ? d : (d.results !== undefined ? d.results : d); });
  }
  function reason(err) {
    if (err && err.status === 0) return "Internet yo'q shekilli. Ulanishni tekshiring.";
    if (err && err.status === 429) return "Juda tez-tez urinildi. Biroz kutib, qayta urinib ko'ring.";
    if (err && err.status >= 500) return "Serverda xato. Birozdan keyin qayta urinib ko'ring.";
    return "Ma'lumotni yuklab bo'lmadi.";
  }
  /* Show a visible error inside `el`, with a retry button when `retry` is given. */
  function fail(el, err, retry) {
    el.hidden = false;
    el.innerHTML = '<p class="error" role="alert">' + esc(reason(err)) +
      (retry ? ' <button type="button" class="linkbtn" data-retry>Qayta urinish</button>' : "") + "</p>";
    if (retry) el.querySelector("[data-retry]").addEventListener("click", retry);
  }
  var FIELD_LABEL = { price: "Narx", quantity: "Miqdor", unit: "Birlik", location: "Bozor / do'kon",
                      old_price: "Eski narx", source_url: "Havola", product: "Mahsulot" };
  /* DRF 400 body -> short Uzbek sentence (server messages may be English, so only field names are shown). */
  function formProblem(err) {
    if (err.status === 0 || err.status === 429 || err.status >= 500) return reason(err);
    if (err.status === 403) return "Narx qo'shish uchun sotuvchi bo'lishingiz kerak (Profil bo'limida).";
    var names = Object.keys(err.data || {}).map(function (k) { return FIELD_LABEL[k]; }).filter(Boolean);
    return names.length ? "Tekshiring: " + names.join(", ") + "." : "Saqlab bo'lmadi. Maydonlarni tekshiring.";
  }

  /* ---------- price movement ---------- */
  function delta(c) {
    if (!c) return "";
    var n = Math.abs(c.pct);
    var inner = c.dir === "up" ? '<span aria-hidden="true">▲</span> ' + n + '%<span class="sr"> qimmatlashdi</span>'
      : c.dir === "down" ? '<span aria-hidden="true">▼</span> ' + n + '%<span class="sr"> arzonlashdi</span>'
      : '<span aria-hidden="true">＝</span> o&#39;zgarmagan';
    return '<span class="delta delta--' + c.dir + '" title="Oldin: ' + money(c.old_price) + ' so&#39;m">' + inner + "</span>";
  }

  /* ---------- favorites + cart (localStorage) ---------- */
  function load(k, d) { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode: keep in memory */ } }
  var fav = load("nk_fav", []), cart = load("nk_cart", {});

  function sync() {
    document.querySelectorAll("[data-fav]").forEach(function (b) {
      var on = fav.indexOf(Number(b.dataset.fav)) !== -1;
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-label", on ? "Saralanganlardan olib tashlash" : "Saralanganlarga qo'shish");
    });
    document.querySelectorAll("[data-cart]").forEach(function (b) {
      var on = !!cart[b.dataset.cart];
      b.classList.toggle("in", on);
      var l = b.querySelector(".lbl"); if (l) l.textContent = on ? "Savatda ✓" : "Savatga";
    });
    var counts = { fav: fav.length, cart: Object.keys(cart).length };
    document.querySelectorAll("[data-count]").forEach(function (el) {
      var n = counts[el.dataset.count]; el.textContent = n; el.hidden = !n;
    });
  }
  function emit() { sync(); document.dispatchEvent(new CustomEvent("nk:change")); }

  document.addEventListener("click", function (e) {
    var f = e.target.closest("[data-fav]"), c = e.target.closest("[data-cart]");
    if (f && !f.hasAttribute("data-nolisten")) { e.preventDefault(); NK.toggleFav(f.dataset.fav); }
    else if (c && !c.hasAttribute("data-nolisten")) { e.preventDefault(); NK.toggleCart(c.dataset.cart); }
  });
  window.addEventListener("storage", function () { fav = load("nk_fav", []); cart = load("nk_cart", {}); emit(); });
  document.addEventListener("DOMContentLoaded", sync);

  /* Product + its cheapest offer, cached per page. Resolves {p: null} only for a product that no longer exists. */
  var infoCache = {};
  function productInfo(id) {
    if (!infoCache[id]) {
      infoCache[id] = Promise.all([
        request("/api/products/" + id + "/").catch(function (e) { if (e.status === 404) return null; throw e; }),
        request("/api/products/" + id + "/cheapest/?days=30").catch(function (e) { if (e.status === 404) return null; throw e; }),
      ]).then(function (x) { return { p: x[0], offer: x[1] && x[1].results && x[1].results[0] }; })
        .catch(function (e) { delete infoCache[id]; throw e; });
    }
    return infoCache[id];
  }

  /* ---------- trend chart (Chart.js is optional; a text fallback is shown without it) ---------- */
  function trend(o) {
    /* o: {product, district?, unitLabel, canvas, box, empty} */
    var url = "/api/products/" + o.product + "/trend/?days=30" + (o.district ? "&district=" + encodeURIComponent(o.district) : "");
    return request(url).then(function (r) {
      var pts = r.points || [];
      o.box.hidden = true; o.empty.hidden = true;
      if (o.canvas._nk) { o.canvas._nk.destroy(); o.canvas._nk = null; }
      if (!pts.length) { o.empty.hidden = false; o.empty.textContent = "Bu mahsulot uchun hali ma'lumot yo'q."; return; }
      if (!window.Chart) {
        var last = pts[pts.length - 1];
        o.empty.hidden = false;
        o.empty.textContent = "Grafik yuklanmadi. Oxirgi o'rtacha narx: " + money(last.median_price) + " so'm.";
        return;
      }
      o.box.hidden = false;
      var css = getComputedStyle(document.documentElement);
      var ink = css.getPropertyValue("--text").trim(), muted = css.getPropertyValue("--muted").trim(), line = css.getPropertyValue("--line").trim();
      o.canvas._nk = new Chart(o.canvas, {
        type: "line",
        data: {
          labels: pts.map(function (x) { return x.date.slice(5).split("-").reverse().join("."); }),
          datasets: [{
            label: "O'rtacha, so'm/" + o.unitLabel, data: pts.map(function (x) { return Number(x.median_price); }),
            borderColor: ink, backgroundColor: ink, tension: 0.25, pointRadius: 4,
            segment: { borderDash: function (c) { return pts[c.p1DataIndex] && pts[c.p1DataIndex].live ? [5, 4] : undefined; } },
          }],
        },
        options: {
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: function (c) { return money(c.parsed.y) + " so'm" + (pts[c.dataIndex].live ? " (bugun, hali yakunlanmagan)" : ""); } } },
          },
          scales: {
            x: { ticks: { color: muted }, grid: { color: line } },
            y: { ticks: { color: muted, callback: function (v) { return money(v); } }, grid: { color: line } },
          },
        },
      });
    }).catch(function (e) { o.box.hidden = true; fail(o.empty, e, function () { trend(o); }); });
  }

  /* ---------- header search ---------- */
  function initSearch() {
    var q = document.getElementById("nav-search"), box = document.getElementById("search-results");
    if (!q || !box) return;
    var timer = null, ctrl = null, active = -1;
    function close() { box.hidden = true; q.setAttribute("aria-expanded", "false"); active = -1; }
    function items() { return box.querySelectorAll("a"); }
    function open() { box.hidden = false; q.setAttribute("aria-expanded", "true"); active = -1; }
    function mark(i) {
      var a = items(); if (!a.length) return;
      active = (i + a.length) % a.length;
      a.forEach(function (el, n) { el.classList.toggle("active", n === active); });
      a[active].scrollIntoView({ block: "nearest" });
    }
    function show(list) {
      box.innerHTML = list.length
        ? list.map(function (p) { return '<li role="option"><a href="/product/' + p.id + '/">' + esc(p.name) + "<small>" + esc(p.category_name || "") + "</small></a></li>"; }).join("")
        : '<li class="empty-hit">Hech narsa topilmadi. Boshqacha yozib ko&#39;ring.</li>';
      open();
    }
    function run() {
      var v = q.value.trim();
      if (!v) { close(); return; }
      if (ctrl) ctrl.abort();
      ctrl = window.AbortController ? new AbortController() : null;
      request("/api/products/?page_size=8&search=" + encodeURIComponent(v), ctrl ? { signal: ctrl.signal } : {})
        .then(function (d) { if (q.value.trim() === v) show(d.results || []); })
        .catch(function (e) {
          if (e.name === "AbortError") return;
          box.innerHTML = '<li class="empty-hit">' + esc(e.status === 0 ? "Internet yo'q shekilli." : "Qidiruv ishlamadi. Qayta urinib ko'ring.") + "</li>";
          open();
        });
    }
    q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 200); });
    q.addEventListener("focus", function () { if (q.value.trim() && box.innerHTML) box.hidden = false; });
    q.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); mark(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); mark(active - 1); }
      else if (e.key === "Escape") { close(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var t = items()[active >= 0 ? active : 0];
        if (t) window.location.href = t.href; else run();
      }
    });
    document.addEventListener("click", function (e) { if (!e.target.closest(".search")) close(); });
  }

  var NK = window.NK = {
    UNIT_LABEL: UNIT_LABEL, TYPE_LABEL: TYPE_LABEL,
    money: money, esc: esc, safeUrl: safeUrl, cookie: cookie, ago: ago,
    request: request, api: api, fail: fail, formProblem: formProblem, delta: delta,
    productInfo: productInfo, trend: trend, sync: sync,
    favs: function () { return fav.slice(); },
    cart: function () { return Object.assign({}, cart); },
    toggleFav: function (id) { id = Number(id); var i = fav.indexOf(id); if (i === -1) fav.push(id); else fav.splice(i, 1); save("nk_fav", fav); emit(); },
    toggleCart: function (id) { if (cart[id]) delete cart[id]; else cart[id] = 1; save("nk_cart", cart); emit(); },
    setQty: function (id, q) { q = Math.max(0.1, Math.round(q * 100) / 100); if (cart[id]) { cart[id] = q; save("nk_cart", cart); emit(); } },
    removeCart: function (id) { delete cart[id]; save("nk_cart", cart); emit(); },
    clearCart: function () { cart = {}; save("nk_cart", cart); emit(); },
  };
  initSearch();
})();
