import { useEffect, useState } from 'react'
import Run from './Run.jsx'
import Stats from './Stats.jsx'
import Playbook from './Playbook.jsx'

const TABS = [['run', 'Agent runs'], ['stats', 'Statistics'], ['pb', 'Playbook']]

export default function App() {
  const [tab, setTab] = useState('run'), [meta, setMeta] = useState(null)
  useEffect(() => { fetch('/api/meta').then(r => r.json()).then(setMeta).catch(() => setMeta({ ready: false })) }, [])

  return (
    <>
      <nav className="tabs">
        <span className="brand">
        Procurement <em>Desk</em>
        </span>
        {TABS.map(([k, l]) => (
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </nav>
      {!meta ? (
        <div className="pn err">Connecting...</div>
      ) : !meta.ready ? (
        <div className="pn err">Not ready</div>
      ) : (
        <>
          <div hidden={tab !== 'run'}><Run meta={meta} /></div>
          <div hidden={tab !== 'stats'}><Stats active={tab === 'stats'} /></div>
          <div hidden={tab !== 'pb'}><Playbook active={tab === 'pb'} /></div>
        </>
      )}
    </>
  )
}