import { useEffect, useState } from 'react'
import { ArrowRight, Check } from './Icons'
import { api, type Interview, type Payoff as PayoffData, type Question, type YourType } from './api'

export function typeChips(t: YourType, which: 'loves' | 'avoids') {
  const out: string[] = []
  for (const [key, values] of Object.entries(t[which])) {
    for (const v of values) out.push(label(key, v))
  }
  return out
}

export function label(key: string, v: string) {
  switch (key) {
    case 'tone': return `${v} tones`
    case 'pattern': return v === 'solid' ? 'solid colours' : `${v} prints`
    case 'fit': return `${v} fit`
    case 'vibe': return `${v} vibe`
    case 'group': return `${v} wear`
    case 'category': return `${v}s`
    case 'price': return v === 'under 25' ? 'under $25' : v === '150+' ? '$150+' : `$${v}`
    case 'neck': return v.includes('neck') ? v : `${v} neck`
    case 'length': return ['mini', 'midi', 'maxi'].includes(v) ? `${v} length` : v
    default: return v
  }
}

// Cupid's this or that: two real dresses, alike except for the one thing it can't tell from your swipes.
function Ask({ sid, round, i, q }: { sid: string; round: number; i: number; q: Question }) {
  const [done, setDone] = useState<Question>(q)
  const [busy, setBusy] = useState(false)
  const go = async (a: 'a' | 'b' | 'neither') => {
    setBusy(true)
    try {
      setDone(await api.answer(sid, round, i, a))
    } catch { /* leave it open so they can try again */ } finally {
      setBusy(false)
    }
  }
  const side = (k: 'a' | 'b') => (
    <button className={`side ${done.answer === k ? 'won' : done.answer ? 'lost' : ''}`}
      disabled={busy || !!done.answer} onClick={() => go(k)}>
      <img src={done[k].image} alt={done[k].label} />
      <span>{done[k].label}</span>
    </button>
  )
  return (
    <div className="ask">
      <p className="q">{done.question}</p>
      <div className="sides">{side('a')}<span className="or">or</span>{side('b')}</div>
      {done.reply ? <p className="reply"><Check size={14} />{done.reply}</p>
        : <button className="btn btn-text neither" disabled={busy} onClick={() => go('neither')}>Neither</button>}
    </div>
  )
}

export default function Payoff({ sid, data, onNext, onMatches }: { sid: string; data: PayoffData; onNext: () => void; onMatches: () => void }) {
  const [ask, setAsk] = useState<Interview | null>(null)
  useEffect(() => {
    let stop = false
    const tick = async () => {
      try {
        const a = await api.questions(sid, data.round)
        if (!stop) setAsk(a)
        if (a.status !== 'thinking') return
      } catch { /* try again */ }
      if (!stop) setTimeout(tick, 1500)
    }
    tick()
    return () => { stop = true }
  }, [sid, data.round])

  const loves = typeChips(data.your_type, 'loves')
  const avoids = typeChips(data.your_type, 'avoids')
  const thinking = !ask || ask.status === 'thinking'

  return (
    <div className="overlay sheet">
      <div className="sheet-body">
        <div>
          <p className="eyebrow">Round {data.round} · you liked {data.liked} of {data.swipes}</p>
          <h1 className="flow-title" style={{ marginTop: 8 }}>Here's what<br />I <em>learned</em>.</h1>
        </div>

        {thinking ? <div className="read-skeleton"><i /><i /></div>
          : ask.read ? <p className="read">{ask.read}</p>
          : loves.length > 0 && (
            <div className="type-chips light">
              {loves.map(a => <span key={a} className="yes">{a}</span>)}
              {avoids.map(a => <span key={a} className="no">{a}</span>)}
            </div>
          )}

        {ask && ask.questions.length > 0 && (
          <div>
            <div className="section-title" style={{ marginBottom: 10 }}>
              Cupid has {ask.questions.length === 1 ? 'a question' : `${ask.questions.length} questions`} for you
            </div>
            <div className="asks">
              {ask.questions.map((q, i) => <Ask key={q.a.attribute} sid={sid} round={data.round} i={i} q={q} />)}
            </div>
          </div>
        )}

      </div>
      <div className="flow-foot">
        <button className="btn btn-primary" onClick={onNext}>Continue to round {data.round + 1} <ArrowRight size={16} /></button>
        <button className="btn btn-text" onClick={onMatches}>View matches</button>
      </div>
    </div>
  )
}
