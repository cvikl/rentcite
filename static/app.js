/* Homerule front end. Everything shown comes from the API; nothing is decided here. */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const RESULT_LABEL = { applies: 'In force', unknown: 'Unknown', superseded: 'Superseded', not_yet_effective: 'Not yet effective', pending: 'Proposed' };
  const RESULT_ES = { applies: 'En vigor', unknown: 'Desconocido', superseded: 'Reemplazada', not_yet_effective: 'Aún no vigente', pending: 'Propuesta' };
  const FACT_Q = {
    year_built: { q: 'What year was the building built?', type: 'number', ph: 'e.g. 1962' },
    units: { q: 'How many units are in the building?', type: 'number', ph: 'e.g. 12' },
    certificate_of_occupancy_date: { q: 'When was the first certificate of occupancy issued?', type: 'date' },
    owner_type: { q: 'Who owns the building?', type: 'select', opts: ['natural_person', 'llc', 'corporation', 'reit', 'trust', 'nonprofit', 'government'] },
    property_type: { q: 'What kind of building is it?', type: 'select', opts: ['multifamily', 'single_family', 'condominium', 'duplex', 'mixed_use', 'mobile_home', 'other'] },
    owner_occupied: { q: 'Does the owner live in the building?', type: 'select', opts: ['true', 'false'] },
    rent_subsidized: { q: 'Is the rent subsidized by a government program?', type: 'select', opts: ['true', 'false'] },
    tenancy_length_months: { q: 'How many months has the tenant lived there?', type: 'number' },
    lease_type: { q: 'What kind of lease?', type: 'select', opts: ['month_to_month', 'fixed_term'] },
    building_age_years: { q: 'What year was the building built?', type: 'number', ph: 'e.g. 1962', maps: 'year_built' },
    new_construction: { q: 'What year was the building built?', type: 'number', ph: 'e.g. 1962', maps: 'year_built' },
  };

  const state = { meta: null, address: null, lookup: null, asOf: todayISO(), facts: {}, lang: 'en', prev: {}, free: null, timeline: null };

  function todayISO() { const d = new Date(); return d.toISOString().slice(0, 10); }
  function fmtDate(s) { if (!s) return '—'; const d = new Date(s + 'T00:00:00'); return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }); }
  function busy(msg) { const b = $('#busy'); if (!msg) { b.hidden = true; return; } b.textContent = msg; b.hidden = false; }
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) { let d = ''; try { d = (await r.json()).detail || ''; } catch (e) { /* ignore */ } throw new Error(d || `${r.status} ${r.statusText}`); }
    return r.json();
  }

  // ---------------------------------------------------------------- routing
  function route() {
    const h = location.hash || '#/';
    let view = 'notice';
    if (h.startsWith('#/changes')) view = 'changes';
    else if (h.startsWith('#/record')) view = 'record';
    else if (h.startsWith('#/add')) view = 'add';
    $$('.view').forEach((v) => { v.hidden = v.dataset.view !== view; });
    $$('.views a').forEach((a) => { if (a.dataset.view === view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    if (view === 'changes') loadChanges();
    if (view === 'record') loadRecord();
    const m = h.match(/^#\/a\/(addr_\d+)(?:\?(.*))?/);
    if (m) {
      const params = new URLSearchParams(m[2] || '');
      if (params.get('as_of')) { state.asOf = params.get('as_of'); $('#asof').value = state.asOf; }
      if (!state.address || state.address.address_id !== m[1]) openAddress(m[1]);
    }
  }
  window.addEventListener('hashchange', route);

  // ---------------------------------------------------------------- search
  const q = $('#q'), suggest = $('#suggest');
  let sugTimer = null, sugIndex = -1, sugItems = [];
  q.addEventListener('input', () => { $('#clear-q').hidden = !q.value; clearTimeout(sugTimer); sugTimer = setTimeout(() => fetchSuggest(q.value), 120); });
  q.addEventListener('focus', () => { if (q.value) fetchSuggest(q.value); });
  q.addEventListener('keydown', (e) => {
    if (suggest.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); sugIndex = Math.min(sugIndex + 1, sugItems.length - 1); paintSug(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sugIndex = Math.max(sugIndex - 1, 0); paintSug(); }
    else if (e.key === 'Enter') { e.preventDefault(); const it = sugItems[sugIndex] || sugItems[0]; if (it) pick(it); }
    else if (e.key === 'Escape') { closeSug(); }
  });
  $('#search-form').addEventListener('submit', (e) => e.preventDefault());
  $('#clear-q').addEventListener('click', () => { q.value = ''; $('#clear-q').hidden = true; closeSug(); q.focus(); });
  document.addEventListener('click', (e) => { if (!$('#search-form').contains(e.target)) closeSug(); });
  async function fetchSuggest(text) {
    if (!text.trim()) { closeSug(); return; }
    try { sugItems = await api(`/api/addresses?q=${encodeURIComponent(text)}&limit=12`); } catch (e) { sugItems = []; }
    sugIndex = -1; paintSug();
  }
  function paintSug() {
    if (!sugItems.length) {
      suggest.innerHTML = `<li class="none">No sample address matches. Open the notice and use “Any other address” to look one up live.</li>`;
    } else {
      suggest.innerHTML = sugItems.map((a, i) => `<li role="option" aria-selected="${i === sugIndex}" data-i="${i}"><span>${esc(a.label)}</span><span class="meta">${a.jurisdiction && a.jurisdiction.city ? esc(a.jurisdiction.city) + ' · ' : ''}${a.year_built ? 'built ' + a.year_built : 'year unknown'} · ${a.units ? a.units + ' units' : 'units unknown'}</span></li>`).join('');
      $$('li[data-i]', suggest).forEach((li) => li.addEventListener('mousedown', (e) => { e.preventDefault(); pick(sugItems[+li.dataset.i]); }));
    }
    suggest.hidden = false; q.setAttribute('aria-expanded', 'true');
  }
  function closeSug() { suggest.hidden = true; q.setAttribute('aria-expanded', 'false'); }
  function pick(a) { closeSug(); q.value = a.label; $('#clear-q').hidden = false; location.hash = `#/a/${a.address_id}`; }

  // ---------------------------------------------------------------- as-of
  const asof = $('#asof');
  asof.value = state.asOf;
  asof.addEventListener('change', () => { if (!asof.value) return; state.asOf = asof.value; rerun(); });
  $('#asof-today').addEventListener('click', () => { state.asOf = todayISO(); asof.value = state.asOf; rerun(); });

  function rerun() {
    if (state.free) return runFree(state.free);
    if (state.address) openAddress(state.address.address_id, true);
  }

  // ---------------------------------------------------------------- notice
  async function openAddress(id, keep) {
    state.free = null;
    if (!keep) { state.facts = {}; state.prev = {}; }
    const body = $('#sheet-body'); $('#sheet-empty').hidden = true; body.hidden = false;
    if (!keep) body.innerHTML = `<div class="skel"><div></div><div></div><div></div><div></div></div>`;
    try {
      const facts = Object.keys(state.facts).length ? `&facts=${encodeURIComponent(JSON.stringify(state.facts))}` : '';
      const [lk, tl] = await Promise.all([
        api(`/api/lookup/${id}?as_of=${state.asOf}${facts}`),
        keep && state.timeline && state.timeline.id === id ? Promise.resolve(state.timeline.points) : api(`/api/timeline?address_id=${id}`),
      ]);
      state.address = lk.address; state.lookup = lk; state.timeline = { id, points: tl };
      q.value = `${lk.address.street}, ${lk.address.postal_city}, ${lk.address.state} ${lk.address.zip}`; $('#clear-q').hidden = false;
      renderNotice(lk);
      if (location.hash !== `#/a/${id}`) history.replaceState(null, '', `#/a/${id}`);
    } catch (e) {
      body.innerHTML = `<div class="err-sheet"><h1>Nothing posted</h1><p>${esc(e.message)}</p></div>`;
    }
  }

  async function runFree(params) {
    state.free = params; state.address = null; state.timeline = null;
    const body = $('#sheet-body'); $('#sheet-empty').hidden = true; body.hidden = false;
    body.innerHTML = `<div class="skel"><div></div><div></div><div></div><div></div></div>`;
    busy('Resolving the legal jurisdiction with the Census Geocoder');
    try {
      const qs = new URLSearchParams({ ...params, as_of: state.asOf });
      if (Object.keys(state.facts).length) qs.set('facts', JSON.stringify(state.facts));
      const lk = await api(`/api/lookup-free?${qs}`);
      state.lookup = lk; renderNotice(lk);
    } catch (e) {
      body.innerHTML = `<div class="err-sheet"><h1>Nothing posted</h1><p>${esc(e.message)}</p></div>`;
    } finally { busy(null); }
  }

  function stampHTML(res, e, cls) {
    const label = state.lang === 'es' ? RESULT_ES[res] : RESULT_LABEL[res];
    let sub = '';
    if (res === 'not_yet_effective') sub = `<small>from ${esc(e.effective_date || '?')}</small>`;
    if (res === 'applies' && e.effective_date) sub = `<small>since ${esc(e.effective_date)}</small>`;
    if (res === 'pending') sub = `<small>not law</small>`;
    if (res === 'unknown') sub = `<small>fact missing</small>`;
    return `<span class="stamp ${res} ${cls || ''}">${esc(label)}${sub}</span>`;
  }

  function condText(c) {
    if (!c) return '';
    if (c.field) {
      const v = Array.isArray(c.value) ? c.value.join(', ') : c.value;
      if (c.value === '__unknowable__') return `<code>${esc(c.note || 'a fact not in any record')}</code>`;
      return `<code>${esc(c.field)} ${esc(c.operator)} ${esc(v)}</code>`;
    }
    if (c.type === 'ALWAYS' || !c.clauses || !c.clauses.length) return '<code>every rental in the jurisdiction</code>';
    const inner = c.clauses.map(condText);
    if (c.type === 'NOT') return `not (${inner[0]})`;
    return inner.length > 1 ? `(${inner.join(` <i>${c.type.toLowerCase()}</i> `)})` : inner[0];
  }

  function ruleHTML(e, idx) {
    const r = e.rule || {};
    const res = e.result.replace(/ /g, '_');
    const changed = state.prev[e.rule_id] && state.prev[e.rule_id] !== res;
    const missing = (e.missing_facts || []).filter((f) => FACT_Q[f]);
    const ask = res === 'unknown' && missing.length ? askHTML(e, missing[0]) : '';
    const conflict = e.conflict_flag ? `<p class="conflict">Conflict: ${esc(e.conflict_reason)}</p>` : '';
    const v = r.verification || {};
    const ver = v.supported === undefined ? '' : `<p class="ver">Verifier: <span class="${v.supported ? 'ok' : 'bad'}">${v.supported ? 'quote supports the record' : 'quote does not support the record'}</span>${(v.issues || []).length ? ' · ' + esc(v.issues.join(' ')) : ''}${(v.corrected_fields || []).length ? ' · corrected ' + esc(v.corrected_fields.join(', ')) : ''}${v.cache_key ? ` · <a href="/api/llm-record/${esc(v.cache_key)}" target="_blank" rel="noopener">verifier record</a>` : ''}</p>`;
    const ex = (r.exemptions || []).length ? `<p class="tree">Exempt: ${r.exemptions.map((x) => `${esc(x.description)} ${condText(x.conditions)}`).join('; ')}</p>` : '';
    return `<article class="rule ${res}" data-rule="${esc(e.rule_id)}" id="r-${idx}">
      <div class="main">
        <p class="req">${esc(e.plain_language || r.title)}</p>
        ${e.plain_language_es ? `<p class="req-es" lang="es">${esc(e.plain_language_es)}</p>` : ''}
        <p class="strip"><span class="cite">${esc(e.citation)}</span>${r.key_value ? `<span>${esc(r.key_value.label)}: <b>${esc(r.key_value.value)}</b></span>` : ''}<span class="lvl ${esc(e.level)}">${esc(e.level)} rule</span>${r.effective_date ? `<span>effective ${esc(r.effective_date)}</span>` : '<span>no effective date in text</span>'}${r.superseded_date ? `<span>until ${esc(r.superseded_date)}</span>` : ''}</p>
        <p class="why"><b>Why:</b> ${esc(e.reason)}</p>
        ${conflict}
      </div>
      <div class="side">${stampHTML(res, e, changed ? 'flip' : '')}<span class="conf">confidence ${Math.round((e.confidence || 0) * 100)}%</span><span class="meta-status">${esc(r.status)}${r.penalty ? ' · penalty stated' : ''}</span></div>
      ${ask}
      <details class="law"><summary><svg aria-hidden="true"><use href="#i-chev"/></svg> Show the law</summary>
        <blockquote class="q" cite="${esc(r.source_url || '')}">${esc(e.quoted_span)}</blockquote>
        <p class="src"><span>${esc(r.doc_title || e.source_doc_id)}</span>${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">source <svg aria-hidden="true"><use href="#i-ext"/></svg></a>` : ''}<span>retrieved ${esc(r.retrieval_date || '?')}</span><span>chars ${(r.source_char_offset || []).join('–')}</span><span>read by ${esc(r.model || 'model')}</span><a href="/api/rules/${esc(e.rule_id)}" target="_blank" rel="noopener">rule record</a></p>
        <p class="tree">Covers: ${condText(r.coverage_conditions)}${r.precedence && r.precedence.relationship !== 'stacks_with' && r.precedence.relationship !== 'none' ? ` · ${esc(r.precedence.relationship.replace('_', ' '))} ${esc(r.precedence.target_scope)} rules${r.precedence.source_language ? ': “' + esc(r.precedence.source_language) + '”' : ''}` : ''}</p>
        ${ex}${r.penalty ? `<p class="tree">Penalty: ${esc(r.penalty)}</p>` : ''}${ver}
      </details>
    </article>`;
  }

  function askHTML(e, field) {
    const f = FACT_Q[field];
    const target = f.maps || field;
    let input = '';
    if (f.type === 'select') input = `<select name="v"><option value="">choose</option>${f.opts.map((o) => `<option>${o}</option>`).join('')}</select>`;
    else input = `<input name="v" type="${f.type}" placeholder="${esc(f.ph || '')}" required>`;
    return `<div class="ask"><p class="qq"><b>Tell us</b>${esc(f.q)}</p><form data-field="${esc(target)}">${input}<button class="btn sm" type="submit">Re-stamp</button></form><p class="caption">Your answer is used on this screen only and labelled as yours. The scored files keep “unknown” because the records do not hold this fact.</p></div>`;
  }

  function renderNotice(lk) {
    const a = lk.address, js = lk.jurisdiction_stack, f = lk.building_facts;
    const byCat = {};
    lk.results.forEach((e) => { (byCat[e.category] = byCat[e.category] || []).push(e); });
    const cats = state.meta ? Object.keys(state.meta.categories) : Object.keys(byCat);
    const fact = (k, label) => f[k] != null ? `<span><b>${esc(f[k])}</b> ${label}</span>` : `<span class="unk">${label} unknown</span>`;
    const yours = Object.keys(state.facts).length ? `<div class="yours"><span><b>Stated by you</b>${Object.entries(state.facts).map(([k, v]) => `${esc(k)} = ${esc(v)}`).join(', ')}. Not from the records.</span><button class="btn ghost sm" type="button" id="clear-facts">Forget</button></div>` : '';
    const levelLit = (lvl) => lk.results.some((e) => e.level === lvl && e.result === 'applies') ? 'lit' : '';
    let idx = 0;
    const sections = cats.filter((c) => byCat[c]).map((c) => `<section class="cat"><div class="cat-h"><h2>${esc(state.meta ? state.meta.categories[c] : c)}</h2><span class="count">${byCat[c].length} rule${byCat[c].length > 1 ? 's' : ''} posted</span></div>${byCat[c].map((e) => ruleHTML(e, idx++)).join('')}</section>`).join('');
    const none = (lk.no_rule_findings || []);
    const noneHTML = none.length ? `<section class="none-posted"><h2>Nothing posted at this level</h2><ul>${none.map((n) => `<li><b>${esc(state.meta ? state.meta.categories[n.category] : n.category)}</b>: no ${esc(n.level)} rule in the corpus for ${esc(n.jurisdiction)}</li>`).join('')}</ul><p class="caption">A positive finding from the corpus, not a gap: no enacted rule in this category exists at this level in the documents read. Pending and struck measures never count as rules.</p></section>` : '';
    const tl = state.timeline ? timelineHTML(state.timeline.points) : '';
    $('#sheet-body').innerHTML = `
      <header class="notice-head">
        <div>
          <h1>Notice to tenants of ${esc(a.street)}<small>${esc(a.postal_city)}, ${esc(a.state)} ${esc(a.zip)}${a.address_id !== 'adhoc' ? ' · sample ' + esc(a.address_id) : ' · live lookup'}</small></h1>
          <div class="stack">
            <span class="lvl">State</span><span class="val ${levelLit('state')}">${esc(js.state)}</span>
            <span class="lvl">County</span><span class="val ${levelLit('county')}">${esc(js.county || 'unresolved')}</span>
            <span class="lvl">City</span><span class="val ${levelLit('city')}">${esc(js.city || 'unresolved')} <span class="how">· ${esc(js.method.replace(/_/g, ' '))}, confidence ${Math.round((js.confidence || 0) * 100)}%${js.matched_address ? ', matched “' + esc(js.matched_address) + '”' : ''}</span></span>
          </div>
          <p class="facts">${fact('year_built', 'built')}${fact('units', 'units')}${fact('property_type', 'type')}${a.use_code ? `<span>use code <b>${esc(a.use_code)}</b></span>` : ''}${a.source ? `<span class="caption">source: ${esc(a.source)}</span>` : ''}</p>
        </div>
        <div class="stamp-big" aria-label="As of ${esc(lk.as_of_date)}"><span class="l">As of</span><span class="d">${esc(lk.as_of_date)}</span></div>
      </header>
      ${tl}
      ${yours}
      ${sections || `<section class="cat"><div class="cat-h"><h2>No rules reach this address</h2></div><p class="caption" style="padding-bottom:18px">Either the corpus holds no rule for this jurisdiction, or every rule's coverage conditions definitively fail for this building.</p></section>`}
      ${noneHTML}
      <div class="tear"><a href="/api/outputs/rules.json" download>rules.json<small>every rule, with its quote</small></a><a href="/api/outputs/lookups.json" download>lookups.json<small>every sample address, as of today</small></a><a href="/api/outputs/changes.json" download>changes.json<small>T1–T6, affected addresses</small></a></div>
      <p class="sheet-foot"><span>Posted by Homerule. The model read the law; plain code decided every stamp.</span><span>Not legal advice.</span></p>`;
    state.prev = {}; lk.results.forEach((e) => { state.prev[e.rule_id] = e.result.replace(/ /g, '_'); });
    wireNotice();
    if (!$('#sheet-body').dataset.scrolled) { $('#sheet-body').dataset.scrolled = '1'; }
  }

  function timelineHTML(points) {
    const start = new Date('2024-01-01T00:00:00'), end = new Date('2028-12-31T00:00:00');
    const span = end - start;
    const pct = (d) => Math.max(0, Math.min(100, ((new Date(d + 'T00:00:00') - start) / span) * 100));
    const ticks = points.filter((p) => p.date > '2024-01-01' && p.date < '2028-01-01').map((p) => `<span class="tick ${p.date > state.asOf ? 'red' : ''}" style="left:${pct(p.date).toFixed(2)}%" data-l="${esc(p.date.slice(0, 7))}"></span>`).join('');
    const val = Math.round(((new Date(state.asOf + 'T00:00:00') - start) / span) * 1000);
    return `<div class="timeline"><span class="lbl">Time machine</span><div class="track"><div class="ticks">${ticks}</div><input id="tl" type="range" min="0" max="1000" value="${val}" aria-label="As-of date"><div class="ends"><span>2024</span><span>2026</span><span>2028</span></div></div><div class="lang" role="group" aria-label="Language"><button type="button" data-lang="en" aria-pressed="${state.lang === 'en'}">EN</button><button type="button" data-lang="es" aria-pressed="${state.lang === 'es'}">ES</button></div></div>`;
  }

  function wireNotice() {
    const tl = $('#tl');
    if (tl) {
      let t = null;
      tl.addEventListener('input', () => {
        const start = new Date('2024-01-01T00:00:00'), end = new Date('2028-12-31T00:00:00');
        const d = new Date(start.getTime() + (end - start) * (tl.value / 1000));
        state.asOf = d.toISOString().slice(0, 10); asof.value = state.asOf;
        $('.stamp-big .d').textContent = state.asOf;
        clearTimeout(t); t = setTimeout(rerun, 140);
      });
    }
    $$('.timeline .lang button').forEach((b) => b.addEventListener('click', () => { state.lang = b.dataset.lang; document.body.dataset.lang = state.lang; $$('.timeline .lang button').forEach((x) => x.setAttribute('aria-pressed', x === b)); $$('.stamp').forEach((s) => { const res = Array.from(s.classList).find((c) => RESULT_LABEL[c]); if (res) s.firstChild.textContent = state.lang === 'es' ? RESULT_ES[res] : RESULT_LABEL[res]; }); }));
    $$('.ask form').forEach((f) => f.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = f.elements.v.value; if (!v) return;
      state.facts[f.dataset.field] = f.elements.v.type === 'number' ? Number(v) : v;
      rerun();
    }));
    const cf = $('#clear-facts'); if (cf) cf.addEventListener('click', () => { state.facts = {}; rerun(); });
  }

  // ---------------------------------------------------------------- free address
  $('#free-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const fd = new FormData(e.target); const p = {};
    for (const [k, v] of fd.entries()) if (String(v).trim()) p[k] = String(v).trim();
    state.facts = {}; state.prev = {};
    runFree(p);
  });

  // ---------------------------------------------------------------- changes
  let changesLoaded = false;
  async function loadChanges(force) {
    if (changesLoaded && !force) return;
    const board = $('#changes-board');
    board.innerHTML = `<div class="skel"><div></div><div></div><div></div></div>`;
    try {
      const recs = await api('/api/changes');
      changesLoaded = true;
      if (!recs.length) { board.innerHTML = `<p class="caption">No change tests have been run yet (make changes).</p>`; return; }
      board.innerHTML = recs.map((r) => {
        const empty = !r.rule_ids.length;
        const ba = (qq, lbl) => `<div><span class="lbl">${lbl}</span><span class="dt">${esc(qq.as_of_date)}</span><span class="st ${esc(qq.status)}">${esc(qq.status.replace(/_/g, ' '))}</span><span class="n">${qq.affected_addresses.length} address${qq.affected_addresses.length === 1 ? '' : 'es'} reached</span></div>`;
        return `<article class="test ${empty ? 'empty' : ''}"><span class="tid">${esc(r.test_id)}</span><h2>${esc(r.description)}</h2>
          <p class="rules">${r.rule_ids.length ? r.rule_ids.map((id) => `<span>${esc(id)}</span>`).join('') : '<span>No rule in rules.json matched this test.</span>'}</p>
          <div class="ba">${ba(r.query_before, 'Before')}${ba(r.query_after, 'After')}</div>
          <p class="aff">${r.affected_addresses.length} affected <small>${empty || !r.affected_addresses.length ? 'empty set' : 'sample addresses'}</small></p>
          ${r.conflicts.length ? `<p class="cf">${r.conflicts.map((c) => `<span>Conflict with ${esc(c.with_rule_id)}: ${esc(c.reason)}</span>`).join('')}</p>` : ''}
          ${r.affected_addresses.length ? `<details><summary>Show addresses</summary><ul data-test="${esc(r.test_id)}"></ul></details>` : ''}
          ${r.notes ? `<p class="notes">${esc(r.notes)}</p>` : ''}
        </article>`;
      }).join('');
      $$('.test details', board).forEach((d) => d.addEventListener('toggle', async () => {
        const ul = $('ul', d); if (!d.open || ul.dataset.done) return;
        const rows = await api(`/api/changes/${ul.dataset.test}/addresses`);
        ul.innerHTML = rows.map((x) => `<li><a href="#/a/${esc(x.address_id)}">${esc(x.label)}</a><span>${esc(x.city || '')}</span></li>`).join('');
        ul.dataset.done = '1';
      }));
    } catch (e) { board.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  }

  // ---------------------------------------------------------------- record
  let recordLoaded = false;
  async function loadRecord(force) {
    if (recordLoaded && !force) return;
    const el = $('#record');
    el.innerHTML = `<div class="skel"><div></div><div></div><div></div></div>`;
    try {
      const [au, meta] = await Promise.all([api('/api/audit'), state.meta ? Promise.resolve(state.meta) : api('/api/meta')]);
      recordLoaded = true;
      const byDoc = {}; au.extractions.forEach((x) => { byDoc[x.doc_id] = x; });
      const docs = meta.documents.map((d) => {
        const x = byDoc[d.doc_id] || {};
        const win = (x.windows || []);
        const keys = win.filter((w) => w.cache_key).map((w) => `<a href="/api/llm-record/${esc(w.cache_key)}" target="_blank" rel="noopener">model output${win.length > 1 ? ' ' + (w.window + 1) : ''}</a>`).join(' ');
        const ver = (x.verification || []).filter((v) => v.cache_key).map((v) => `<a href="/api/llm-record/${esc(v.cache_key)}" target="_blank" rel="noopener">verifier</a>`).join(' ');
        return `<tr><td>${esc(d.doc_id)}</td><td>${esc(d.title)}<br><span class="caption">${esc(d.citation)} · ${esc(d.kind)} · ${esc(d.state)}${d.city ? ' / ' + esc(d.city) : ''}</span></td><td>${d.url && d.url.startsWith('http') ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">source</a>` : esc(d.url || '')}<br><span class="caption">retrieved ${esc(d.retrieval_date)}</span></td><td class="num">${d.status === 'ok' ? (x.rules ? x.rules.length : 0) : '<span class="caption">unreachable</span>'}</td><td>${keys} ${ver}${x.model ? `<br><span class="caption">${esc(x.model)} · ${esc(x.at || '')}</span>` : ''}</td></tr>`;
      }).join('');
      const runs = au.runs.slice().reverse().map((r) => `<tr><td>${esc(r.at)}</td><td>${esc(r.step)}</td><td>${esc(Object.entries(r).filter(([k]) => !['at', 'step'].includes(k)).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · '))}</td></tr>`).join('');
      el.innerHTML = `<section class="rec"><h2>Documents read</h2><p class="caption">Every model call is stored content-addressed in cache/llm with its full prompt and answer. The verifier may correct fields; it can never touch a quote.</p><div class="twrap"><table class="t"><thead><tr><th>Doc</th><th>Title</th><th>Source</th><th>Rules</th><th>Model records</th></tr></thead><tbody>${docs}</tbody></table></div></section>
        <section class="rec"><h2>Pipeline runs</h2><div class="twrap"><table class="t"><thead><tr><th>When (UTC)</th><th>Step</th><th>Details</th></tr></thead><tbody>${runs || '<tr><td colspan="3" class="caption">No runs yet.</td></tr>'}</tbody></table></div></section>`;
    } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  }

  // ---------------------------------------------------------------- add a law
  $('#add-file').addEventListener('change', (e) => { $('#add-file-name').textContent = e.target.files[0] ? e.target.files[0].name : 'Choose a .txt file'; });
  $('#add-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#add-submit'); btn.disabled = true; busy('Reading the document, slicing quotes, verifying, re-evaluating every address');
    const out = $('#add-result'); out.hidden = false; out.innerHTML = `<div class="skel"><div></div><div></div><div></div></div>`;
    try {
      const res = await api('/api/add-doc', { method: 'POST', body: new FormData(e.target) });
      changesLoaded = false; recordLoaded = false; state.meta = null;
      const rules = res.rules.map((r) => `<div class="rule-mini"><div><p class="req">${esc(r.requirement)}</p><p class="strip">${esc(r.source_citation)} · ${esc(r.category)} · effective ${esc(r.effective_date || 'not stated')} · ${esc(r.status)} · confidence ${Math.round(r.confidence * 100)}%</p><blockquote class="q">${esc(r.quoted_span)}</blockquote></div><div>${stampHTML(r.status === 'pending' ? 'pending' : (r.effective_date && r.effective_date > todayISO() ? 'not_yet_effective' : 'applies'), { effective_date: r.effective_date })}</div></div>`).join('');
      const c = res.change;
      out.innerHTML = `<section class="rec"><h2>${esc(res.doc_id)} extracted: ${res.rules.length} rule${res.rules.length === 1 ? '' : 's'}</h2><p class="caption">Quotes are sliced from the uploaded text; the verifier checked each record against its quote.</p>${rules || '<p class="caption">No rule in the six categories was found in this document.</p>'}</section>
        ${c ? `<section class="rec"><h2>Change test ${esc(c.test_id)}</h2><p>${esc(c.description)}</p><p class="caption" style="margin-top:6px">Before ${esc(c.query_before.as_of_date)}: ${esc(c.query_before.status.replace(/_/g, ' '))} · after ${esc(c.query_after.as_of_date)}: ${esc(c.query_after.status.replace(/_/g, ' '))} · <b>${c.affected_addresses.length} affected addresses</b>${c.conflicts.length ? ' · conflicts: ' + esc(c.conflicts.map((x) => x.with_rule_id).join(', ')) : ''}</p><p style="margin-top:10px"><a href="#/changes" class="btn ghost sm">Open the changes board</a></p></section>` : ''}`;
    } catch (err) { out.innerHTML = `<section class="rec"><p class="err">${esc(err.message)}</p></section>`; }
    finally { btn.disabled = false; busy(null); }
  });

  // ---------------------------------------------------------------- boot
  async function boot() {
    try {
      state.meta = await api('/api/meta');
      const cities = Object.entries(state.meta.cities).sort((a, b) => b[1] - a[1]);
      $('#cities').innerHTML = cities.map(([c, n]) => `<button type="button" data-city="${esc(c.split(',')[0])}">${esc(c)}<small>${n}</small></button>`).join('');
      $$('#cities button').forEach((b) => b.addEventListener('click', async () => { const rows = await api(`/api/addresses?city=${encodeURIComponent(b.dataset.city)}&limit=1`); if (rows[0]) location.hash = `#/a/${rows[0].address_id}`; }));
      const h = await api('/api/health');
      $('#foot-meta').textContent = `${h.rules} rules from ${h.documents} documents · ${h.addresses} sample addresses · extraction model ${h.model} · today ${state.meta.today}`;
    } catch (e) { $('#foot-meta').textContent = 'The API is not reachable.'; }
    route();
  }
  boot();
})();
