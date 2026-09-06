/*!
 * fleet-feedback v0.1.0 — the universal "Improve this page" widget.
 * Source: bamr87/bamr87 templates/feedback/ (spec: specs/FEEDBACK.md, UPS-FB).
 *
 * Zero dependencies. Registers <fleet-feedback>, installs a console/error ring
 * buffer as early as it is loaded, and files a prefilled GitHub issue that
 * carries page context, environment, and captured logs. Works in any stack:
 * Jekyll, React, Django, Rails, MkDocs, VS Code webviews.
 *
 *   <script src="/assets/js/fleet-feedback.js"></script>
 *   <fleet-feedback repo="owner/name" branch="main" source="pages/about.md"></fleet-feedback>
 *
 * Attributes (all optional except repo): repo, branch, source, page-title,
 * labels (csv marker labels, default "page-feedback"), assignee (default
 * "copilot"; "" disables), mode ("url" | "proxy"), endpoint (proxy URL),
 * capture-logs ("true"/"false"), log-limit (40), fab ("true"/"false"),
 * label ("Improve this page"), env ("production"), types (URL of a JSON array).
 * Inline taxonomy: <script type="application/json" slot="types">[...]</script>.
 *
 * JS API: window.FleetFeedback.open({ type, description, extra })
 *         any element with [data-fleet-feedback-open] (+ data-type) opens it.
 */
(function () {
  'use strict';

  var VERSION = '0.1.0';
  var MAX_URL_LENGTH = 7000;
  var TRIM_ORDER = ['logs', 'directive', 'environment'];
  var SECTION_ORDER = ['description', 'context', 'environment', 'logs', 'directive', 'footer'];

  /* ---------------------------------------------------------------------- */
  /* 1. Console + error capture — installed once, as early as this loads.    */
  /* ---------------------------------------------------------------------- */
  var g = (window.__fleetFeedback = window.__fleetFeedback || { logs: [], limit: 40, installed: false });

  function stringify(v) {
    if (v instanceof Error) return (v.name || 'Error') + ': ' + v.message + (v.stack ? '\n' + v.stack.split('\n').slice(1, 4).join('\n') : '');
    if (typeof v === 'string') return v;
    try { return JSON.stringify(v); } catch (e) { return String(v); }
  }
  function record(level, parts) {
    var line = parts.map(stringify).join(' ').slice(0, 600);
    g.logs.push({ t: new Date().toISOString(), level: level, msg: line });
    while (g.logs.length > g.limit) g.logs.shift();
  }
  if (!g.installed) {
    ['warn', 'error'].forEach(function (level) {
      var orig = console[level];
      console[level] = function () {
        record(level, Array.prototype.slice.call(arguments));
        return orig && orig.apply(console, arguments);
      };
    });
    window.addEventListener('error', function (e) {
      record('error', [e.message || 'Uncaught error', e.filename ? '(' + e.filename + ':' + e.lineno + ')' : '']);
    });
    window.addEventListener('unhandledrejection', function (e) {
      record('error', ['Unhandled rejection:', e.reason]);
    });
    g.installed = true;
  }

  /* ---------------------------------------------------------------------- */
  /* 2. Built-in taxonomy — mirrors templates/feedback/feedback_types.yml.   */
  /*    Labels MUST exist in the target repo (GitHub drops unknown labels).  */
  /* ---------------------------------------------------------------------- */
  var DEFAULT_TYPES = [
    { id: 'fix-page', label: 'Report a problem', group: 'This page', scope: 'page', description: 'A typo, broken link, wrong information, or something rendering badly', labels: ['bug'], agent: true, directive: 'Reproduce and fix the reported defect on the page identified in Page context. Keep the change minimal and surgical; verify with the project build.', placeholder: 'What is wrong, where on the page, and what did you expect instead?' },
    { id: 'improve-page', label: 'Improve this page', group: 'This page', scope: 'page', description: 'Polish the copy, structure, or presentation', labels: ['docs'], agent: true, directive: 'Act as a content editor for the page in Page context. Tighten copy, fix grammar, improve heading hierarchy — without changing the core message or breaking links.', placeholder: 'What would make this page clearer, tighter, or more useful?' },
    { id: 'expand-page', label: 'Add missing detail', group: 'This page', scope: 'page', description: 'Add depth, examples, or a section a reader would expect', labels: ['docs'], agent: true, directive: 'Expand the page in Page context with concrete examples, prerequisites, and any expected-but-missing sections. Preserve tone and front matter.', placeholder: 'What is missing? Which examples or sections would help?' },
    { id: 'update-page', label: 'Flag outdated content', group: 'This page', scope: 'page', description: 'Stale versions, dead links, or old screenshots', labels: ['docs'], agent: true, directive: 'Audit the page in Page context for stale versions, dead links, and outdated screenshots; refresh them and bump lastmod.', placeholder: 'What is out of date? Paste the stale value or link if you can.' },
    { id: 'accessibility', label: 'Accessibility issue', group: 'This page', scope: 'page', description: 'Contrast, keyboard, screen-reader, or focus problems', labels: ['bug', 'area:a11y'], agent: true, directive: 'Audit the page in Page context against WCAG 2.1 AA for the reported barrier and propose concrete fixes.', placeholder: 'What barrier did you hit? Which assistive tech or input method?' },
    { id: 'ui-ux', label: 'UI / UX improvement', group: 'The site', scope: 'site', description: 'A design or usability refinement', labels: ['feature'], agent: true, directive: 'Propose a token-first UI/UX refinement using the page in Page context as the starting example. Cover responsive behaviour, dark mode, and accessibility.', placeholder: 'What feels off, and how might it look or behave instead?' },
    { id: 'performance', label: 'Performance', group: 'The site', scope: 'site', description: 'Slow load, layout shift, or heavy assets', labels: ['bug', 'area:perf'], agent: true, directive: 'Profile the page in Page context (LCP, CLS, INP), identify the bottleneck, and propose fixes.', placeholder: 'What felt slow? On what device / connection?' },
    { id: 'feature', label: 'Feature request', group: 'The site', scope: 'site', description: 'Propose a new capability', labels: ['feature'], agent: false, directive: '', placeholder: 'What should it do, and who benefits?' },
    { id: 'question', label: 'Ask a question', group: 'The site', scope: 'site', description: 'Something unclear — not necessarily a bug', labels: ['question'], agent: false, directive: '', placeholder: 'What are you trying to do, and where did you get stuck?' }
  ];

  /* ---------------------------------------------------------------------- */
  /* 3. Helpers                                                              */
  /* ---------------------------------------------------------------------- */
  function cell(v) { return String(v == null ? '' : v).replace(/\|/g, '\\|').replace(/\r?\n/g, ' '); }
  function bool(v, d) { return v == null ? d : v !== 'false' && v !== '0'; }
  function uniq(arr) { return arr.filter(function (x, i) { return x && arr.indexOf(x) === i; }); }
  function mq(q) { return window.matchMedia && window.matchMedia(q).matches; }

  var STYLE = [
    ':host{--_fg:var(--fleet-color-ink,var(--zer0-color-ink,var(--bs-body-color,#1b1f23)));',
    '--_bg:var(--fleet-color-bg-elevated,var(--zer0-color-bg-elevated,var(--bs-body-bg,#fff)));',
    '--_muted:var(--fleet-color-ink-muted,var(--zer0-color-ink-muted,#6c757d));',
    '--_border:var(--fleet-color-border,var(--zer0-color-border,#dee2e6));',
    '--_primary:var(--fleet-color-primary,var(--zer0-color-primary,var(--bs-primary,#007bff)));',
    '--_radius:var(--fleet-radius-lg,.5rem);--_shadow:var(--fleet-shadow-lg,0 1rem 3rem rgba(0,0,0,.18));',
    '--_focus:var(--fleet-shadow-focus,0 0 0 .2rem rgba(0,123,255,.25));',
    '--_fab-layer:var(--fleet-layer-fab-feedback,1051);--_modal-layer:var(--fleet-layer-feedback-modal,1096);',
    '--_offset:var(--fleet-space-fab-offset,1rem);--_size:var(--fleet-space-fab-size,3.5rem);',
    'font:400 1rem/1.55 var(--fleet-font-sans,system-ui,sans-serif);color:var(--_fg)}',
    '*{box-sizing:border-box}',
    '.fab{position:fixed;right:var(--_offset);bottom:calc(var(--_offset) + var(--fleet-space-fab-gap,.75rem) + var(--_size));z-index:var(--_fab-layer);',
    'width:var(--_size);height:var(--_size);border-radius:50%;border:0;background:var(--_primary);color:#fff;cursor:pointer;box-shadow:var(--_shadow);font-size:1.4rem;display:grid;place-items:center}',
    '.fab:focus-visible,button:focus-visible,textarea:focus-visible,input:focus-visible,label:focus-within{outline:0;box-shadow:var(--_focus)}',
    'dialog{z-index:var(--_modal-layer);border:1px solid var(--_border);border-radius:var(--_radius);background:var(--_bg);color:var(--_fg);padding:0;width:min(40rem,calc(100vw - 2rem));max-height:calc(100vh - 2rem);box-shadow:var(--_shadow)}',
    'dialog::backdrop{background:rgba(0,0,0,.5)}',
    'form{display:flex;flex-direction:column;gap:1rem;padding:1.25rem}',
    'header{display:flex;justify-content:space-between;align-items:center;gap:1rem}h2{margin:0;font-size:1.25rem}',
    '.close{background:none;border:0;font-size:1.5rem;line-height:1;cursor:pointer;color:var(--_muted)}',
    'fieldset{border:0;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(12rem,1fr));gap:.5rem}',
    'legend,.h{font-weight:600;margin-bottom:.5rem}',
    '.type{display:flex;gap:.5rem;align-items:flex-start;border:1px solid var(--_border);border-radius:var(--_radius);padding:.5rem .6rem;cursor:pointer}',
    '.type:has(input:checked){border-color:var(--_primary);box-shadow:inset 0 0 0 1px var(--_primary)}',
    '.type small{display:block;color:var(--_muted);font-size:.8rem}',
    'textarea{width:100%;min-height:7rem;padding:.6rem;border:1px solid var(--_border);border-radius:var(--_radius);background:transparent;color:inherit;font:inherit;resize:vertical}',
    'details{border:1px solid var(--_border);border-radius:var(--_radius);padding:.5rem .75rem}summary{cursor:pointer;font-weight:600}',
    'ul{margin:.5rem 0 0;padding-left:1.25rem;font-size:.85rem;color:var(--_muted)}pre{margin:.5rem 0 0;max-height:8rem;overflow:auto;font-size:.75rem;white-space:pre-wrap}',
    '.row{display:flex;gap:.75rem;align-items:center;flex-wrap:wrap}.grow{flex:1}',
    '.btn{border:1px solid var(--_primary);border-radius:var(--_radius);padding:.5rem 1rem;font:inherit;cursor:pointer;background:var(--_primary);color:#fff}',
    '.btn.ghost{background:transparent;color:var(--_primary)}',
    '.status{font-size:.85rem;color:var(--_muted);min-height:1.2em}',
    '@media (prefers-reduced-motion:no-preference){dialog[open]{animation:fi var(--fleet-motion-base,200ms) var(--fleet-ease,cubic-bezier(.2,0,0,1))}}',
    '@keyframes fi{from{opacity:0;transform:translateY(.5rem)}to{opacity:1;transform:none}}'
  ].join('');

  /* ---------------------------------------------------------------------- */
  /* 4. The element                                                          */
  /* ---------------------------------------------------------------------- */
  function FleetFeedback() {
    var self = Reflect.construct(HTMLElement, [], FleetFeedback);
    self._types = DEFAULT_TYPES;
    self._preset = {};
    return self;
  }
  FleetFeedback.prototype = Object.create(HTMLElement.prototype);
  FleetFeedback.prototype.constructor = FleetFeedback;

  FleetFeedback.prototype.config = function () {
    var a = this.getAttribute.bind(this);
    return {
      repo: a('repo') || '',
      branch: a('branch') || 'main',
      source: a('source') || '',
      pageTitle: a('page-title') || document.title,
      labels: (a('labels') || 'page-feedback').split(',').map(function (s) { return s.trim(); }),
      assignee: a('assignee') == null ? 'copilot' : a('assignee'),
      mode: a('mode') === 'proxy' ? 'proxy' : 'url',
      endpoint: a('endpoint') || '/api/github/issue',
      captureLogs: bool(a('capture-logs'), true),
      logLimit: parseInt(a('log-limit') || '40', 10),
      fab: bool(a('fab'), true),
      label: a('label') || 'Improve this page',
      env: a('env') || '',
      typesUrl: a('types') || ''
    };
  };

  FleetFeedback.prototype.connectedCallback = function () {
    var self = this;
    var cfg = this.config();
    g.limit = cfg.logLimit;
    var inline = this.querySelector('script[type="application/json"]');
    if (inline) { try { this._types = JSON.parse(inline.textContent); } catch (e) { console.warn('fleet-feedback: bad inline types JSON'); } }
    else if (cfg.typesUrl && window.fetch) {
      fetch(cfg.typesUrl).then(function (r) { return r.json(); }).then(function (t) { if (Array.isArray(t) && t.length) { self._types = t; self._renderTypes(); } }).catch(function () {});
    }
    this._render(cfg);
    // Progressive enhancement: any [data-fleet-feedback-open] anywhere opens the dialog.
    document.addEventListener('click', function (e) {
      var t = e.target && e.target.closest && e.target.closest('[data-fleet-feedback-open]');
      if (!t) return;
      e.preventDefault();
      self.open({ type: t.getAttribute('data-type') || '' });
    });
    window.FleetFeedback = { open: function (o) { self.open(o || {}); }, logs: g.logs, version: VERSION, element: self };
  };

  FleetFeedback.prototype._render = function (cfg) {
    var root = this.attachShadow({ mode: 'open' });
    root.innerHTML =
      '<style>' + STYLE + '</style>' +
      (cfg.fab ? '<button type="button" class="fab" aria-haspopup="dialog" aria-controls="dlg" title="' + cfg.label + '" aria-label="' + cfg.label + '">&#x1F4E3;</button>' : '') +
      '<dialog id="dlg" aria-labelledby="ttl">' +
      '<form method="dialog" novalidate>' +
      '<header><h2 id="ttl">' + cfg.label + '</h2><button type="button" class="close" aria-label="Close">&times;</button></header>' +
      '<div><div class="h" id="tl">What kind of request?</div><fieldset id="types" aria-labelledby="tl"></fieldset></div>' +
      '<div><label class="h" for="desc">Describe it</label><textarea id="desc" name="description" required></textarea></div>' +
      '<details><summary>What will be attached</summary><ul id="ctx" aria-live="polite"></ul>' +
      '<label class="row" style="margin-top:.5rem"><input type="checkbox" id="logs" checked> <span>Include captured console &amp; error logs (<span id="nlogs">0</span>)</span></label>' +
      '<pre id="logpre" hidden></pre></details>' +
      '<div class="row"><span class="status grow" id="status" role="status" aria-live="polite"></span>' +
      '<button type="button" class="btn ghost" id="cancel">Cancel</button><button type="submit" class="btn" id="submit">Open GitHub issue</button></div>' +
      '</form></dialog>';
    this._$ = function (s) { return root.querySelector(s); };
    this._renderTypes();
    var self = this;
    if (cfg.fab) this._$('.fab').addEventListener('click', function () { self.open({}); });
    this._$('.close').addEventListener('click', function () { self.close(); });
    this._$('#cancel').addEventListener('click', function () { self.close(); });
    this._$('#logs').addEventListener('change', function (e) { self._$('#logpre').hidden = !e.target.checked; });
    this._$('form').addEventListener('submit', function (e) { e.preventDefault(); self.submit(); });
    this._$('#dlg').addEventListener('close', function () { if (self._opener && self._opener.focus) self._opener.focus(); });
  };

  FleetFeedback.prototype._renderTypes = function () {
    if (!this._$) return;
    var fs = this._$('#types');
    fs.innerHTML = this._types.map(function (t, i) {
      return '<label class="type"><input type="radio" name="type" value="' + t.id + '"' + (i === 0 ? ' checked' : '') + ' aria-describedby="d-' + t.id + '">' +
        '<span><strong>' + t.label + '</strong><small id="d-' + t.id + '">' + (t.description || '') + '</small></span></label>';
    }).join('');
    var self = this;
    fs.addEventListener('change', function () { self._syncPlaceholder(); });
    this._syncPlaceholder();
  };

  FleetFeedback.prototype._type = function () {
    var v = this._$('input[name=type]:checked');
    var id = v ? v.value : '';
    return this._types.filter(function (t) { return t.id === id; })[0] || this._types[0];
  };
  FleetFeedback.prototype._syncPlaceholder = function () {
    var t = this._type();
    if (t) this._$('#desc').placeholder = t.placeholder || '';
  };

  FleetFeedback.prototype.open = function (opts) {
    var cfg = this.config();
    this._preset = opts || {};
    this._opener = document.activeElement;
    if (opts && opts.type) {
      var r = this._$('input[name=type][value="' + opts.type + '"]');
      if (r) { r.checked = true; this._syncPlaceholder(); }
    }
    if (opts && opts.description) this._$('#desc').value = opts.description;
    var ctx = this.context(cfg);
    this._$('#ctx').innerHTML = [
      'Page: ' + ctx.title, 'URL: ' + ctx.url, ctx.sourceUrl ? 'Source: ' + ctx.path : '', 'Browser, viewport, colour scheme, referrer', 'Repository: ' + cfg.repo + ' @ ' + cfg.branch
    ].filter(Boolean).map(function (s) { return '<li>' + s.replace(/</g, '&lt;') + '</li>'; }).join('');
    var logs = cfg.captureLogs ? g.logs : [];
    this._$('#nlogs').textContent = String(logs.length);
    this._$('#logs').checked = cfg.captureLogs && logs.length > 0;
    this._$('#logs').disabled = !cfg.captureLogs || logs.length === 0;
    this._$('#logpre').textContent = logs.map(function (l) { return l.t + ' [' + l.level + '] ' + l.msg; }).join('\n');
    this._$('#logpre').hidden = !this._$('#logs').checked;
    this._$('#status').textContent = '';
    this._$('#submit').textContent = cfg.mode === 'proxy' ? 'File issue' : 'Open GitHub issue';
    var dlg = this._$('#dlg');
    if (!dlg.open) dlg.showModal();
    this._$('#desc').focus();
  };
  FleetFeedback.prototype.close = function () { var d = this._$('#dlg'); if (d.open) d.close(); };

  FleetFeedback.prototype.context = function (cfg) {
    var path = cfg.source;
    return {
      title: cfg.pageTitle,
      url: location.href,
      path: path,
      sourceUrl: path && cfg.repo ? 'https://github.com/' + cfg.repo + '/blob/' + cfg.branch + '/' + path : '',
      lastmod: (document.querySelector('meta[property="article:modified_time"]') || {}).content || ''
    };
  };

  FleetFeedback.prototype.buildIssue = function () {
    var cfg = this.config(), t = this._type(), ctx = this.context(cfg);
    var desc = this._$('#desc').value.trim();
    var includeLogs = this._$('#logs').checked && cfg.captureLogs;
    var logs = includeLogs ? g.logs.slice() : [];
    var extra = this._preset.extra ? '\n\n' + this._preset.extra : '';
    var s = {};
    s.description = '## 📝 Description\n\n' + (desc || '_(no description provided)_') + extra;
    s.context = ['## 📄 Page context', '', '| Field | Value |', '|---|---|',
      '| **Page** | ' + cell(ctx.title) + ' |', '| **URL** | ' + cell(ctx.url) + ' |',
      ctx.sourceUrl ? '| **Source** | [`' + cell(ctx.path) + '`](' + ctx.sourceUrl + ') |' : '',
      ctx.lastmod ? '| **Last modified** | ' + cell(ctx.lastmod) + ' |' : ''].filter(Boolean).join('\n');
    s.environment = ['## 🔧 Environment', '', '| Field | Value |', '|---|---|',
      '| **Browser** | ' + cell(navigator.userAgent) + ' |',
      '| **Viewport** | ' + window.innerWidth + '×' + window.innerHeight + ' @' + (window.devicePixelRatio || 1) + 'x |',
      '| **Colour scheme** | ' + (mq('(prefers-color-scheme: dark)') ? 'dark' : 'light') + (mq('(prefers-reduced-motion: reduce)') ? ', reduced motion' : '') + ' |',
      '| **Referrer** | ' + cell(document.referrer || '—') + ' |',
      '| **Repository** | ' + cell(cfg.repo) + ' @ ' + cell(cfg.branch) + ' |',
      cfg.env ? '| **Build env** | ' + cell(cfg.env) + ' |' : '',
      '| **Captured at** | ' + new Date().toISOString() + ' |'].filter(Boolean).join('\n');
    s.logs = logs.length ? '<details><summary>🧾 Console &amp; error logs (' + logs.length + ')</summary>\n\n```text\n' +
      logs.map(function (l) { return l.t + ' [' + l.level + '] ' + l.msg; }).join('\n').replace(/```/g, "'''") + '\n```\n\n</details>' : '';
    s.directive = t.agent && t.directive ? '## 🤖 Agent directive\n\n' + t.directive : '';
    s.footer = '---\n_Filed from ' + ctx.url + ' via fleet-feedback v' + VERSION + '._\n<!-- fleet-feedback v1 type=' + t.id + ' -->';
    var labels = uniq(cfg.labels.concat(t.labels || []));
    var assignees = t.agent && cfg.assignee ? [cfg.assignee] : [];
    var title = ('[' + t.label + '] ' + (ctx.title || document.title)).slice(0, 240);
    return { title: title, sections: s, labels: labels, assignees: assignees, type: t };
  };

  function assemble(sections, skip) {
    return SECTION_ORDER.filter(function (k) { return sections[k] && skip.indexOf(k) < 0; }).map(function (k) { return sections[k]; }).join('\n\n');
  }
  FleetFeedback.prototype.buildUrl = function (issue) {
    var cfg = this.config();
    var base = 'https://github.com/' + cfg.repo + '/issues/new';
    var skip = [], url, i = 0;
    function compose() {
      var p = new URLSearchParams();
      p.set('title', issue.title);
      p.set('body', assemble(issue.sections, skip));
      if (issue.labels.length) p.set('labels', issue.labels.join(','));
      if (issue.assignees.length) p.set('assignees', issue.assignees.join(','));
      return base + '?' + p.toString();
    }
    url = compose();
    while (url.length > MAX_URL_LENGTH && i < TRIM_ORDER.length) { skip.push(TRIM_ORDER[i++]); url = compose(); }
    return { url: url, trimmed: skip, overBudget: url.length > MAX_URL_LENGTH, fullBody: assemble(issue.sections, []) };
  };

  FleetFeedback.prototype.submit = function () {
    var cfg = this.config(), self = this, status = this._$('#status');
    if (!cfg.repo) { status.textContent = 'fleet-feedback: missing repo attribute.'; return; }
    if (!this._$('#desc').value.trim()) { status.textContent = 'Please describe the request first.'; this._$('#desc').focus(); return; }
    var issue = this.buildIssue();
    if (cfg.mode === 'proxy') {
      status.textContent = 'Filing…';
      fetch(cfg.endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: issue.title, body: assemble(issue.sections, []), labels: issue.labels, assignees: issue.assignees, type: issue.type.id }) })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (j) { status.textContent = 'Filed: ' + (j.html_url || j.url || 'ok'); setTimeout(function () { self.close(); }, 1500); })
        .catch(function (e) { status.textContent = 'Could not file (' + e.message + '). Copied the issue to your clipboard instead.'; self._clipboard(assemble(issue.sections, [])); });
      return;
    }
    var built = this.buildUrl(issue);
    var win = window.open(built.url, '_blank');
    if (!win) {
      this._clipboard(built.fullBody);
      status.textContent = 'Pop-up blocked — the full issue is on your clipboard. Open ' + 'https://github.com/' + cfg.repo + '/issues/new and paste.';
      return;
    }
    try { win.opener = null; } catch (e) { /* cross-origin */ }
    if (built.trimmed.length) {
      this._clipboard(built.fullBody);
      status.textContent = 'Opened GitHub. The URL was too long for ' + built.trimmed.join(', ') + ' — the full body is on your clipboard; paste it over the prefilled one.';
    } else {
      status.textContent = 'Opened GitHub in a new tab.';
      setTimeout(function () { self.close(); }, 1200);
    }
  };
  FleetFeedback.prototype._clipboard = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(function () {});
  };

  if (window.customElements && !customElements.get('fleet-feedback')) customElements.define('fleet-feedback', FleetFeedback);
})();
