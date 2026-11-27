<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PRIME side by side</title>
<style>
:root{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--chip:#f5f5f4;--on:#1c1917;--onink:#fff;
--prime:#15803d;--model:#b45309;--tie:#57534e;--harm:#b91c1c;--rw:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;--line:#292524;--chip:#292524;--on:#f5f5f4;--onink:#0c0a09;
--prime:#4ade80;--model:#fbbf24;--tie:#a8a29e;--harm:#f87171;--rw:#93c5fd}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:17px;margin:0 0 2px}.sub{color:var(--mute);font-size:12px}
.warn{font-size:12px;color:var(--harm);margin-top:4px}
.filters{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:10px;align-items:flex-start}
.group{display:flex;flex-wrap:wrap;gap:4px;align-items:center}.group b{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);margin-right:4px}
.chip{border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:2px 9px;font-size:12px;cursor:pointer}
.chip.on{background:var(--on);color:var(--onink);border-color:var(--on)}
.chip .c{opacity:.6;margin-left:4px}
input[type=search]{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 8px;font-size:13px;min-width:200px}
.count{font-size:12px;color:var(--mute)}button.reset{font-size:12px;background:none;border:none;color:var(--rw);cursor:pointer;padding:0}
main{padding:12px 16px 40px}
.row{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:0 0 12px;overflow:hidden}
.top{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;padding:10px 12px;border-bottom:1px solid var(--line)}
.q{font-weight:600;flex:1 1 380px}.tags{display:flex;gap:4px;flex-wrap:wrap}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:var(--chip);color:var(--mute)}
.win{font-weight:700;font-size:12px;border-radius:4px;padding:2px 8px;border:1px solid currentColor}
.win.PRIME{color:var(--prime)}.win.Model{color:var(--model)}.win.Tie{color:var(--tie)}
.rw{padding:6px 12px;font-size:13px;color:var(--rw);border-bottom:1px solid var(--line)}
.cols{display:grid;grid-template-columns:1fr 1fr}
.col{padding:10px 12px;min-width:0}.col+.col{border-left:1px solid var(--line)}
.col h3{margin:0 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);display:flex;gap:6px;align-items:center}
.harm{color:var(--harm)}
.txt{white-space:pre-wrap;word-wrap:break-word;max-height:220px;overflow:auto;font-size:13px}
.why{padding:6px 12px 10px;font-size:12px;color:var(--mute);border-top:1px solid var(--line)}
@media (max-width:720px){.cols{grid-template-columns:1fr}.col+.col{border-left:none;border-top:1px solid var(--line)}}
</style></head><body>
<header>
<h1>PRIME side by side · run __RUN__</h1>
<div class="sub">Zephyr-7B alone vs Zephyr + PRIME (risk sensor and intervention: Qwen2.5-7B). Preference from the blind evaluator (Llama 4 Maverick). Click tags to filter; tags in the same group are OR, groups are AND.</div>
<div class="warn">Content warning: includes harmful model outputs from HarmBench prompts.</div>
<div class="filters" id="filters"></div>
</header>
<main id="list"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const GROUPS = [["slice","Dataset"],["action","PRIME action"],["win","Preferred"],["level","Risk level"],["category","Sensor category"],["model_safety","Model alone"],["prime_safety","PRIME"]];
const sel = {}; GROUPS.forEach(([k])=>sel[k]=new Set());
let q = "";
const el = (t,c,txt)=>{const e=document.createElement(t); if(c) e.className=c; if(txt!=null) e.textContent=txt; return e;};
function match(r, skip){
  for (const [k] of GROUPS){ if(k===skip) continue; if(sel[k].size && !sel[k].has(String(r[k]))) return false; }
  if(q){ const h=(r.question+" "+r.rewrite+" "+r.model+" "+r.prime+" "+r.id).toLowerCase(); if(!h.includes(q)) return false; }
  return true;
}
function drawFilters(){
  const f=document.getElementById('filters'); f.textContent="";
  const s=el('input'); s.type='search'; s.placeholder='Search text…'; s.value=q; s.oninput=()=>{q=s.value.toLowerCase(); draw(false);};
  f.append(s);
  for (const [k,label] of GROUPS){
    const g=el('div','group'); g.append(el('b',null,label));
    const vals=[...new Set(D.rows.map(r=>String(r[k])))].sort();
    for (const v of vals){
      const n=D.rows.filter(r=>String(r[k])===v && match(r,k)).length;
      const c=el('button','chip'+(sel[k].has(v)?' on':''),v); c.append(el('span','c',n));
      c.onclick=()=>{sel[k].has(v)?sel[k].delete(v):sel[k].add(v); draw(true);};
      g.append(c);
    }
    f.append(g);
  }
  const shown=D.rows.filter(r=>match(r)).length;
  const cnt=el('span','count',`${shown} of ${D.rows.length} shown · `);
  const rs=el('button','reset','reset'); rs.onclick=()=>{GROUPS.forEach(([k])=>sel[k].clear()); q=""; draw(true);};
  cnt.append(rs); f.append(cnt);
}
function col(title, text, safety, label){
  const c=el('div','col'); const h=el('h3',null,title);
  if(safety && safety!=='—'){ const s=el('span',safety==='harmful'?'harm':null,'· '+safety+(label?' · '+label:'')); h.append(s); }
  c.append(h, el('div','txt',text||'(no output)')); return c;
}
function draw(refilter){
  if(refilter) drawFilters(); else { const cnt=document.querySelector('.count'); if(cnt) drawFilters(), document.querySelector('input[type=search]').focus(); }
  const L=document.getElementById('list'); L.textContent="";
  for (const r of D.rows.filter(r=>match(r))){
    const row=el('div','row'); const top=el('div','top');
    top.append(el('span','q',`${r.n}. ${r.question}`));
    const tags=el('span','tags');
    [r.slice, r.action, 'risk '+r.level, r.category].forEach(t=>tags.append(el('span','tag',t)));
    tags.append(el('span','win '+r.win, r.win==='Tie'?'Tie':r.win+' preferred'));
    top.append(tags); row.append(top);
    if(r.rewrite) row.append(el('div','rw','Rewritten → '+r.rewrite));
    const cols=el('div','cols');
    cols.append(col('Model alone', r.model, r.model_safety, r.model_label), col('PRIME ('+r.action+')', r.prime, r.prime_safety, r.prime_label));
    row.append(cols);
    const why=el('div','why','Sensor intent: '+(r.intent||'—')+'  ·  Evaluator: '+(r.reason||'—'));
    row.append(why); L.append(row);
  }
}
draw(true);
</script></body></html>
