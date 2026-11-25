import { useEffect, useState } from 'react'
import { ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from 'recharts'

export const ACT = { ACCEPT: 'var(--ok)', COUNTER: 'var(--in)', REJECT: 'var(--bd)', ESCALATE: 'var(--wr)' }
const tip = { contentStyle: { background: 'var(--pn)', border: '1px solid var(--ln)', fontSize: 12 }, cursor: { fill: 'var(--bg)' } }
const tick = { fontSize: 11, fill: 'var(--mu)' }
const inr = n => n >= 1e7 ? (n / 1e7).toFixed(2) + ' Cr' : n >= 1e5 ? (n / 1e5).toFixed(2) + ' L' : Math.round(n).toLocaleString('en-IN')
const labelColor = n => ACT[n.split(':')[0]]
const Panel = ({ t, children }) => <section className="pn"><h3>{t}</h3><div className="in">{children}</div></section>
const Stack = ({ data, h = 280 }) => <ResponsiveContainer width="100%" height={h}><BarChart data={data} margin={{ left: -10 }}>
  <CartesianGrid stroke="var(--ln)" vertical={false} /><XAxis dataKey="name" tick={tick} interval={0} angle={data.length > 6 ? -35 : 0} textAnchor={data.length > 6 ? 'end' : 'middle'} height={data.length > 6 ? 70 : 30} />
  <YAxis tick={tick} /><Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
  {Object.keys(ACT).map(a => <Bar key={a} dataKey={a} stackId="a" fill={ACT[a]} />)}</BarChart></ResponsiveContainer>

export default function Stats({ active }) {
  const [s, setS] = useState(null), [err, setErr] = useState('')
  useEffect(() => { if (active && !s) fetch('/api/stats').then(r => r.json()).then(j => j.error ? setErr(j.error) : setS(j)).catch(e => setErr(String(e))) }, [active])
  if (err) return <div className="pn err">{err}</div>
  if (!s) return <div className="page"><div className="pn err">Running the engine over every thread…</div></div>
  const n = a => s.actions.find(x => x.name === a)?.value || 0, pct = v => (s.total ? (100 * v / s.total).toFixed(1) : 0) + '%'
  return <div className="page">
    <div className="kpis">
      <div className="kpi"><small>Threads decided</small><b>{s.total.toLocaleString()}</b><i>in {s.seconds}s, no model calls</i></div>
      <div className="kpi"><small>Auto-decided</small><b>{pct(n('ACCEPT') + n('COUNTER') + n('REJECT'))}</b><i>accept, counter or reject</i></div>
      <div className="kpi"><small>Escalated to a human</small><b>{pct(n('ESCALATE'))}</b><i>{n('ESCALATE')} review ticket{n('ESCALATE') === 1 ? '' : 's'}</i></div>
      <div className="kpi"><small>Value accepted</small><b>₹{inr(s.spend.ACCEPT || 0)}</b><i>deals within approval limit</i></div>
      <div className="kpi"><small>Match submitted labels</small><b>{s.comparable ? `${s.matched}/${s.comparable}` : 'n/a'}</b><i>vs the scored submission</i></div>
    </div>
    <div className="g2">
      <Panel t="Outcome mix"><ResponsiveContainer width="100%" height={280}><PieChart>
        <Pie data={s.actions} dataKey="value" nameKey="name" innerRadius={62} outerRadius={105} paddingAngle={2} stroke="var(--pn)" label={({ name, value }) => `${name} ${value}`}>
          {s.actions.map(a => <Cell key={a.name} fill={ACT[a.name]} />)}</Pie><Tooltip {...tip} /></PieChart></ResponsiveContainer></Panel>
      <Panel t="Threads per final label"><ResponsiveContainer width="100%" height={280}><BarChart data={s.labels} layout="vertical" margin={{ left: 70 }}>
        <CartesianGrid stroke="var(--ln)" horizontal={false} /><XAxis type="number" tick={tick} /><YAxis type="category" dataKey="name" tick={tick} width={190} />
        <Tooltip {...tip} /><Bar dataKey="value">{s.labels.map(l => <Cell key={l.name} fill={labelColor(l.name)} />)}</Bar></BarChart></ResponsiveContainer></Panel>
    </div>
    <div className="g2">
      <Panel t="Outcome by category"><Stack data={s.by_category} h={320} /></Panel>
      <Panel t="Outcome by negotiation round"><Stack data={s.by_round.map(r => ({ ...r, name: 'Round ' + r.name }))} /></Panel>
    </div>
    <div className="g2">
      <Panel t="Suppliers needing the most attention"><div className="scroll"><table><thead><tr><th>Supplier</th><th className="n">Reject</th><th className="n">Escalate</th><th className="n">Accept</th><th className="n">Counter</th></tr></thead>
        <tbody>{s.suppliers.map(r => <tr key={r.name}><td>{r.name}</td><td className="n" style={{ color: 'var(--bd)' }}>{r.REJECT}</td><td className="n" style={{ color: 'var(--wr)' }}>{r.ESCALATE}</td><td className="n">{r.ACCEPT}</td><td className="n">{r.COUNTER}</td></tr>)}</tbody></table></div></Panel>
      <Panel t="Advisory flags">{Object.keys(s.flags).length ? <table><tbody>{Object.entries(s.flags).map(([k, v]) => <tr key={k}><td>{k}</td><td className="n">{v}</td></tr>)}</tbody></table>
        : <div className="meta">No advisory flags were raised on any thread. Nothing needs a second look.</div>}</Panel>
    </div></div>
}
