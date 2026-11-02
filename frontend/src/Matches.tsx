import { useEffect, useState } from 'react'
import { ArrowLeft, External, Star, Tag } from './Icons'
import { api, money, type Card, type Look } from './api'

export default function Matches({ sid, onBack }: { sid: string; onBack: () => void }) {
  const [tab, setTab] = useState<'liked' | 'tried'>('liked')
  const [items, setItems] = useState<Card[] | null>(null)
  const [looks, setLooks] = useState<Look[] | null>(null)

  useEffect(() => {
    api.matches(sid).then(setItems).catch(() => setItems([]))
    api.tryons(sid).then(setLooks).catch(() => setLooks([]))
  }, [sid])

  const count = tab === 'liked' ? items?.length : looks?.length
  return (
    <>
      <div className="page-head">
        <button className="icon-btn" onClick={onBack} aria-label="Back"><ArrowLeft size={18} /></button>
        <h2>Matches</h2>
        {count != null && <span className="muted" style={{ fontSize: 13 }}>{count} {tab === 'liked' ? 'saved' : 'tried on'}</span>}
      </div>
      <div className="seg">
        <button className={tab === 'liked' ? 'on' : ''} onClick={() => setTab('liked')}>Liked</button>
        <button className={tab === 'tried' ? 'on' : ''} onClick={() => setTab('tried')}>Tried on you{looks?.length ? ` · ${looks.length}` : ''}</button>
      </div>
      <div className="list">
        {tab === 'liked' && <Liked items={items} />}
        {tab === 'tried' && <Tried looks={looks} />}
      </div>
    </>
  )
}

function Liked({ items }: { items: Card[] | null }) {
  if (items === null) return <div className="center" style={{ paddingTop: 80 }}><div className="spinner" /></div>
  if (items.length === 0) return (
    <div className="empty">
      <p style={{ fontWeight: 600, color: 'var(--ink)' }}>No matches yet</p>
      <p>Swipe right on pieces you love and they'll appear here.</p>
    </div>
  )
  return <>{items.map(c => (
    <div key={c.id} className="row">
      <div className="ph"><img src={c.tryon ?? c.image} alt={c.title} loading="lazy" className={c.tryon ? 'on-you' : undefined} /></div>
      <div className="info">
        {c.action === 'crush' && <span className="tag-crush"><Star size={11} filled />Loved it on me</span>}
        {c.action === 'pricey' && <span className="tag-pricey"><Tag size={11} />Loved, too pricey</span>}
        <div className="title">{c.title}</div>
        <div className="line"><b>{money(c.price)}</b><span>{c.match}% match</span></div>
        {c.verdict && <div className="flag g" style={{ color: 'var(--ink-2)' }}>{c.verdict.reason}</div>}
        {!c.verdict && c.green[0] && <div className="flag g">{c.green[0]}</div>}
        {c.red[0] && <div className="flag r">{c.red[0]}</div>}
        <a className="link" href={c.link} target="_blank" rel="noopener noreferrer">View product <External size={13} /></a>
      </div>
    </div>
  ))}</>
}

// Every dress you tried on with a super like, newest first, with Cupid's verdict.
function Tried({ looks }: { looks: Look[] | null }) {
  if (looks === null) return <div className="center" style={{ paddingTop: 80 }}><div className="spinner" /></div>
  if (looks.length === 0) return (
    <div className="empty">
      <p style={{ fontWeight: 600, color: 'var(--ink)' }}>Nothing tried on yet</p>
      <p>Super like a dress to try it on, and every look you try lands here.</p>
    </div>
  )
  return (
    <div className="looks dates-grid">
      {looks.map(l => {
        const v = l.verdict
        return (
          <div key={l.id} className={`date-card ${v ? (v.verdict === 'match' ? 'kept' : 'passed') : ''}`}>
            <div className="ph">
              <img src={l.tryon} alt={l.title} loading="lazy" />
            </div>
            <div className="res">
              {v && <><b>{v.verdict === 'match' ? '✓ Works on you' : '✕ Not on you'}</b>{v.reason}</>}
              <a href={l.link} target="_blank" rel="noopener noreferrer">{money(l.price)} · View <External size={12} /></a>
            </div>
          </div>
        )
      })}
    </div>
  )
}
