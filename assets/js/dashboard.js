/* ==========================================================================
   dashboard.js — interactivity + analytics for the project command center.
   Progressive enhancement: cards/stats are server-rendered by Liquid; this
   adds count-up, scroll reveal, faceted search/filter/sort, and Chart.js
   analytics computed from the DASH_PROJECTS / DASH_HEALTH data islands.
   ========================================================================== */
(function () {
  "use strict";
  var root = document.getElementById("command-center");
  if (!root) return;

  /* ---- count-up on the hero stat tiles ---------------------------------- */
  function countUp(el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (isNaN(target)) { return; }
    var dur = 900, start = null;
    function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      el.textContent = Math.round(target * easeOut(p)).toString();
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = target.toString();
    }
    requestAnimationFrame(step);
  }
  var nums = root.querySelectorAll(".cc-num[data-count]");
  nums.forEach(countUp);
  // failsafe: guarantee final values even if rAF is throttled/interrupted
  setTimeout(function () { nums.forEach(function (el) { el.textContent = el.getAttribute("data-count"); }); }, 1200);

  /* ---- reveal sections on scroll ---------------------------------------- */
  var reveals = root.querySelectorAll(".cc-reveal");
  function revealAll() { reveals.forEach(function (el) { el.classList.add("cc-in"); }); }
  if ("IntersectionObserver" in window) {
    root.classList.add("cc-anim");           // enable the hidden initial state
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("cc-in"); io.unobserve(e.target); } });
    }, { threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });
    setTimeout(revealAll, 1600);             // failsafe: never leave content hidden
  } else {
    revealAll();
  }

  /* ---- faceted search / filter / sort ----------------------------------- */
  var grid = document.getElementById("cc-grid");
  var cards = grid ? Array.prototype.slice.call(grid.querySelectorAll(".cc-card")) : [];
  var search = document.getElementById("cc-search");
  var sortSel = document.getElementById("cc-sort");
  var countEl = document.getElementById("cc-count");
  var emptyEl = document.getElementById("cc-empty");
  var chips = Array.prototype.slice.call(root.querySelectorAll(".cc-chip"));

  function activeFilters() {
    var groups = {};
    chips.forEach(function (c) {
      if (c.getAttribute("aria-pressed") === "true") {
        var g = c.getAttribute("data-group");
        (groups[g] = groups[g] || []).push(c.getAttribute("data-value"));
      }
    });
    return groups;
  }

  function matches(card, q, groups) {
    if (q) {
      var hay = (card.getAttribute("data-name") + " " + card.getAttribute("data-desc") + " " +
                 card.getAttribute("data-stack")).toLowerCase();
      if (hay.indexOf(q) === -1) return false;
    }
    for (var g in groups) {
      if (!groups.hasOwnProperty(g)) continue;
      var val = card.getAttribute("data-" + g) || "";
      if (groups[g].indexOf(val) === -1) return false;
    }
    return true;
  }

  function apply() {
    var q = (search && search.value || "").trim().toLowerCase();
    var groups = activeFilters();
    var shown = 0;
    cards.forEach(function (card) {
      var ok = matches(card, q, groups);
      card.style.display = ok ? "" : "none";
      if (ok) shown++;
    });
    if (countEl) countEl.textContent = shown + " of " + cards.length + " shown";
    if (emptyEl) emptyEl.style.display = shown === 0 ? "block" : "none";
  }

  var HEALTH_RANK = { red: 0, amber: 1, green: 2, unknown: 3 };
  function sortCards(mode) {
    var arr = cards.slice();
    arr.sort(function (a, b) {
      switch (mode) {
        case "name": return a.getAttribute("data-name").localeCompare(b.getAttribute("data-name"));
        case "health": return (HEALTH_RANK[a.getAttribute("data-health")] - HEALTH_RANK[b.getAttribute("data-health")]) ||
                               a.getAttribute("data-name").localeCompare(b.getAttribute("data-name"));
        case "stars": return num(b, "data-stars") - num(a, "data-stars");
        case "alerts": return num(b, "data-alerts") - num(a, "data-alerts");
        case "recent": return num(a, "data-commitdays", 1e9) - num(b, "data-commitdays", 1e9);
        default: /* featured */ return (fav(b) - fav(a)) || a.getAttribute("data-name").localeCompare(b.getAttribute("data-name"));
      }
    });
    arr.forEach(function (c) { grid.appendChild(c); });
  }
  function num(el, attr, dflt) { var v = parseInt(el.getAttribute(attr), 10); return isNaN(v) ? (dflt || 0) : v; }
  function fav(el) { return el.getAttribute("data-featured") === "true" ? 1 : 0; }

  if (search) search.addEventListener("input", apply);
  chips.forEach(function (c) {
    c.addEventListener("click", function () {
      var pressed = c.getAttribute("aria-pressed") === "true";
      if (c.getAttribute("data-group") === "reset") {
        chips.forEach(function (x) { if (x !== c) x.setAttribute("aria-pressed", "false"); });
        if (search) search.value = "";
      } else {
        c.setAttribute("aria-pressed", pressed ? "false" : "true");
      }
      apply();
    });
  });
  if (sortSel) sortSel.addEventListener("change", function () { sortCards(sortSel.value); });
  sortCards("featured");
  apply();

  /* ---- analytics (Chart.js) --------------------------------------------- */
  var projects = window.DASH_PROJECTS || [];
  var healthArr = window.DASH_HEALTH || [];
  var healthBy = {};
  healthArr.forEach(function (h) { if (h && h.name) healthBy[h.name] = h; });

  function cssVar(name, fallback) {
    var v = getComputedStyle(root).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  if (typeof Chart === "undefined") return;

  var textColor = cssVar("--bs-body-color", "#1f2328");
  var muted = cssVar("--bs-secondary-color", "#6b7280");
  var grid2 = "rgba(128,128,128,.18)";
  Chart.defaults.color = textColor;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily || "system-ui";
  Chart.defaults.plugins.legend.labels.boxWidth = 12;

  var C = {
    red: cssVar("--cc-red", "#ef4444").trim(),
    amber: cssVar("--cc-amber", "#f59e0b").trim(),
    green: cssVar("--cc-green", "#22c55e").trim(),
    docs: cssVar("--cc-docs", "#3b82f6").trim(),
    ai: cssVar("--cc-ai", "#8b5cf6").trim(),
    tools: cssVar("--cc-tools", "#10b981").trim(),
    dash: cssVar("--cc-dash", "#f59e0b").trim(),
    muted: muted.trim()
  };

  function tally(arr, keyFn) {
    var m = {};
    arr.forEach(function (x) { var k = keyFn(x); if (k == null) return; m[k] = (m[k] || 0) + 1; });
    return m;
  }
  function mk(id, config) {
    var el = document.getElementById(id);
    if (!el) return;
    try { new Chart(el.getContext("2d"), config); } catch (e) { /* noop */ }
  }
  var noGrid = { grid: { display: false }, ticks: { color: muted } };
  var vGrid = { grid: { color: grid2 }, ticks: { color: muted, precision: 0 } };

  /* health distribution */
  (function () {
    var t = tally(projects, function (p) { var h = healthBy[p.name]; return h && h.attention ? h.attention.level : "unknown"; });
    var order = ["red", "amber", "green", "unknown"];
    var labels = [], data = [], colors = [];
    order.forEach(function (k) { if (t[k]) { labels.push(k); data.push(t[k]); colors.push(C[k] || C.muted); } });
    mk("chart-health", {
      type: "doughnut",
      data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "bottom" } } }
    });
  })();

  /* projects by category */
  (function () {
    var t = tally(projects, function (p) { return p.category; });
    var labels = Object.keys(t);
    var colorMap = { "docs": C.docs, "full-stack-ai": C.ai, "dev-tools": C.tools, "dash": C.dash };
    mk("chart-category", {
      type: "bar",
      data: { labels: labels, datasets: [{ data: labels.map(function (l) { return t[l]; }),
        backgroundColor: labels.map(function (l) { return colorMap[l] || C.muted; }), borderRadius: 6 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: noGrid, y: vGrid } }
    });
  })();

  /* projects by status */
  (function () {
    var t = tally(projects, function (p) { return p.status; });
    var labels = Object.keys(t);
    var sc = { active: C.green, maintenance: C.docs, experiment: C.amber, archived: C.muted };
    mk("chart-status", {
      type: "polarArea",
      data: { labels: labels, datasets: [{ data: labels.map(function (l) { return t[l]; }),
        backgroundColor: labels.map(function (l) { return (sc[l] || C.muted) + "cc"; }), borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
        scales: { r: { grid: { color: grid2 }, ticks: { display: false } } } }
    });
  })();

  /* top security alerts */
  (function () {
    var rows = healthArr.filter(function (h) { return h && h.security && h.security.alerts > 0; })
      .sort(function (a, b) { return b.security.alerts - a.security.alerts; }).slice(0, 8);
    mk("chart-security", {
      type: "bar",
      data: { labels: rows.map(function (h) { return h.name; }),
        datasets: [{ data: rows.map(function (h) { return h.security.alerts; }), backgroundColor: C.red + "cc", borderRadius: 5 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: vGrid, y: noGrid } }
    });
  })();

  /* top tech stacks */
  (function () {
    var m = {};
    projects.forEach(function (p) { (p.stack || []).forEach(function (s) { m[s] = (m[s] || 0) + 1; }); });
    var rows = Object.keys(m).map(function (k) { return [k, m[k]]; })
      .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 10);
    mk("chart-stack", {
      type: "bar",
      data: { labels: rows.map(function (r) { return r[0]; }),
        datasets: [{ data: rows.map(function (r) { return r[1]; }), backgroundColor: C.ai + "cc", borderRadius: 5 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: vGrid, y: noGrid } }
    });
  })();
})();
