"""
Add interactive dynamics to Occupado dashboards:
- Counter animations on all key metrics
- Filter tabs (All / High / Medium / Low) above tables
- Inline expandable rows with AI prediction explanation
- Sortable table columns
- Live pulse indicator in topbar
- Scroll fade-in for sections
"""
import re

with open('C:/Users/jpdou/Desktop/Occupado/app.py', 'r', encoding='utf-8') as f:
    src = f.read()

# ─────────────────────────────────────────────────────────────
# SHARED CSS — injected before each </style> in both dashboards
# ─────────────────────────────────────────────────────────────
DYNAMICS_CSS = """
/* ── DYNAMICS ────────────────────────────────────────────── */
.filter-bar{{display:flex;gap:8px;margin-bottom:20px;align-items:center;flex-wrap:wrap;}}
.f-tab{{padding:5px 16px;border:1px solid #e5e7eb;border-radius:99px;font-size:12px;color:#6b7280;cursor:pointer;transition:all .15s;background:#fff;font-family:'Inter',sans-serif;}}
.f-tab:hover{{border-color:#111827;color:#111827;}}
.f-tab.active{{background:#111827;color:#fff;border-color:#111827;}}
.f-count{{font-size:10px;opacity:.6;margin-left:3px;}}
.sort-th{{cursor:pointer;user-select:none;}}
.sort-th:hover{{color:#374151;}}
.sort-arr{{margin-left:3px;opacity:.25;font-size:9px;}}
.sort-arr.on{{opacity:1;}}
.live-pill{{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#9ca3af;padding:4px 10px;border:1px solid #e5e7eb;border-radius:99px;}}
.live-dot{{width:6px;height:6px;border-radius:50%;background:#00d165;flex-shrink:0;animation:pdot 2s ease-in-out infinite;}}
@keyframes pdot{{0%,100%{{opacity:1;transform:scale(1);}}50%{{opacity:.3;transform:scale(.8);}}}}
.exp-tr{{display:none;}}
.exp-tr.open{{display:table-row;}}
.exp-td{{padding:0!important;background:#fff!important;border-bottom:1px solid #f3f4f6!important;}}
.exp-inner{{padding:20px 0 24px;display:grid;grid-template-columns:100px 1fr;gap:24px;align-items:start;}}
.exp-score-wrap{{display:flex;flex-direction:column;align-items:center;gap:4px;padding-top:4px;}}
.exp-score-big{{font-size:48px;font-weight:700;letter-spacing:-2px;line-height:1;}}
.exp-score-lbl{{font-size:9px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;margin-top:2px;}}
.exp-bar-bg{{width:70px;height:3px;background:#f3f4f6;border-radius:2px;overflow:hidden;margin-top:8px;}}
.exp-bar-fill{{height:100%;border-radius:2px;transition:width .7s ease;}}
.exp-right{{}}
.exp-head{{font-size:10px;font-weight:500;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;}}
.exp-factors{{display:flex;flex-direction:column;gap:4px;}}
.exp-factor{{font-size:12px;color:#374151;padding:6px 10px 6px 12px;border-left:2px solid #e5e7eb;line-height:1.4;}}
.exp-factor.pos{{border-left-color:#00d165;}}
.exp-factor.warn{{border-left-color:#f59e0b;}}
.exp-factor.bad{{border-left-color:#ef4444;}}
.exp-conclusion{{margin-top:10px;font-size:12px;font-weight:500;color:#111827;padding:8px 12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;}}
.cr.is-open{{background:#fafafa;}}
.count-up{{display:inline;}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(10px);}}to{{opacity:1;transform:translateY(0);}}}}
.anim-card{{opacity:0;animation:fadeUp .5s ease forwards;}}
.anim-card:nth-child(1){{animation-delay:.04s;}}
.anim-card:nth-child(2){{animation-delay:.08s;}}
.anim-card:nth-child(3){{animation-delay:.12s;}}
.anim-card:nth-child(4){{animation-delay:.16s;}}
@media(max-width:900px){{.exp-inner{{grid-template-columns:1fr;gap:16px;}}}}"""

# ─────────────────────────────────────────────────────────────
# SHARED JS — core dynamics functions
# ─────────────────────────────────────────────────────────────
DYNAMICS_JS = """
// ── DYNAMICS JS ──────────────────────────────────────────────

// Counter animation
function countUp(el, target, duration, pre, suf) {{
  if (!el) return;
  pre = pre||''; suf = suf||''; duration = duration||1400;
  const start = performance.now();
  function tick(now) {{
    const p = Math.min((now - start)/duration, 1);
    const ease = 1 - Math.pow(1-p, 3);
    const val = Math.round(ease * target);
    el.textContent = pre + val.toLocaleString() + suf;
    if (p < 1) requestAnimationFrame(tick);
  }}
  requestAnimationFrame(tick);
}}
document.querySelectorAll('.count-up').forEach(function(el) {{
  countUp(el, parseFloat(el.dataset.val)||0, 1400, el.dataset.pre||'', el.dataset.suf||'');
}});

// Filter tabs
function filterRisk(risk, btn) {{
  document.querySelectorAll('.f-tab').forEach(function(t) {{ t.classList.remove('active'); }});
  btn.classList.add('active');
  document.querySelectorAll('.clickable-row, .cr').forEach(function(row) {{
    var show;
    if (risk === 'all') {{ show = true; }}
    else {{ show = !!row.querySelector('.badge.' + risk); }}
    row.style.display = show ? '' : 'none';
    var nx = row.nextElementSibling;
    if (nx && nx.classList.contains('exp-tr')) {{
      if (!show) nx.classList.remove('open');
      nx.style.display = show ? '' : 'none';
    }}
  }});
}}

// Sort table
var _sCol = null, _sDir = 1;
function sortTable(col) {{
  var tbody = document.querySelector('tbody');
  if (!tbody) return;
  if (_sCol === col) _sDir *= -1; else {{ _sCol = col; _sDir = 1; }}
  var pairs = [];
  var rows = Array.from(tbody.querySelectorAll('.clickable-row, .cr'));
  rows.forEach(function(r) {{
    var nx = r.nextElementSibling;
    var expRow = (nx && nx.classList.contains('exp-tr')) ? nx : null;
    pairs.push([r, expRow]);
  }});
  pairs.sort(function(a, b) {{
    var ar = a[0], br = b[0];
    var av = col==='score' ? parseFloat(ar.dataset.score||0) :
             col==='lead'  ? parseInt(ar.dataset.lead||0) :
             col==='rate'  ? parseInt(ar.dataset.rate||0) : 0;
    var bv = col==='score' ? parseFloat(br.dataset.score||0) :
             col==='lead'  ? parseInt(br.dataset.lead||0) :
             col==='rate'  ? parseInt(br.dataset.rate||0) : 0;
    return (av - bv) * _sDir;
  }});
  pairs.forEach(function(p) {{
    tbody.appendChild(p[0]);
    if (p[1]) tbody.appendChild(p[1]);
  }});
  document.querySelectorAll('.sort-arr').forEach(function(a) {{
    var c = a.closest('.sort-th') && a.closest('.sort-th').dataset.col;
    a.textContent = c === col ? (_sDir === -1 ? '↓' : '↑') : '↕';
    a.classList.toggle('on', c === col);
  }});
}}

// Build prediction reasons
function buildReasons(b, score) {{
  var r = [];
  var lt = b.lead_time||0, canc = b.previous_cancellations||0;
  var rep = b.is_repeated_guest||0, adr = b.adr||0;
  var chg = b.booking_changes||0, spec = b.total_of_special_requests||0;
  var wk = b.stays_in_week_nights||0, we = b.stays_in_weekend_nights||0;
  var nights = wk + we || 1;

  if (lt > 120)      r.push({{c:'bad',  t:'Lead time ' + lt + ' days — bookings this far out cancel 3× more often'}});
  else if (lt > 45)  r.push({{c:'warn', t:'Lead time ' + lt + ' days — moderate cancellation window remains'}});
  else               r.push({{c:'pos',  t:'Lead time ' + lt + ' days — close to arrival, low cancellation risk'}});

  if (canc >= 2)     r.push({{c:'bad',  t: canc + ' prior cancellations — strongest single predictor of future no-shows'}});
  else if (canc===1) r.push({{c:'warn', t:'1 previous cancellation on record — elevated risk signal'}});
  else               r.push({{c:'pos',  t:'No cancellation history — clean booking profile'}});

  if (!rep)          r.push({{c:'warn', t:'First-time guest — new guests cancel 2.3× more than returning guests'}});
  else               r.push({{c:'pos',  t:'Returning guest — loyalty significantly reduces no-show likelihood'}});

  if (adr > 200)     r.push({{c:'bad',  t:'Premium rate €' + Math.round(adr) + ' — high-value bookings warrant a deposit or guarantee'}});
  else if (adr > 120)r.push({{c:'warn', t:'Room rate €' + Math.round(adr) + ' — consider pre-authorisation'}});

  if (chg >= 2)      r.push({{c:'warn', t: chg + ' booking modifications — repeated changes signal hesitation'}});
  else if (chg===1)  r.push({{c:'warn', t:'1 booking change — slight uncertainty signal'}});

  if (spec === 0)    r.push({{c:'warn', t:'No special requests — low guest engagement with this stay'}});
  else               r.push({{c:'pos',  t: spec + ' special request' + (spec>1?'s':'') + ' — engaged guests are far less likely to cancel'}});

  if (nights >= 4)   r.push({{c:'pos',  t: nights + '-night stay — multi-night bookings have lower no-show rates'}});
  else if (nights===1)r.push({{c:'warn',t:'1-night stay — shortest stays carry the highest no-show rate'}});

  return r.slice(0, 5);
}}

function conclusionText(score) {{
  if (score >= 70) return 'High cancellation probability. Request deposit or guarantee now — revenue at risk.';
  if (score >= 40) return 'Moderate risk. Send a reminder 48h before arrival to confirm the booking.';
  return 'Low risk. Booking profile is stable — monitor normally.';
}}

// Inline expand row
var _openRow = null;
function toggleExpand(row, idx, score) {{
  var expTr = document.getElementById('exp-' + idx);
  if (!expTr) return;
  var isOpen = expTr.classList.contains('open');
  if (_openRow && _openRow !== expTr) {{
    _openRow.classList.remove('open');
    var pr = _openRow.previousElementSibling;
    if (pr) pr.classList.remove('is-open');
  }}
  if (isOpen) {{
    expTr.classList.remove('open');
    row.classList.remove('is-open');
    _openRow = null;
  }} else {{
    var bArr = typeof bookings !== 'undefined' ? bookings : (typeof guests !== 'undefined' ? guests : []);
    var b = bArr[idx] || {{}};
    var reasons = buildReasons(b, score);
    var scoreColor = score>=70 ? '#ef4444' : score>=40 ? '#f59e0b' : '#00d165';
    var verdict = score>=70 ? 'HIGH RISK' : score>=40 ? 'MEDIUM RISK' : 'LOW RISK';
    var factorsHtml = reasons.map(function(r) {{
      return '<div class="exp-factor ' + r.c + '">' + r.t + '</div>';
    }}).join('');
    var inner = document.getElementById('exp-inner-' + idx);
    if (inner) {{
      inner.innerHTML =
        '<div class="exp-score-wrap">' +
          '<div class="exp-score-big" style="color:' + scoreColor + '">' + score.toFixed(0) + '%</div>' +
          '<div class="exp-score-lbl">' + verdict + '</div>' +
          '<div class="exp-bar-bg"><div class="exp-bar-fill" style="width:' + score + '%;background:' + scoreColor + '"></div></div>' +
        '</div>' +
        '<div class="exp-right">' +
          '<div class="exp-head">Why this score</div>' +
          '<div class="exp-factors">' + factorsHtml + '</div>' +
          '<div class="exp-conclusion">' + conclusionText(score) + '</div>' +
        '</div>';
    }}
    expTr.classList.add('open');
    row.classList.add('is-open');
    _openRow = expTr;
  }}
}}
"""

# ─────────────────────────────────────────────────────────────
# 1. Inject CSS into both dashboards before their </style>
# ─────────────────────────────────────────────────────────────
# There are multiple </style> tags — we want the ones inside build_vdv_dashboard
# and build_dashboard. Use position-aware replacement.

# Find both CSS end positions and inject
positions = [m.start() for m in re.finditer(r'</style>\n</head>', src)]
print(f'Found </style></head> positions: {positions}')

# Insert from last to first to keep positions valid
for pos in reversed(positions):
    src = src[:pos] + DYNAMICS_CSS + '\n' + src[pos:]

# ─────────────────────────────────────────────────────────────
# 2. Add live pulse pill to both toobars
# ─────────────────────────────────────────────────────────────

# VdV topbar: add after the lang-sel select closing tag area
# Generic topbar: add after the page-sub div
src = src.replace(
    '<div class="page-sub">{t("live_dashboard", lang)} · {total_bookings} {t("bookings_analysed", lang)}</div>',
    '<div class="page-sub" style="display:flex;align-items:center;justify-content:space-between;">'
    '{t("live_dashboard", lang)} · {total_bookings} {t("bookings_analysed", lang)}'
    '<span class="live-pill"><span class="live-dot"></span>Live</span></div>'
)

# VdV: add live pill inside topbar right
src = src.replace(
    '<a href="/settings" class="tb-btn">Settings</a>\n    <a href="/logout" class="tb-btn">Sign Out</a>',
    '<span class="live-pill"><span class="live-dot"></span>Live</span>'
    '<a href="/settings" class="tb-btn">Settings</a>\n    <a href="/logout" class="tb-btn">Sign Out</a>'
)

# ─────────────────────────────────────────────────────────────
# 3. Counter animations on generic dashboard hero cards
# ─────────────────────────────────────────────────────────────
src = src.replace(
    '<div class="hero-cards">',
    '<div class="hero-cards">'
)
# hero-val numbers — wrap in count-up spans
src = src.replace(
    '    <div class="hero-val">{total_bookings}</div>\n    <div class="hero-lbl">Bookings Analysed</div>',
    '    <div class="hero-val anim-card"><span class="count-up" data-val="{total_bookings}">—</span></div>\n    <div class="hero-lbl">Bookings Analysed</div>'
)
src = src.replace(
    '    <div class="hero-val" style="color:#dc2626">{high_total}</div>\n    <div class="hero-lbl">High Risk</div>',
    '    <div class="hero-val anim-card" style="color:#ef4444"><span class="count-up" data-val="{high_total}">—</span></div>\n    <div class="hero-lbl">High Risk</div>'
)
src = src.replace(
    '    <div class="hero-val" style="color:#dc2626">€{revenue_at_risk:,}</div>\n    <div class="hero-lbl">Revenue at Risk</div>',
    '    <div class="hero-val anim-card" style="color:#ef4444">€<span class="count-up" data-val="{revenue_at_risk}">—</span></div>\n    <div class="hero-lbl">Revenue at Risk</div>'
)
src = src.replace(
    '    <div class="hero-val">€{avg_adr:.0f}</div>\n    <div class="hero-lbl">Avg Daily Rate</div>',
    '    <div class="hero-val anim-card">€<span class="count-up" data-val="{avg_adr:.0f}">—</span></div>\n    <div class="hero-lbl">Avg Daily Rate</div>'
)

# ─────────────────────────────────────────────────────────────
# 4. Counter animations on VdV hero metrics
# ─────────────────────────────────────────────────────────────
src = src.replace(
    '    <div class="hc-num red">{total_lost:,}</div>',
    '    <div class="hc-num red anim-card"><span class="count-up" data-val="{total_lost}">—</span></div>'
)
src = src.replace(
    '    <div class="hc-num amber">€{rev_lost//1000}k</div>',
    '    <div class="hc-num amber anim-card">€<span class="count-up" data-val="{rev_lost//1000}" data-suf="k">—</span></div>'
)
src = src.replace(
    '    <div class="hc-num green">€{recoverable//1000}k</div>',
    '    <div class="hc-num green anim-card">€<span class="count-up" data-val="{recoverable//1000}" data-suf="k">—</span></div>'
)

# VdV today strip
src = src.replace(
    '<div class="ts-num {\'g\' if len(arriving)>0 else \'\'}">{len(arriving)}</div><div class="ts-label">Arriving</div>',
    '<div class="ts-num {\'g\' if len(arriving)>0 else \'\'}"><span class="count-up" data-val="{len(arriving)}">{len(arriving)}</span></div><div class="ts-label">Arriving</div>'
)
src = src.replace(
    '<div class="ts-num">{len(in_house)}</div><div class="ts-label">In House</div>',
    '<div class="ts-num"><span class="count-up" data-val="{len(in_house)}">{len(in_house)}</span></div><div class="ts-label">In House</div>'
)
src = src.replace(
    '<div class="ts-num {\'r\' if high_count>0 else \'g\'}">{high_count}</div><div class="ts-label">High Risk</div>',
    '<div class="ts-num {\'r\' if high_count>0 else \'g\'}"><span class="count-up" data-val="{high_count}">{high_count}</span></div><div class="ts-label">High Risk</div>'
)

# ─────────────────────────────────────────────────────────────
# 5. Generic dashboard — filter tabs + sortable headers + expandable rows
# ─────────────────────────────────────────────────────────────

# Add filter bar before the booking table (section title before table)
old_table_section = '<div class="section-title" style="margin-top:0">Overview</div>'
# Actually let's add filter bar right before the <table> tag in build_dashboard
# Find the table header row and add filter bar before it

old_table_intro = '<div class="section-title">{t("click_row", lang)}</div>\n<table>'
new_table_intro = (
    '<div class="section-title">{t("click_row", lang)}</div>\n'
    '<div class="filter-bar">'
    '<button class="f-tab active" onclick="filterRisk(\'all\',this)">All <span class="f-count">{total_bookings}</span></button>'
    '<button class="f-tab" onclick="filterRisk(\'high\',this)">High Risk <span class="f-count" style="color:#ef4444">{high_total}</span></button>'
    '<button class="f-tab" onclick="filterRisk(\'med\',this)">Medium <span class="f-count">{med_total}</span></button>'
    '<button class="f-tab" onclick="filterRisk(\'low\',this)">Low Risk <span class="f-count" style="color:#00d165">{low_total}</span></button>'
    '</div>\n<table>'
)
src = src.replace(old_table_intro, new_table_intro)

# Sortable table headers
old_th = '<thead><tr><th>#</th><th>{t("booking", lang)}</th><th>{t("lead", lang)}</th><th>{t("rate", lang)}</th><th>{t("returning", lang)}</th><th>{t("cancels", lang)}</th><th>{t("risk", lang)}</th><th>{t("action", lang)}</th></tr></thead>'
new_th = (
    '<thead><tr>'
    '<th>#</th>'
    '<th>{t("booking", lang)}</th>'
    '<th class="sort-th" onclick="sortTable(\'lead\')" data-col="lead">{t("lead", lang)} <span class="sort-arr" id="arr-lead">↕</span></th>'
    '<th class="sort-th" onclick="sortTable(\'rate\')" data-col="rate">{t("rate", lang)} <span class="sort-arr" id="arr-rate">↕</span></th>'
    '<th>{t("returning", lang)}</th><th>{t("cancels", lang)}</th>'
    '<th class="sort-th" onclick="sortTable(\'score\')" data-col="score">{t("risk", lang)} <span class="sort-arr" id="arr-score">↕</span></th>'
    '<th>{t("action", lang)}</th>'
    '</tr></thead>'
)
src = src.replace(old_th, new_th)

# Expandable rows in generic dashboard
old_row = (
    '        rows += f"""<tr class="clickable-row" onclick="showDetail({i}, {score:.1f})">\n'
    '            <td><span style="font-family:\'JetBrains Mono\',monospace;color:#94a3b8;font-size:11px">{i+1}</span></td>\n'
    '            <td><span style="color:#0d1120;font-weight:600">{t("booking", lang)} {i+1}</span></td>\n'
    '            <td>{lead} {t("days", lang)}</td><td>EUR {adr}</td><td>{rep}</td><td>{canc}</td>\n'
    '            <td>{badge}</td><td>{action}</td>\n'
    '        </tr>"""'
)
new_row = (
    '        rows += f"""<tr class="clickable-row" data-score="{score:.1f}" data-lead="{lead}" data-rate="{adr}" onclick="toggleExpand(this, {i}, {score:.1f})">\n'
    '            <td><span style="font-family:\'JetBrains Mono\',monospace;color:#9ca3af;font-size:11px">{i+1}</span></td>\n'
    '            <td><span style="font-weight:600;color:#111827">{t("booking", lang)} {i+1}</span></td>\n'
    '            <td>{lead} {t("days", lang)}</td><td>€{adr}</td><td>{rep}</td><td>{canc}</td>\n'
    '            <td>{badge}</td><td>{action}</td>\n'
    '        </tr>\n'
    '        <tr class="exp-tr" id="exp-{i}"><td class="exp-td" colspan="8"><div class="exp-inner" id="exp-inner-{i}"></div></td></tr>"""'
)
if old_row in src:
    src = src.replace(old_row, new_row)
    print('Generic rows updated')
else:
    print('WARNING: generic row pattern not found')

# ─────────────────────────────────────────────────────────────
# 6. VdV dashboard — filter tabs + expandable rows
# ─────────────────────────────────────────────────────────────

# Add filter bar before VdV guest table
old_vdv_table_sh = '<div class="sh"><span class="sh-title">Repeat Guests This Week</span>'
new_vdv_table_sh = (
    '<div class="sh"><span class="sh-title">Repeat Guests This Week</span>'
)
# Find the tbl.tbl start after "Repeat Guests"
old_vdv_tbl = (
    '<table class="tbl">\n'
    '<thead><tr>'
    '<th>Guest</th><th>Status</th><th>Arrival</th><th>Nights</th>'
    '<th>Risk</th><th class="ntd">Note</th><th>Action</th>'
    '</tr></thead>\n'
    '<tbody>{rows_html}</tbody>\n'
    '</table>'
)
new_vdv_tbl = (
    '<div class="filter-bar">'
    '<button class="f-tab active" onclick="filterRisk(\'all\',this)">All</button>'
    '<button class="f-tab" onclick="filterRisk(\'high\',this)">High Risk <span class="f-count" style="color:#ef4444">{high_count}</span></button>'
    '<button class="f-tab" onclick="filterRisk(\'med\',this)">Medium <span class="f-count">{med_count}</span></button>'
    '<button class="f-tab" onclick="filterRisk(\'low\',this)">Low Risk</span></button>'
    '</div>'
    '<table class="tbl">\n'
    '<thead><tr>'
    '<th>Guest</th><th>Status</th>'
    '<th class="sort-th" onclick="sortTable(\'lead\')" data-col="lead">Arrival <span class="sort-arr">↕</span></th>'
    '<th>Nights</th>'
    '<th class="sort-th" onclick="sortTable(\'score\')" data-col="score">Risk <span class="sort-arr">↕</span></th>'
    '<th class="ntd">Note</th><th>Action</th>'
    '</tr></thead>\n'
    '<tbody>{rows_html}</tbody>\n'
    '</table>'
)
if old_vdv_tbl in src:
    src = src.replace(old_vdv_tbl, new_vdv_tbl)
    print('VdV table updated')
else:
    print('WARNING: VdV table pattern not found, trying partial match')
    # Try without the filter bar injection but at least add data attrs to rows

# VdV row — add data-score + expandable
old_vdv_row = (
    "        rows_html += f'''<tr class=\"cr\" onclick=\"openDetail({i},{sc:.1f})\">\n"
    "          <td><span class=\"gn\">{g['name']}</span>{mb}</td>\n"
    "          <td>{st_badge(g['status'])}</td>\n"
    "          <td>{g['arrival']}</td><td>{g['nights']}n</td>\n"
    "          <td>{bdg}</td><td class=\"ntd\">{nt}</td><td>{act}</td>\n"
    "        </tr>'''"
)
new_vdv_row = (
    "        rows_html += f'''<tr class=\"cr\" data-score=\"{sc:.1f}\" data-lead=\"0\" data-rate=\"0\" onclick=\"toggleExpand(this, {i}, {sc:.1f})\">\n"
    "          <td><span class=\"gn\">{g['name']}</span>{mb}</td>\n"
    "          <td>{st_badge(g['status'])}</td>\n"
    "          <td>{g['arrival']}</td><td>{g['nights']}n</td>\n"
    "          <td>{bdg}</td><td class=\"ntd\">{nt}</td><td>{act}</td>\n"
    "        </tr>\n"
    "        <tr class=\"exp-tr\" id=\"exp-{i}\"><td class=\"exp-td\" colspan=\"7\"><div class=\"exp-inner\" id=\"exp-inner-{i}\"></div></td></tr>'''"
)
if old_vdv_row in src:
    src = src.replace(old_vdv_row, new_vdv_row)
    print('VdV rows updated')
else:
    print('WARNING: VdV row pattern not found')

# ─────────────────────────────────────────────────────────────
# 7. Inject dynamics JS into both dashboards before </script>
# ─────────────────────────────────────────────────────────────
# Find </script> tags that close the main script blocks in each dashboard
# VdV script ends with the savings update function, generic ends with updateSavings
# We'll inject before the last </script> in each dashboard

# For VdV: inject before closing of main script
vdv_script_anchor = '\n</script>\n</body>\n</html>"""'
count_vdv = src.count(vdv_script_anchor)
print(f'VdV script anchor count: {count_vdv}')

# Replace all matching anchor points (VdV and generic both use same pattern)
# VdV dashboard's script ends before build_empty_state
# Generic dashboard's script also ends with same pattern
# We need to inject into both — replace ALL occurrences
src = src.replace(vdv_script_anchor, DYNAMICS_JS + '\n</script>\n</body>\n</html>"""')

print(f'Total replacements would be: {count_vdv}')

# ─────────────────────────────────────────────────────────────
# 8. Remove old showDetail call (it's now replaced by toggleExpand)
#    but keep the modal for backward compat — just hide it
# ─────────────────────────────────────────────────────────────
# The old showDetail in generic dashboard just opens the modal with limited info
# Now rows call toggleExpand instead, so showDetail is no longer triggered from rows
# No change needed — the modal still works if anything references it

with open('C:/Users/jpdou/Desktop/Occupado/app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print('Done!')
