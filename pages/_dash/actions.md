---
layout: default
title: Actions Usage
description: GitHub Actions consumption analytics — where CI minutes go, and which workflows run a lot while producing little.
permalink: /actions/
sidebar:
  nav: dash
---

# 📈 GitHub Actions Usage

Where your Actions minutes go across every registry repo, and — quantitatively — which workflows are **high-running but low-effective**. Refreshed daily by `.github/workflows/actions-usage.yml` (via PyGithub) into `_data/actions_usage.yml`.

{% assign a = site.data.actions_usage %}
{% if a == nil %}
<div class="alert alert-info">
No Actions usage data yet. Run <code>tools/dash actions</code> locally (needs
<code>PyGithub</code> + a GitHub token), or wait for the daily
<code>Actions Usage Refresh</code> workflow. It queries the Actions API for each
registry repo and writes <code>_data/actions_usage.yml</code>, which this page renders.
</div>
{% else %}

<div class="row text-center my-4">
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ a.totals.total_hours }}h</h3><div class="text-muted small">Consumed / {{ a.window_days }}d</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 border-danger"><div class="card-body p-2"><h3 class="mb-0 text-danger">{{ a.totals.waste_hours }}h</h3><div class="text-muted small">Wasted ({{ 100 | minus: a.totals.effectiveness_pct | round }}%)</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ a.totals.success_rate_pct }}%</h3><div class="text-muted small">Run success rate</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ a.totals.runs }}</h3><div class="text-muted small">Runs</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ a.totals.workflows }}</h3><div class="text-muted small">Active workflows</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ a.totals.repos_with_activity }}</h3><div class="text-muted small">of {{ a.repos_scanned }} repos active</div></div></div></div>
</div>

<p class="small text-muted">{{ a.note }}</p>

## Consumption by workflow type

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Type</th><th style="width:35%">Share of minutes</th><th class="text-end">Minutes</th><th class="text-end">Runs</th><th class="text-end">Effectiveness</th><th class="text-end">Wasted</th></tr></thead>
  <tbody>
  {% for t in a.by_type %}
    <tr>
      <td><span class="badge bg-secondary">{{ t.type }}</span></td>
      <td>
        <div class="progress" style="height:16px" role="progressbar" aria-valuenow="{{ t.share_pct }}" aria-valuemin="0" aria-valuemax="100">
          <div class="progress-bar {% if t.effectiveness_pct < 55 %}bg-danger{% elsif t.effectiveness_pct < 85 %}bg-warning{% else %}bg-success{% endif %}" style="width:{{ t.share_pct }}%">{{ t.share_pct }}%</div>
        </div>
      </td>
      <td class="text-end">{{ t.total_min | round }}</td>
      <td class="text-end">{{ t.runs }}</td>
      <td class="text-end {% if t.effectiveness_pct < 55 %}text-danger fw-bold{% endif %}">{{ t.effectiveness_pct }}%</td>
      <td class="text-end">{{ t.waste_min | round }}m</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Cost vs. effectiveness

<p class="small text-muted">Each dot is a workflow: <strong>x = minutes consumed</strong> (√-scaled), <strong>y = effectiveness</strong> (% of minutes ending in success), <strong>size = run count</strong>. The shaded corner (high cost, low value) is where to look first.</p>
<div style="overflow-x:auto"><canvas id="quadrant" width="900" height="440" style="max-width:100%"></canvas></div>
<div id="quadrant-tip" class="small text-muted"></div>

## Workflows — drill down

<div class="mb-2" id="type-filter"><span class="small text-muted me-2">Filter:</span>
  <button class="btn btn-sm btn-outline-secondary active" data-type="all">all</button>
  {% for t in a.by_type %}<button class="btn btn-sm btn-outline-secondary" data-type="{{ t.type }}">{{ t.type }}</button>{% endfor %}
</div>

<div class="table-responsive">
<table class="table table-sm table-hover align-middle" id="wf-table">
  <thead>
    <tr>
      <th data-sort="repo">Repo / workflow</th>
      <th data-sort="type">Type</th>
      <th data-sort="runs" class="text-end">Runs</th>
      <th data-sort="total_min" class="text-end">Min</th>
      <th data-sort="avg_min" class="text-end">Avg</th>
      <th data-sort="p95_min" class="text-end">p95</th>
      <th data-sort="success_rate_pct" class="text-end">Success</th>
      <th data-sort="effectiveness_pct" class="text-end">Effective</th>
      <th data-sort="waste_min" class="text-end">Wasted</th>
      <th>Signals</th>
    </tr>
  </thead>
  <tbody>
  {% for w in a.workflows %}
    <tr data-type="{{ w.type }}" class="{% if w.flags contains 'high-cost-low-value' %}table-danger{% elsif w.flags contains 'failing' %}table-warning{% endif %}"
        data-repo="{{ w.repo }}" data-runs="{{ w.runs }}" data-total_min="{{ w.total_min }}" data-avg_min="{{ w.avg_min }}"
        data-p95_min="{{ w.p95_min }}" data-success_rate_pct="{{ w.success_rate_pct }}" data-effectiveness_pct="{{ w.effectiveness_pct }}" data-waste_min="{{ w.waste_min }}">
      <td>{% if w.repo_url %}<a href="{{ w.repo_url }}">{{ w.repo }}</a>{% else %}{{ w.repo }}{% endif %} <span class="text-muted">/ {{ w.workflow }}</span></td>
      <td><span class="badge bg-light text-dark border">{{ w.type }}</span></td>
      <td class="text-end">{{ w.runs }}</td>
      <td class="text-end">{{ w.total_min | round }}</td>
      <td class="text-end">{{ w.avg_min | round: 1 }}</td>
      <td class="text-end">{{ w.p95_min | round: 1 }}</td>
      <td class="text-end">{{ w.success_rate_pct }}%</td>
      <td class="text-end {% if w.effectiveness_pct < 55 %}text-danger fw-bold{% endif %}">{{ w.effectiveness_pct }}%</td>
      <td class="text-end">{{ w.waste_min | round }}m</td>
      <td>
        {% for f in w.flags %}{% case f %}
          {% when 'high-cost-low-value' %}<span class="badge bg-danger">high-cost·low-value</span>
          {% when 'failing' %}<span class="badge bg-danger">failing</span>
          {% when 'flaky' %}<span class="badge bg-warning text-dark">flaky</span>
          {% when 'slow' %}<span class="badge bg-warning text-dark">slow</span>
          {% when 'cancel-heavy' %}<span class="badge bg-warning text-dark">cancel-heavy</span>
          {% when 'cron-heavy' %}<span class="badge bg-info text-dark">cron-heavy</span>
          {% else %}<span class="badge bg-secondary">{{ f }}</span>
        {% endcase %}{% endfor %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

{% if a.inactive.size > 0 %}
<details class="my-3">
<summary><strong>{{ a.inactive.size }} workflows defined but idle</strong> this window — candidates to prune or disable</summary>
<div class="table-responsive mt-2">
<table class="table table-sm">
  <thead><tr><th>Repo</th><th>Workflow</th><th>Path</th><th>State</th></tr></thead>
  <tbody>
  {% for i in a.inactive %}<tr><td>{{ i.repo }}</td><td>{{ i.workflow }}</td><td><code class="small">{{ i.path }}</code></td><td>{% if i.state != 'active' %}<span class="badge bg-secondary">{{ i.state }}</span>{% else %}{{ i.state }}{% endif %}</td></tr>{% endfor %}
  </tbody>
</table>
</div>
</details>
{% endif %}

<p class="small text-muted">Generated {{ a.generated_at }} · window {{ a.window_days }} days · {{ a.repos_scanned }} repos.</p>

<script>
(function () {
  var WF = {{ a.workflows | jsonify }};
  if (!Array.isArray(WF) || !WF.length) return;

/* ---- cost-vs-effectiveness quadrant (canvas) ---- */ var cv = document.getElementById('quadrant'); if (cv && cv.getContext) {
    var ctx = cv.getContext('2d'), W = cv.width, H = cv.height,
        padL = 48, padR = 16, padT = 16, padB = 34;
    var maxMin = Math.max.apply(null, WF.map(function (w) { return w.total_min; })) || 1;
    var css = getComputedStyle(document.body);
    var fg = css.color || '#333', muted = 'rgba(128,128,128,.6)';
    var TYPE_COLORS = { ai:'#8b5cf6', ci:'#2563eb', deploy:'#0891b2', release:'#059669',
      docs:'#65a30d', security:'#d97706', dependencies:'#db2777', automation:'#0d9488', other:'#6b7280' };
    var sx = function (m) { return padL + Math.sqrt(m / maxMin) * (W - padL - padR); };
    var sy = function (e) { return padT + (1 - e / 100) * (H - padT - padB); };

    function draw() {
      ctx.clearRect(0, 0, W, H);
      // danger zone: high cost (x > 45%), low value (y: eff < 55)
      ctx.fillStyle = 'rgba(220,53,69,.08)';
      ctx.fillRect(sx(maxMin * 0.2), sy(55), W - padR - sx(maxMin * 0.2), sy(0) - sy(55));
      // grid + axes
      ctx.strokeStyle = muted; ctx.fillStyle = muted; ctx.lineWidth = 1;
      ctx.font = '11px system-ui,sans-serif'; ctx.textAlign = 'right';
      [0, 25, 50, 75, 100].forEach(function (e) {
        var y = sy(e); ctx.globalAlpha = .25; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
        ctx.globalAlpha = 1; ctx.fillText(e + '%', padL - 5, y + 3);
      });
      ctx.textAlign = 'left';
      ctx.fillText('effectiveness ↑   ·   cost →   ·   ⬛ danger: high cost, low value', padL, H - 12);
      // points (largest first so small dots sit on top)
      WF.slice().sort(function (a, b) { return b.total_min - a.total_min; }).forEach(function (w) {
        var r = Math.max(3, Math.min(16, 3 + Math.sqrt(w.runs) * 1.6));
        ctx.beginPath(); ctx.arc(sx(w.total_min), sy(w.effectiveness_pct), r, 0, 6.2832);
        ctx.fillStyle = (TYPE_COLORS[w.type] || TYPE_COLORS.other) + 'cc';
        ctx.fill();
        if (w.flags && w.flags.indexOf('high-cost-low-value') >= 0) { ctx.lineWidth = 2; ctx.strokeStyle = '#dc3545'; ctx.stroke(); }
      });
    }
    draw();
    var tip = document.getElementById('quadrant-tip');
    cv.addEventListener('mousemove', function (ev) {
      var rect = cv.getBoundingClientRect(), scale = cv.width / rect.width;
      var mx = (ev.clientX - rect.left) * scale, my = (ev.clientY - rect.top) * scale, hit = null;
      WF.forEach(function (w) {
        var dx = sx(w.total_min) - mx, dy = sy(w.effectiveness_pct) - my;
        if (dx * dx + dy * dy < 120) hit = w;
      });
      tip.textContent = hit ? (hit.repo + ' / ' + hit.workflow + ' — ' + Math.round(hit.total_min) + 'm, '
        + hit.effectiveness_pct + '% effective, ' + hit.runs + ' runs') : '';
    });
  }

/* ---- type filter ---- */ var rows = Array.prototype.slice.call(document.querySelectorAll('#wf-table tbody tr')); document.querySelectorAll('#type-filter button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('#type-filter button').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      var t = btn.getAttribute('data-type');
      rows.forEach(function (r) { r.style.display = (t === 'all' || r.getAttribute('data-type') === t) ? '' : 'none'; });
    });
  });

/* ---- column sort ---- */ var tbody = document.querySelector('#wf-table tbody'), dir = {}; document.querySelectorAll('#wf-table th[data-sort]').forEach(function (th) {
    th.style.cursor = 'pointer';
    th.addEventListener('click', function () {
      var key = th.getAttribute('data-sort'), num = key !== 'repo' && key !== 'type';
      dir[key] = !dir[key];
      rows.sort(function (a, b) {
        var av = a.getAttribute('data-' + key) || a.getAttribute('data-repo') || '',
            bv = b.getAttribute('data-' + key) || b.getAttribute('data-repo') || '';
        if (key === 'type') { av = a.getAttribute('data-type'); bv = b.getAttribute('data-type'); }
        if (num) { av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; return dir[key] ? av - bv : bv - av; }
        return dir[key] ? String(av).localeCompare(bv) : String(bv).localeCompare(av);
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
}); })();
</script>
{% endif %}
