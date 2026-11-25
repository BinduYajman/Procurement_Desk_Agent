import { useEffect, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts'

const num = v => v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
const SECS = [['proc', 'Decision procedure'], ['cat', 'Categories'], ['sup', 'Suppliers'], ['amd', 'Amendments'], ['prec', 'Precedents']]
const SC = { APPROVED: 'ok', PROBATION: 'wr', BLACKLISTED: 'bd' }
const Chip = ({ c = 'mu', children }) => <span className={'chip c-' + c}>{children}</span>

export default function Playbook({ active }) {
  const [p, setP] = useState(null), [sec, setSec] = useState('proc'), [cat, setCat] = useState(null), [q, setQ] = useState(''), [st, setSt] = useState('ALL')
  useEffect(() => { if (active && !p) fetch('/api/playbook').then(r => r.json()).then(j => { setP(j); setCat(j.categories[0]?.key) }) }, [active])
  if (!p) return <div className="page"><div className="pn err">Loading the playbook…</div></div>
  const c = p.categories.find(x => x.key === cat), errs = p.issues.filter(i => i.severity === 'error').length
  const sups = p.suppliers.filter(s => (st === 'ALL' || s.status.startsWith(st)) && s.name.toLowerCase().includes(q.toLowerCase()))
  return <div className="page">
    <div className="strip"><span>Engine <b>v{p.version}</b></span><span>Playbook fingerprint <b>{p.fingerprint}</b></span><span><b>{p.categories.length}</b> categories</span><span><b>{p.suppliers.length}</b> suppliers</span><span><b>{p.amendments.length}</b> amendments</span>
      <span>Validation: <b style={{ color: errs ? 'var(--bd)' : 'var(--ok)' }}>{errs ? errs + ' error(s)' : 'passes'}</b></span></div>
    <div className="sub">{SECS.map(([k, l]) => <button key={k} className={sec === k ? 'on' : ''} onClick={() => setSec(k)}>{l}</button>)}</div>

    {sec === 'proc' && <div className="g2">
      <section className="pn"><h3>Rules, first match wins</h3><div className="in">{p.rules.map(r => <div key={r.id} className="row"><span className="k">{r.id}</span><span className="t">{r.title}<span className="d">{r.source}</span></span></div>)}</div></section>
      <section className="pn"><h3>Prompt-injection lexicon</h3><div className="in">{p.injection.map(r => <div key={r.id} className="row"><span className="k">{r.id}</span><span className="t">{r.title}</span></div>)}
        <div className="meta" style={{ marginTop: 8 }}>Banned terms: automatic renewal, advance above 30%, unlimited liability for Acme, exclusivity.</div></div></section>
      <section className="pn"><h3>Exchange rates (INR)</h3><div className="in"><table><tbody>{Object.entries(p.fx).map(([k, v]) => <tr key={k}><td>{k}</td><td className="n">{num(v)}</td></tr>)}</tbody></table></div></section>
      <section className="pn"><h3>Playbook checks</h3><div className="in">{p.issues.length ? p.issues.map((i, k) => <div key={k} className="row"><Chip c={i.severity === 'error' ? 'bd' : 'wr'}>{i.severity}</Chip><span className="t">{i.message}</span></div>) : <div className="meta">No errors or warnings: every category, amendment and contract is consistent.</div>}</div></section></div>}

    {sec === 'cat' && <div className="g2">
      <section className="pn"><h3>Categories</h3><div className="scroll"><table><thead><tr><th>Category</th><th className="n">Target</th><th className="n">Walk-away</th><th className="n">Rounds</th><th className="n">Exponent</th><th className="n">Limit</th><th className="n">GST</th></tr></thead>
        <tbody>{p.categories.map(x => <tr key={x.key} onClick={() => setCat(x.key)} style={{ cursor: 'pointer', background: x.key === cat ? 'var(--bg)' : '' }}><td><b>{x.name}</b><div className="meta" style={{ fontSize: 12 }}>{x.unit}</div></td>
          <td className="n">{num(x.target)}</td><td className="n">{num(x.walk)}</td><td className="n">{x.rounds}</td><td className="n">{x.beta}</td><td className="n">{num(x.limit)}</td><td className="n">{x.gst}%</td></tr>)}</tbody></table></div></section>
      {c && <section className="pn"><h3>{c.name}: concession schedule</h3><div className="in">
        <ResponsiveContainer width="100%" height={250}><LineChart data={c.levels.map((v, i) => ({ r: 'Round ' + (i + 1), L: v }))} margin={{ left: 0, right: 16 }}>
          <CartesianGrid stroke="var(--ln)" vertical={false} /><XAxis dataKey="r" tick={{ fontSize: 11, fill: 'var(--mu)' }} /><YAxis tick={{ fontSize: 11, fill: 'var(--mu)' }} domain={['auto', 'auto']} tickFormatter={v => Math.round(v).toLocaleString('en-IN')} width={60} />
          <Tooltip formatter={v => [num(v), 'L(r)']} contentStyle={{ background: 'var(--pn)', border: '1px solid var(--ln)', fontSize: 12 }} />
          <ReferenceLine y={c.walk} stroke="var(--bd)" strokeDasharray="4 3" label={{ value: 'walk-away', fill: 'var(--bd)', fontSize: 11, position: 'insideTopLeft' }} />
          <Line dataKey="L" stroke="var(--in)" strokeWidth={2} isAnimationActive={false} dot={{ r: 4, fill: "var(--in)" }} /></LineChart></ResponsiveContainer>
        <div className="meta">L(r) = T + (W − T)·((r−1)/(R−1))<sup>β</sup>. Round 1 gives the target ({num(c.target)}); the final round gives the walk-away price ({num(c.walk)}). Amendments and supplier caps can change these per thread.</div></div></section>}</div>}

    {sec === 'sup' && <section className="pn"><h3>Suppliers <span className="chips" style={{ margin: 0 }}>
      <input placeholder="Search supplier" value={q} onChange={e => setQ(e.target.value)} />
      <select value={st} onChange={e => setSt(e.target.value)}><option>ALL</option><option>APPROVED</option><option>PROBATION</option><option>BLACKLISTED</option></select></span></h3>
      <div className="scroll"><table><thead><tr><th>Supplier</th><th>Status</th><th>Contract price caps</th><th>Contract FX</th></tr></thead>
        <tbody>{sups.map(s => <tr key={s.name}><td>{s.name}</td><td><Chip c={SC[s.status.split(' ')[0]] || 'mu'}>{s.status}</Chip></td>
          <td>{Object.entries(s.caps).map(([k, v]) => <div key={k}>{k}: ₹{num(v)}</div>)}</td><td>{Object.entries(s.fx).map(([k, v]) => <div key={k}>{k} = ₹{num(v)}</div>)}</td></tr>)}</tbody></table></div></section>}

    {sec === 'amd' && <section className="pn"><h3>Dated amendments (later effective date wins)</h3><div className="scroll"><table><thead><tr><th>Effective</th><th>Amendment</th><th>Category</th><th>Field</th><th className="n">New value</th></tr></thead>
      <tbody>{p.amendments.map(a => <tr key={a.source}><td className="n" style={{ textAlign: 'left' }}>{a.effective}</td><td>{a.source}</td><td>{a.category}</td><td>{a.field.replace(/_/g, ' ')}</td><td className="n">₹{num(a.value)}</td></tr>)}</tbody></table></div></section>}

    {sec === 'prec' && <div>{p.precedents.map(g => g.items.map((t, i) => <details key={g.key + i} className="pn" style={{ marginBottom: 10 }} open={false}><summary style={{ padding: 12, color: 'var(--ink)' }}>{t.split('\n')[0].replace(/^#\s*/, '')} <span className="meta">({g.key})</span></summary><pre className="pre">{t}</pre></details>))}</div>}
  </div>
}
