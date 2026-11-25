import { useEffect, useRef, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, ReferenceLine, Tooltip } from 'recharts'

const sleep = ms => new Promise(r => setTimeout(r, ms))
const Chip = ({ c = 'mu', children }) => <span className={'chip c-' + c}>{children}</span>
const CAP = {
  parse: 'Cleaning the text and splitting earlier vs latest messages',
  security: 'Scanning every line of the whole thread for instructions aimed at an AI',
  terms: 'Checking the latest message for banned contract terms',
  extract: 'Finding the supplier’s current offer (injected lines may not supply a price)',
  normalize: 'Converting the quote to INR, excluding GST, per unit, with exact fractions',
  values: 'Applying the category page, dated amendments, then the supplier contract cap',
  schedule: 'Computing the concession level for this round',
  rules: 'Walking the decision procedure in playbook order',
}
const WHY = r => ({
  ACCEPT: 'Price is within the concession level and the deal value is within the approval limit.',
  COUNTER: 'Price is above L(r) on a non-final round: counter at L(r), rounded half-up.',
  REJECT: r === 'BLACKLISTED_SUPPLIER' ? 'Supplier is blacklisted.' : 'Price is above the walk-away level on the final round.',
  ESCALATE: 'A human must review this thread.',
})

const R = {
  parse: d => ({ chip: <Chip c="ok">done</Chip>, body: <>
    <div className="chips"><Chip>{d.earlier.length} earlier message(s)</Chip><Chip c="ok">latest: {d.latest}</Chip></div>
    <div className="meta">Only the <b>latest</b> message can carry the offer and banned terms; the <b>whole thread</b> is screened for injection.</div></> }),
  security: d => { const n = d.rules.filter(r => r.hits.length).length
    return { chip: n ? <Chip c="bd">{n} injection rule(s) hit</Chip> : <Chip c="ok">clean</Chip>, body: d.rules.map(r =>
      <div key={r.id} className={'row ' + (r.hits.length ? 'hit' : '')}><span className="k">{r.id}</span>
        <span className="t">{r.title}{r.hits.map((h, i) => <span key={i} className="d">⚠ “{h}”</span>)}</span>
        <Chip c={r.hits.length ? 'bd' : 'ok'}>{r.hits.length ? 'MATCH' : 'clear'}</Chip></div>) } },
  terms: d => ({ chip: d.hits.length ? <Chip c="bd">banned term</Chip> : <Chip c="ok">clean</Chip>,
    body: d.hits.length ? d.hits.map((h, i) => <div key={i} className="row hitw"><span className="k">{h.id}</span>
      <span className="t">{h.title}<span className="d">“{h.evidence}”</span></span><Chip c="bd">BANNED</Chip></div>)
      : <div className="meta">No automatic renewal, advance above 30%, unlimited liability or exclusivity found.</div> }),
  extract: d => ({ chip: <Chip c={d.offers.length ? 'ok' : 'wr'}>{d.offers.length} offer line(s)</Chip>, body: <>
    {d.offers.length ? d.offers.map((o, i) => <div key={i}><div className="q">{o.line}</div>
      <div className="chips">{o.amounts.map((a, j) => <Chip key={j} c="ok">{a.raw || a.cur + ' ' + a.amt}</Chip>)}{o.conds.map((c, j) => <Chip key={'c' + j} c="wr">{c.k} = {c.v}</Chip>)}</div></div>)
      : <div className="meta">No current-offer line found.</div>}
    {d.previous.length > 0 && <div className="meta">Earlier supplier quote(s), used only for “% off previous quote”: {d.previous.map(p => p.line).join(' | ')}</div>}
    {d.excluded.map((x, i) => <div key={i} className="meta" style={{ color: 'var(--bd)' }}>Excluded as injected text: {x}</div>)}
    <div className="chips">{d.flags.map(f => <Chip key={f} c="wr">{f}</Chip>)}</div></> }),
  normalize: d => ({ chip: d.price ? <Chip c="ok">p = {d.price}</Chip> : <Chip c="bd">no usable price</Chip>, body: <>
    {d.attempts.map((a, i) => <div key={i}>{a.steps.map((s, j) => <div key={j} className="stp"><span>{s.d}</span><span>{s.v ?? ''}</span></div>)}
      {a.problem && <div className="meta" style={{ color: 'var(--bd)' }}>Unusable: {a.problem}</div>}</div>)}
    {d.price && <div className="big">p = ₹{d.price} <small className="meta" style={{ fontSize: 13 }}>{d.unit}</small></div>}</> }),
  values: d => ({ chip: <Chip>{d.prov.length > 1 ? 'amended' : 'category page'}</Chip>, body: <>
    <div className="kv"><div><small>Target T</small><b>{d.target}</b></div><div><small>Walk-away W</small><b>{d.walk}</b></div><div><small>Approval limit A</small><b>{d.limit}</b></div></div>
    {d.prov.map((p, i) => <div key={i} className="stp"><span>{p}</span><span /></div>)}
    <div className="chips"><Chip c={/BLACK/.test(d.status) ? 'bd' : /PROB/.test(d.status) ? 'wr' : 'ok'}>supplier: {d.status}{d.known ? '' : ' (unknown)'}</Chip>
      <Chip>{d.rounds} rounds · β={d.beta}</Chip><Chip>as of {d.date}</Chip></div></> }),
  schedule: d => { const lv = d.level && parseFloat(d.level.replace(/,/g, '')), ok = d.p != null && lv != null && d.p <= lv + 1e-9
    const col = ok ? 'var(--ok)' : 'var(--bd)'
    return { chip: <Chip c={d.reached ? 'in' : 'wr'}>{d.reached ? `L(${d.round}) = ${d.level}` : 'not needed'}</Chip>, body: (
      <div className="sched"><div>
        <ResponsiveContainer width="100%" height={118}>
          <LineChart data={d.levels.map((v, i) => ({ r: 'R' + (i + 1), L: v }))} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <XAxis dataKey="r" tick={{ fontSize: 11, fill: 'var(--mu)' }} tickLine={false} />
            <YAxis width={46} tick={{ fontSize: 10, fill: 'var(--mu)' }} tickLine={false} domain={[m => Math.min(m, d.p ?? m) * 0.99, m => Math.max(m, d.p ?? m) * 1.01]} tickFormatter={v => Math.round(v).toLocaleString('en-IN')} />
            <Tooltip formatter={v => [Math.round(v * 100) / 100, 'L(r)']} contentStyle={{ background: 'var(--pn)', border: '1px solid var(--ln)', fontSize: 12 }} />
            <Line dataKey="L" stroke="var(--in)" strokeWidth={2} isAnimationActive={false}
              dot={({ cx, cy, index }) => <circle key={index} cx={cx} cy={cy} r={index === d.round - 1 ? 5 : 3} fill={index === d.round - 1 ? 'var(--in)' : 'var(--pn)'} stroke="var(--in)" strokeWidth={2} />} />
            {d.p != null && <ReferenceLine y={d.p} stroke={col} strokeDasharray="4 3" />}
          </LineChart></ResponsiveContainer></div>
        <div>{d.reached
          ? <div className="meta">Round {d.round}: Acme may accept up to <b>L = {d.level}</b>{d.probation ? ' (probation: no concessions, L = target)' : ''}. Supplier price p = <b style={{ color: col }}>{d.p_txt}</b>, which is <b style={{ color: col }}>{ok ? 'within' : 'above'}</b> the level (dashed line).</div>
          : <div className="meta">A rule before the price check already decided, so the schedule was not needed.</div>}</div></div>) } },
  rules: d => ({ chip: <Chip c="ok">stopped at {d.fired}</Chip>, body: d.rows.map(r =>
    <div key={r.id} className={'row ' + r.state}><span className="k">{r.id}</span><span className="t">{r.title}<span className="d">{r.detail} · <i>{r.source}</i></span></span>
      <Chip c={r.state === 'fired' ? 'ok' : 'mu'}>{r.state === 'fired' ? 'FIRED' : r.state === 'passed' ? 'passed' : 'not reached'}</Chip></div>) }),
  error: d => ({ chip: <Chip c="wr">fail-safe</Chip>, body: <div className="err">{d.error}<div className="meta">The engine fails safe: the thread is escalated to a human.</div></div> }),
}

function Verdict({ run, phase }) {
  if (phase === 'done' && run) {
    const [a] = run.label.split(':'), tk = run.ticket
    return <section className={'verd ' + a}>
      <div className="vk">Verdict · decided by rule {run.fired}</div><div className="va">{a}</div>
      <div><div className="vl">{run.label}</div><div className="vw">{WHY(run.reason)[a]}</div></div>
      <div className="vx">{tk && <div className="kv"><div><small>Send to</small><b>{tk.suggested_owner}</b></div><div><small>Deal value</small><b>{tk.deal_value || 'n/a'}</b></div><div><small>Reason</small><b style={{ fontSize: 12 }}>{tk.reason}</b></div></div>}
        <div className="chips">{run.verified ? <Chip c="ok">replayed steps = official pipeline.decide()</Chip> : <Chip c="bd">MISMATCH with official pipeline</Chip>}
          {run.expected && (run.expected === run.label ? <Chip c="ok">matches submitted label (scored 1.0)</Chip> : <Chip c="bd">differs from submitted: {run.expected}</Chip>)}
          {run.flags.map(f => <Chip key={f} c="wr">{f}</Chip>)}</div></div></section>
  }
  const w = phase === 'work'
  return <section className={'verd ' + (w ? 'work' : 'pend')}><div className="vk">Verdict</div><div className="va">{w ? 'Agent is working' : 'Awaiting run'}</div>
    <div><div className="vw">{w ? 'Following the playbook step by step…' : run ? 'Press “Run agent” to start.' : 'Pick a thread, then run the agent.'}</div></div></section>
}

export default function Run({ meta }) {
  const [q, setQ] = useState(''), [sel, setSel] = useState(null), [open, setOpen] = useState(true)
  const [run, setRun] = useState(null), [phase, setPhase] = useState('idle'), [prog, setProg] = useState(0), [cur, setCur] = useState(-1)
  const [log, setLog] = useState([]), [mode, setMode] = useState('auto'), [spd, setSpd] = useState(900), [err, setErr] = useState('')
  const [f, setF] = useState({ supplier: '', category: meta.categories[0] || '', quantity: 10, round: 1, date: '2026-10-01', msg: '' })
  const tok = useRef(0), step = useRef(null), logEl = useRef(null), tl = useRef(null)
  const add = (t, c = '') => setLog(l => [...l, { t, c }])
  useEffect(() => { logEl.current && (logEl.current.scrollTop = 1e9) }, [log])
  useEffect(() => { tl.current?.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [prog, cur])

  async function load(body, id) {
    tok.current++; step.current = null; setErr(''); setSel(id); setPhase('idle'); setProg(0); setCur(-1)
    const r = await fetch('/api/run', { method: 'POST', body: JSON.stringify(body) }), j = await r.json()
    if (!r.ok) { setErr(j.error); setRun(null); return }
    setRun(j); setLog([{ t: 'thread loaded: ' + j.thread.id + '. Press “Run agent”.', c: 's' }])
  }
  async function play() {
    const my = ++tok.current, manual = mode === 'step'
    setPhase('work'); setProg(0); setCur(-1); setLog([])
    for (let i = 0; i < run.stages.length; i++) {
      const s = run.stages[i]; setCur(i); add('▸ ' + s.title, 's')
      if (manual) await new Promise(r => { step.current = r }); else await sleep(spd * 0.7)
      if (my !== tok.current) return
      setProg(i + 1); setCur(-1); s.log.forEach(x => add('  ' + x, /FIRED/.test(x) ? 'g' : ''))
      if (!manual) await sleep(spd * 0.5)
      if (my !== tok.current) return
    }
    setPhase('done'); add('✔ FINAL  ' + run.label, 'g'); window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const seen = new Set((run?.stages || []).slice(0, prog).map(s => s.id))
  const shown = run ? run.stages.slice(0, cur >= 0 ? cur + 1 : prog) : []
  const list = meta.threads.filter(t => (t.id + t.supplier + t.category + (t.label || '')).toLowerCase().includes(q.toLowerCase())).slice(0, 150)

  return (
    <div className={'app' + (open ? '' : ' col')}>
      <aside className={'pn side' + (open ? '' : ' cl')}>
        <h3>{open && <span>Supplier threads</span>}<button className="ic" title={open ? 'Collapse' : 'Expand'} onClick={() => setOpen(!open)}>{open ? '«' : '»'}</button></h3>
        {open && <>
          <input className="s" placeholder="Search id, supplier, category or label" value={q} onChange={e => setQ(e.target.value)} />
          <div id="list">{list.map(t => <div key={t.id} className={'th' + (sel === t.id ? ' on' : '')} onClick={() => load({ id: t.id }, t.id)}>
            <b>{t.id}</b> · {t.supplier}<small>{t.category}{t.label ? ' · ' + t.label.replace(/:$/, '') : ''}</small></div>)}</div>
          <details><summary>Run your own thread</summary>
            <label>Supplier</label><input list="sl" value={f.supplier} onChange={e => setF({ ...f, supplier: e.target.value })} />
            <datalist id="sl">{meta.suppliers.map(s => <option key={s}>{s}</option>)}</datalist>
            <label>Category</label><select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{meta.categories.map(c => <option key={c}>{c}</option>)}</select>
            <label>Quantity</label><input type="number" value={f.quantity} onChange={e => setF({ ...f, quantity: e.target.value })} />
            <label>Round</label><input type="number" value={f.round} onChange={e => setF({ ...f, round: e.target.value })} />
            <label>Date</label><input type="date" value={f.date} onChange={e => setF({ ...f, date: e.target.value })} />
            <label>Supplier message</label><textarea rows={6} value={f.msg} onChange={e => setF({ ...f, msg: e.target.value })} placeholder={'[Latest message — Supplier, 2026-10-01]\nWe can do INR 70,000 per unit.'} />
            <button className="pr" style={{ marginTop: 8 }} onClick={() => load({ thread_id: 'CUSTOM', date: f.date, supplier: f.supplier, category: f.category, quantity: f.quantity, round: f.round, our_last_counter: '', supplier_message: f.msg }, null)}>Run this thread</button>
          </details></>}
      </aside>

      <div className="sticky">
        <section className="pn"><h3>Supplier message</h3><div className="msg">
          {run ? run.lines.map((l, i) => {
            const cls = [l.hdr && 'hdr', l.sec === 'earlier' && 'earlier', seen.has('security') && l.inj.length && 'inj', seen.has('terms') && l.ban.length && 'ban', seen.has('extract') && l.offer && 'offer', seen.has('extract') && l.prev && !l.offer && 'prev'].filter(Boolean).join(' ')
            return <div key={i} className={'ln ' + cls}>{l.text || ' '}
              {seen.has('security') && l.inj.length > 0 && <span className="tag" style={{ color: 'var(--bd)' }}>{l.inj.join(' ')}</span>}
              {seen.has('terms') && l.ban.length > 0 && <span className="tag" style={{ color: 'var(--wr)' }}>{l.ban.join(' ')}</span>}
              {seen.has('extract') && l.offer && <span className="tag" style={{ color: 'var(--ok)' }}>offer</span>}
              {seen.has('extract') && l.prev && !l.offer && <span className="tag" style={{ color: 'var(--in)' }}>earlier quote</span>}</div>
          }) : <div className="meta" style={{ padding: 12 }}>Pick a thread to begin.</div>}</div></section>
        <section className="pn"><h3>Agent log</h3><div className="log" ref={logEl}>{log.map((l, i) => <div key={i} className={l.c}>{l.t}</div>)}</div></section>
      </div>

      <main>
        <Verdict run={run} phase={phase} />
        <div className="bar">
          <button className="pr" disabled={!run || phase === 'work'} onClick={play}>{phase === 'done' ? '↻ Replay' : '▶ Run agent'}</button>
          <button disabled={phase !== 'work' || mode !== 'step'} onClick={() => step.current && step.current()}>Step ⏭</button>
          <select value={mode} onChange={e => setMode(e.target.value)}><option value="auto">Auto-play</option><option value="step">Manual (click Step)</option></select>
          <select value={spd} onChange={e => setSpd(+e.target.value)}><option value={1600}>Slow</option><option value={900}>Normal</option><option value={250}>Fast</option></select>
          <span className="grow" />{run && <span className="meta">{run.thread.id} · {run.thread.supplier} · {run.thread.category} · qty {run.thread.quantity} · round {run.thread.round} · {run.thread.date}</span>}
        </div>
        {err && <div className="pn err" style={{ color: 'var(--bd)' }}>{err}</div>}
        <div ref={tl}>{shown.map((s, i) => {
          const done = i < prog, out = done ? (R[s.id] || (() => ({})))(s.d) : null
          return <section key={s.id + i} className="card"><div className="ch"><span className="num">{i + 1}</span><b>{s.title}</b>{out?.chip}</div>
            {done ? <div className="cb">{out.body}</div> : <div className="think">{CAP[s.id] || 'Working'}</div>}</section>
        })}</div>
      </main>
    </div>)
}
