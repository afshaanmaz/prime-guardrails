<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>PRIME across models</title>
<style>
:root{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--chip:#f5f5f4;--on:#1c1917;--onink:#fff;
--prime:#15803d;--model:#b45309;--tie:#57534e;--harm:#b91c1c;--rw:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;--line:#292524;--chip:#292524;--on:#f5f5f4;--onink:#0c0a09;
--prime:#4ade80;--model:#fbbf24;--tie:#a8a29e;--harm:#f87171;--rw:#93c5fd}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;max-height:55vh;overflow:auto}
h1{font-size:17px;margin:0 0 2px}.sub{color:var(--mute);font-size:12px}
.warn{font-size:12px;color:var(--harm);margin-top:4px}
.summary{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.sum{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:6px 10px;font-size:12px}
.sum b{display:block;font-size:13px}
.filters{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:10px;align-items:flex-start}
.group{display:flex;flex-wrap:wrap;gap:4px;align-items:center}.group b{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);margin-right:4px}
.chip{border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:2px 9px;font-size:12px;cursor:pointer}
.chip.on{background:var(--on);color:var(--onink);border-color:var(--on)}
.chip .c{opacity:.6;margin-left:4px}
input[type=search]{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 8px;font-size:13px;min-width:200px}
.count{font-size:12px;color:var(--mute)}button.reset{font-size:12px;background:none;border:none;color:var(--rw);cursor:pointer;padding:0}
main{padding:12px 16px 40px}
.row{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:0 0 14px;overflow:hidden}
.top{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;padding:10px 12px;border-bottom:1px solid var(--line)}
.q{font-weight:600;flex:1 1 380px}.tags{display:flex;gap:4px;flex-wrap:wrap}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:var(--chip);color:var(--mute)}
.rw{padding:6px 12px;font-size:13px;color:var(--rw);border-bottom:1px solid var(--line)}
.intent{padding:4px 12px;font-size:12px;color:var(--mute);border-bottom:1px solid var(--line)}
.models{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr))}
.mcol{min-width:0}.mcol+.mcol{border-left:1px solid var(--line)}
.mhead{display:flex;justify-content:space-between;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--chip)}
.mhead span{font-weight:600;font-size:13px}
.win{font-weight:700;font-size:11px;border-radius:4px;padding:1px 7px;border:1px solid currentColor;white-space:nowrap}
.win.PRIME{color:var(--prime)}.win.Model{color:var(--model)}.win.Tie,.win.Not{color:var(--tie)}
.ans{padding:8px 12px}.ans+.ans{border-top:1px dashed var(--line)}
.ans h3{margin:0 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
.harm{color:var(--harm)}
.txt{white-space:pre-wrap;word-wrap:break-word;max-height:200px;overflow:auto;font-size:13px}
.why{padding:6px 12px 10px;font-size:12px;color:var(--mute);border-top:1px solid var(--line)}
@media (max-width:900px){.models{grid-template-columns:1fr}.mcol+.mcol{border-left:none;border-top:2px solid var(--line)}}
</style></head><body>
<header>
<div class="sub"><a href="index.html" style="color:var(--rw)">← All experiments</a></div>
<h1>PRIME across protected models</h1>
<div class="sub">Models: __MODELS__. Same requests and the same PRIME decisions for every model (risk sensor and intervention: Qwen2.5-7B). Preference from the blind evaluator (Llama 4 Maverick). Tags in the same group are OR; groups are AND.</div>
<div class="warn">Content warning: includes harmful model outputs from HarmBench prompts.</div>
<div class="summary" id="summary"></div>
<div class="filters" id="filters"></div>
</header>
<main id="list"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
document.documentElement.style.setProperty('--n', D.models.length);
const harmVals = r => D.models.flatMap(m => { const x = r.m[m.key]; if (!x) return [];
  const o = []; if (x.alone_safety === 'harmful') o.push(m.name + ' alone'); if (x.prime_safety === 'harmful') o.push(m.name + ' + PRIME'); return o; });
const GROUPS = [
  ["slice", "Dataset", r => [r.slice]], ["action", "PRIME action", r => [r.action]],
  ["level", "Risk level", r => [r.level]], ["category", "Sensor category", r => [r.category]],
  ...D.models.map(m => ["win_" + m.key, m.name + ": preferred", r => [r.m[m.key] ? r.m[m.key].win : 'Missing']]),
  ["harm", "Harmful answer (any of)", harmVals]];
const sel = {}; GROUPS.forEach(([k]) => sel[k] = new Set());
let q = "";
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
function match(r, skip) {
  for (const [k, , f] of GROUPS) { if (k === skip || !sel[k].size) continue; if (!f(r).some(v => sel[k].has(String(v)))) return false; }
  if (q) { const h = [r.question, r.rewrite, r.id, ...Object.values(r.m).flatMap(x => [x.alone, x.prime])].join(' ').toLowerCase(); if (!h.includes(q)) return false; }
  return true;
}
function drawSummary() {
  const S = document.getElementById('summary'); S.textContent = "";
  const rows = D.rows.filter(r => match(r));
  for (const m of D.models) {
    const xs = rows.map(r => r.m[m.key]).filter(Boolean), c = w => xs.filter(x => x.win === w).length;
    const ha = xs.filter(x => x.alone_safety === 'harmful').length, hp = xs.filter(x => x.prime_safety === 'harmful').length;
    const s = el('div', 'sum'); s.append(el('b', null, m.name));
    s.append(el('span', null, `PRIME ${c('PRIME')} · Model ${c('Model')} · Tie ${c('Tie')}  |  harmful: alone ${ha} → PRIME ${hp}`));
    S.append(s);
  }
}
function drawFilters() {
  const f = document.getElementById('filters'); f.textContent = "";
  const s = el('input'); s.type = 'search'; s.placeholder = 'Search text…'; s.value = q;
  s.oninput = () => { q = s.value.toLowerCase(); drawList(); drawSummary(); };
  f.append(s);
  for (const [k, label, fn] of GROUPS) {
    const g = el('div', 'group'); g.append(el('b', null, label));
    const vals = [...new Set(D.rows.flatMap(r => fn(r).map(String)))].sort();
    if (!vals.length) continue;
    for (const v of vals) {
      const n = D.rows.filter(r => fn(r).map(String).includes(v) && match(r, k)).length;
      const c = el('button', 'chip' + (sel[k].has(v) ? ' on' : ''), v); c.append(el('span', 'c', n));
      c.onclick = () => { sel[k].has(v) ? sel[k].delete(v) : sel[k].add(v); draw(); };
      g.append(c);
    }
    f.append(g);
  }
  const shown = D.rows.filter(r => match(r)).length;
  const cnt = el('span', 'count', `${shown} of ${D.rows.length} shown · `);
  const rs = el('button', 'reset', 'reset'); rs.onclick = () => { GROUPS.forEach(([k]) => sel[k].clear()); q = ""; draw(); };
  cnt.append(rs); f.append(cnt);
}
function ans(title, text, safety, label) {
  const a = el('div', 'ans'); const h = el('h3', null, title);
  if (safety && safety !== '—') h.append(el('span', safety === 'harmful' ? 'harm' : null, ' · ' + safety + (label ? ' · ' + label : '')));
  a.append(h, el('div', 'txt', text || '(no output)')); return a;
}
function drawList() {
  const L = document.getElementById('list'); L.textContent = "";
  for (const r of D.rows.filter(r => match(r))) {
    const row = el('div', 'row'); const top = el('div', 'top');
    top.append(el('span', 'q', `${r.n}. ${r.question}`));
    const tags = el('span', 'tags');
    [r.slice, 'PRIME: ' + r.action, 'risk ' + r.level, r.category].forEach(t => tags.append(el('span', 'tag', t)));
    top.append(tags); row.append(top);
    if (r.rewrite) row.append(el('div', 'rw', 'Rewritten → ' + r.rewrite));
    if (r.intent) row.append(el('div', 'intent', 'Sensor intent: ' + r.intent));
    const grid = el('div', 'models');
    for (const m of D.models) {
      const x = r.m[m.key]; const c = el('div', 'mcol'); const h = el('div', 'mhead');
      h.append(el('span', null, m.name));
      if (x) h.append(el('span', 'win ' + x.win.split(' ')[0], x.win === 'Tie' || x.win === 'Not scored' ? x.win : x.win + ' preferred'));
      c.append(h);
      if (x) {
        c.append(ans('Model alone', x.alone, x.alone_safety, x.alone_label), ans('With PRIME', x.prime, x.prime_safety, x.prime_label));
        if (x.reason) c.append(el('div', 'why', 'Evaluator: ' + x.reason));
      } else c.append(el('div', 'ans', '(not run)'));
      grid.append(c);
    }
    row.append(grid); L.append(row);
  }
}
function draw() { drawFilters(); drawSummary(); drawList(); }
draw();
</script></body></html>
