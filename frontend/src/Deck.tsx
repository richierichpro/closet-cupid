import { animate, motion, useMotionValue, useTransform } from 'framer-motion'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import FiltersStep, { filterCount } from './FiltersStep'
import { ArrowLeft, External, Heart, Info, Sliders, Sparkle, Star, Tag, Undo, X } from './Icons'
import Logo from './Logo'
import Payoff from './Payoff'
import { api, money, type Action, type Card, type ChosenFilters, type Payoff as PayoffData, type Verdict } from './api'

const ROUND = 12 // matches the engine's ROUND_SIZE
const SWIPE_DISTANCE = 110
const STAMPS: Record<Action, string> = { like: 'LIKE', nope: 'NOPE', crush: 'TRY ON', pricey: 'TOO PRICEY', noton: 'NOPE' }
const LOOKING = { looking: ['dresses'], text: null }

type Toast = { id: number; text: string; kind?: 'thought' | 'match' | 'error' }
const TOAST_MS = 2800
let toastIds = 0

export default function Deck({ sid, onMatches, onRestart }: { sid: string; onMatches: () => void; onRestart: () => void }) {
  const [card, setCard] = useState<Card | null>(null)
  const [swipes, setSwipes] = useState(0)
  const [liked, setLiked] = useState(0)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const [fit, setFit] = useState<Card | null>(null)
  const [payoff, setPayoff] = useState<PayoffData | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [hasMind, setHasMind] = useState(false)
  const lastEvent = useRef(-1)
  const [canRewind, setCanRewind] = useState(false)
  const [looking, setLooking] = useState<{ id: string; label: string }[]>([])
  const [changing, setChanging] = useState(false)
  const [hasPhoto, setHasPhoto] = useState(false)
  const [tryOn, setTryOn] = useState<Card | null>(null)
  const dealtAt = useRef(Date.now())
  const cardRef = useRef<SwipeHandle>(null)
  const pendingNext = useRef<Card | null>(null)
  const lastAction = useRef<Action | null>(null)

  const show = (c: Card | null) => {
    setCard(c)
    dealtAt.current = Date.now()
    if (!c) setDone(true)
  }

  useEffect(() => {
    api.next(sid).then(show).catch(e => (e.message.includes('session') ? onRestart() : setError(e.message)))
    api.session(sid).then(x => { setLooking(x.looking); setSwipes(x.swipes); setHasPhoto(x.has_photo); setHasMind(x.has_mind) }).catch(() => {})
  }, [sid, onRestart])

  // Cupid's thoughts and verdicts arrive a moment after each swipe. The one on screen
  // finishes, then only the newest waiting one plays, so fast swiping never builds a backlog.
  const flash = (t: Omit<Toast, 'id'>) => setToasts(q => [...q.slice(0, 1), { ...t, id: toastIds++ }])
  const toast = toasts[0] ?? null
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToasts(q => q.slice(1)), TOAST_MS)
    return () => clearTimeout(id)
  }, [toast])

  // Cupid's LLM mind works in the background; poll for what it thought and decided.
  useEffect(() => {
    if (!hasMind) return
    let primed = false   // the first poll only catches up, so coming back here doesn't replay old news
    let polling = false
    const id = setInterval(async () => {
      if (polling) return
      polling = true
      try {
        const evs = await api.events(sid, lastEvent.current)
        if (evs.length) lastEvent.current = Math.max(...evs.map(e => e.id))
        // Cupid's thoughts live on the board; only errors get a toast.
        const e = evs.findLast(x => x.type !== 'thought')
        if (primed && e) {
          flash({ kind: e.type, text: e.text })
        }
        primed = true
      } catch { /* the next poll will catch up */ } finally {
        polling = false
      }
    }, 1500)
    return () => clearInterval(id)
  }, [sid, hasMind])

  const onSwiped = useCallback(async (action: Action) => {
    if (!card) return
    // A super like opens the try-on first; the swipe is recorded with its verdict.
    if (action === 'crush' && hasPhoto && !tryOn) {
      setTryOn(card)
      return
    }
    setTryOn(null)
    const dwell = Date.now() - dealtAt.current
    setBusy(true)
    try {
      const r = await api.swipe(sid, card.id, action, dwell)
      setSwipes(r.swipes)
      lastAction.current = action
      if (action !== 'nope') setLiked(n => n + 1)
      setCanRewind(true)
      // After every swipe Cupid says what it concluded: the learning, made visible.
      // With the LLM mind on, its own thoughts arrive as events; otherwise show the engine's.
      if (r.early_refresh) flash({ text: 'Rethinking. Shopping for something different' })
      else if (!hasMind) flash({ kind: 'thought', text: r.thought })
      if (r.its_a_fit) setFit(card)
      if (r.payoff) {
        pendingNext.current = r.next
        setPayoff(r.payoff)
        setCard(null)
      } else {
        show(r.next)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [card, sid, hasPhoto, tryOn, hasMind])

  const rewind = async () => {
    setBusy(true)
    try {
      show(await api.rewind(sid))
      setSwipes(n => Math.max(0, n - 1))
      if (lastAction.current && lastAction.current !== 'nope') setLiked(n => Math.max(0, n - 1))
      lastAction.current = null
      setCanRewind(false)
    } catch {
      flash({ text: 'Nothing to undo' })
    } finally {
      setBusy(false)
    }
  }

  const press = (a: Action) => !busy && card && cardRef.current?.fling(a)

  useEffect(() => {
    const keys: Record<string, Action> = { ArrowLeft: 'nope', ArrowRight: 'like', ArrowUp: 'crush', ArrowDown: 'pricey' }
    const onKey = (e: KeyboardEvent) => {
      if (fit || payoff || changing || tryOn) return
      if (keys[e.key]) { e.preventDefault(); press(keys[e.key]) }
      if (e.key === 'Backspace' && canRewind) rewind()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const inRound = swipes % ROUND

  return (
    <>
      <div className="topbar">
        <Logo />
        <div className="topbar-actions">
          <button className="icon-btn" onClick={() => setChanging(true)} aria-label="Refine filters"><Sliders size={18} /></button>
          <button className="icon-btn" onClick={onMatches} aria-label={`Matches (${liked})`}>
            <Heart size={18} />{liked > 0 && <span className="count">{liked}</span>}
          </button>
        </div>
      </div>
      <div className="context">
        <span className="context-text">{looking.map(l => l.label).join(' + ')}</span>
        <span className="context-count">Round {Math.floor(swipes / ROUND) + 1} · {inRound}/{ROUND}</span>
      </div>
      <div className="progress"><i style={{ width: `${(inRound / ROUND) * 100}%` }} /></div>

      <div className="deck">
        <div className="stack">
          {card && <div className="stack-under" />}
          {card && <SwipeCard key={`${card.id}-${swipes}`} ref={cardRef} card={card} onSwiped={onSwiped} />}
          {!card && !payoff && !done && !error && (
            <div className="skeleton"><div className="ph" /><div className="ln" /><div className="ln short" /></div>
          )}
          {done && (
            <div className="empty">
              <p style={{ fontWeight: 600, color: 'var(--ink)' }}>You've seen everything here</p>
              <p>Try different filters or another category.</p>
              <button className="btn btn-primary" style={{ maxWidth: 260 }} onClick={() => setChanging(true)}>Change search</button>
            </div>
          )}
          {error && <div className="empty"><div className="error">{error}</div></div>}
        </div>
        <div className="actions">
          <button className="act sm undo" onClick={rewind} disabled={!canRewind || busy} aria-label="Undo" title="Undo (Backspace)"><Undo size={18} /></button>
          <button className="act lg nope" onClick={() => press('nope')} disabled={!card || busy} aria-label="Nope" title="Nope (←)"><X size={28} weight={2.4} /></button>
          <button className="act md crush" onClick={() => press('crush')} disabled={!card || busy} aria-label="Super like: try it on" title="Super like: try it on (↑)"><Star size={22} filled /></button>
          <button className="act lg like" onClick={() => press('like')} disabled={!card || busy} aria-label="Like" title="Like (→)"><Heart size={26} filled /></button>
          <button className="act sm pricey" onClick={() => press('pricey')} disabled={!card || busy} aria-label="Love it, too pricey" title="Love it, too pricey (↓)"><Tag size={18} /></button>
        </div>
      </div>

      {toast && (
        <div key={toast.id} className={`toast ${toast.kind ?? ''}`}>
          {toast.kind === 'match' ? <Heart size={13} filled /> : <Sparkle size={13} />}{toast.text}
        </div>
      )}
      {tryOn && <TryOn sid={sid} card={tryOn} onVerdict={a => onSwiped(a)} />}
      {changing && (
        <ChangeLooking sid={sid} onClose={() => setChanging(false)} onChanged={(c, l) => {
          setLooking(l)
          setChanging(false)
          setDone(false)
          show(c)
          flash({ text: 'New filters. Your taste carries over' })
        }} />
      )}
      {fit && !payoff && <FitOverlay card={fit} onClose={() => setFit(null)} />}
      {payoff && (
        <Payoff sid={sid} data={payoff} onMatches={onMatches} onNext={() => {
          setPayoff(null)
          setFit(null)
          show(pendingNext.current)
        }} />
      )}
    </>
  )
}

type SwipeHandle = { fling: (a: Action) => void }

const SwipeCard = forwardRef<SwipeHandle, { card: Card; onSwiped: (a: Action) => void }>(function SwipeCard({ card, onSwiped }, ref) {
  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const rotate = useTransform(x, [-260, 260], [-16, 16])
  const likeO = useTransform(x, [25, SWIPE_DISTANCE], [0, 1])
  const nopeO = useTransform(x, [-SWIPE_DISTANCE, -25], [1, 0])
  const crushO = useTransform(y, [-SWIPE_DISTANCE, -25], [1, 0])
  const [forced, setForced] = useState<Action | null>(null)
  const [details, setDetails] = useState(false)
  const gone = useRef(false)

  const fling = async (a: Action) => {
    if (gone.current) return
    gone.current = true
    setForced(a)
    const to = { like: [700, 60], nope: [-700, 60], crush: [0, -900], pricey: [0, 900], noton: [-700, 60] }[a]
    await Promise.all([
      animate(x, to[0], { duration: 0.32, ease: 'easeIn' }),
      animate(y, to[1], { duration: 0.32, ease: 'easeIn' }),
    ])
    onSwiped(a)
  }
  useImperativeHandle(ref, () => ({ fling }))

  const discount = card.old_price && card.price && card.old_price > card.price
    ? Math.round(100 * (1 - card.price / card.old_price)) : 0
  const flags = [...card.green.slice(0, 1).map(f => ['g', f]), ...card.red.slice(0, 1).map(f => ['r', f])]

  return (
    <motion.div
      className="card"
      style={{ x, y, rotate }}
      drag={!details}
      dragElastic={0.9}
      onDragEnd={(_, info) => {
        const { offset, velocity } = info
        if (offset.x > SWIPE_DISTANCE || velocity.x > 700) fling('like')
        else if (offset.x < -SWIPE_DISTANCE || velocity.x < -700) fling('nope')
        else if (offset.y < -SWIPE_DISTANCE || velocity.y < -700) fling('crush')
        else {
          animate(x, 0, { type: 'spring', stiffness: 400, damping: 30 })
          animate(y, 0, { type: 'spring', stiffness: 400, damping: 30 })
        }
      }}
      initial={{ scale: 0.96, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      <div className="card-photo">
        <img src={card.tryon ?? card.image} alt={card.title} draggable={false} className={card.tryon ? 'on-you' : undefined} />
        <div className="badge"><b>{card.match}%</b> match</div>
        {card.pick && <div className={`pick ${card.pick.purpose}`} title={card.line}>{card.pick.of ? <img src={card.pick.of} alt="" /> : <Sparkle size={12} />}{card.pick.label}</div>}
        <button className="card-info-btn" onClick={() => setDetails(true)} aria-label="Details"><Info size={16} /></button>
        <motion.div className="stamp like" style={{ opacity: forced === 'like' ? 1 : likeO }}>{STAMPS.like}</motion.div>
        <motion.div className="stamp nope" style={{ opacity: forced === 'nope' ? 1 : nopeO }}>{STAMPS.nope}</motion.div>
        <motion.div className="stamp crush" style={{ opacity: forced === 'crush' ? 1 : crushO }}>{STAMPS.crush}</motion.div>
        {forced === 'pricey' && <div className="stamp pricey">{STAMPS.pricey}</div>}
      </div>

      <div className="card-body" onClick={() => setDetails(true)}>
        {card.brand && <div className="card-brand">{card.brand}</div>}
        <div className="price-row">
          <span className="price">{money(card.price)}</span>
          {discount > 0 && <><span className="was">{money(card.old_price)}</span><span className="off">{discount}% off</span></>}
          {card.rating && <span className="rating"><Star size={12} filled />{card.rating.toFixed(1)}</span>}
        </div>
        {flags.length > 0 && (
          <div className="flags">{flags.map(([t, f]) => <div key={f} className={`flag ${t}`}>{f}</div>)}</div>
        )}
      </div>

      {details && (
        <div className="details" onPointerDown={e => e.stopPropagation()}>
          <div className="details-head">
            <div>
              {card.brand && <div className="card-brand" style={{ marginBottom: 4 }}>{card.brand}</div>}
              <h3>{card.title}</h3>
            </div>
            <button className="icon-btn" onClick={() => setDetails(false)} aria-label="Close"><X size={16} /></button>
          </div>
          <div className="price-row">
            <span className="price">{money(card.price)}</span>
            {discount > 0 && <><span className="was">{money(card.old_price)}</span><span className="off">{discount}% off</span></>}
          </div>
          {card.rating && (
            <p className="sub" style={{ fontSize: 13 }}>
              Rated {card.rating.toFixed(1)} from {card.reviews?.toLocaleString('en-IN')} reviews{card.bought ? ` · ${card.bought}` : ''}
            </p>
          )}
          <div className="section">
            <div className="section-title">Green flags</div>
            {card.green.length ? card.green.map(f => <div key={f} className="flag g">{f}</div>) : <p className="sub">Cupid is still learning your taste.</p>}
          </div>
          <div className="section">
            <div className="section-title">Red flags</div>
            {card.red.length ? card.red.map(f => <div key={f} className="flag r">{f}</div>) : <p className="sub">Nothing stands out.</p>}
          </div>
          <div className="section">
            <div className="attrs">
              {Object.entries(card.tags).filter(([k]) => !['group', 'tone', 'vibe'].includes(k)).map(([k, v]) => <span key={k}>{v}</span>)}
            </div>
          </div>
          <a className="btn btn-primary" href={card.link} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none' }}>
            View product <External size={16} />
          </a>
        </div>
      )}
    </motion.div>
  )
})

function FitOverlay({ card, onClose }: { card: Card; onClose: () => void }) {
  return (
    <div className="overlay fit" onClick={onClose}>
      <p className="eyebrow" style={{ color: 'rgba(255,255,255,.55)' }}>Cupid called it at {card.match}%</p>
      <h1>It's a fit.</h1>
      <div className="frame"><img src={card.image} alt="" /></div>
      <button className="btn" onClick={onClose}>Keep swiping</button>
    </div>
  )
}

function ChangeLooking({ sid, onClose, onChanged }: { sid: string; onClose: () => void; onChanged: (c: Card, l: { id: string; label: string }[]) => void }) {
  const [goal, setGoal] = useState<string | null>(null)
  const [filters, setFilters] = useState<ChosenFilters>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { api.session(sid).then(x => setGoal(x.goal)).catch(e => setError(e.message)) }, [sid])

  const go = async () => {
    setBusy(true)
    setError('')
    try {
      const card = await api.changeLooking(sid, { ...LOOKING, filters })
      const info = await api.session(sid)
      onChanged(card, info.looking)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  const n = filterCount(filters)

  return (
    <div className="overlay sheet">
      <div className="flow-head">
        <button className="icon-btn" onClick={onClose} aria-label="Back"><ArrowLeft size={18} /></button>
      </div>
      {busy ? (
        <div className="center"><div><div className="spinner" /><p style={{ fontWeight: 600 }}>Finding dresses for you</p></div></div>
      ) : (
        <>
          <div className="sheet-body">
            <div>
              <h1 className="flow-title">Refine</h1>
              <p className="sub" style={{ marginTop: 10 }}>Set anything you're sure about. Cupid keeps everything it has learned.</p>
            </div>
            {goal && <FiltersStep goal={goal} looking={LOOKING} value={filters} onChange={setFilters} />}
            {error && <div className="error">{error}</div>}
          </div>
          <div className="flow-foot">
            <button className="btn btn-primary" onClick={go}>{n ? `Show results · ${n} filter${n > 1 ? 's' : ''}` : 'Show results'}</button>
          </div>
        </>
      )}
    </div>
  )
}

/** Super like: Cupid dresses you in it (YouCam virtual try-on), then you decide how it looks on you. */
function TryOn({ sid, card, onVerdict }: { sid: string; card: Card; onVerdict: (a: Action) => void }) {
  const [result, setResult] = useState<{ image: string; card: Card; verdict: (Verdict & { error?: string }) | null } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.tryOn(sid, card.id).then(setResult).catch(e => setError(e.message))
  }, [sid, card.id])

  const c = result?.card ?? card
  const v = result?.verdict && !result.verdict.error ? result.verdict : null
  const green = v ? v.green_flags : c.green
  const red = v ? v.red_flags : c.red
  return (
    <div className="overlay sheet">
      <div className="sheet-body">
        <div>
          <p className="eyebrow">Super like · try-on</p>
          <h1 className="flow-title" style={{ marginTop: 8 }}>{result ? <>How does it<br />look on <em>you</em>?</> : error ? <>Try-on isn't<br />available</> : <>Cupid is<br />dressing you…</>}</h1>
        </div>
        <div className="tryon">
          <div className="tryon-main">
            {result ? <img src={result.image} alt="You wearing the dress" /> : error ? (
              <div className="center"><div className="error">{error}</div></div>
            ) : <div className="skeleton"><div className="ph" /></div>}
          </div>
          <div className="tryon-garment"><img src={card.image} alt={card.title} /></div>
        </div>
        <div className="proscons">
          <div>
            <div className="section-title">Green flags</div>
            {green.length ? green.map(f => <div key={f} className="flag g">{f}</div>) : <p className="sub">Nothing yet.</p>}
          </div>
          <div>
            <div className="section-title">Red flags</div>
            {red.length ? red.map(f => <div key={f} className="flag r">{f}</div>) : <p className="sub">None that Cupid can see.</p>}
          </div>
        </div>
      </div>
      <div className="flow-foot verdict">
        <button className="btn btn-secondary" disabled={!result && !error} onClick={() => onVerdict('noton')}><X size={18} /> Not on me</button>
        <button className="btn btn-primary" disabled={!result && !error} onClick={() => onVerdict('crush')}><Heart size={18} filled /> Love it on me</button>
      </div>
    </div>
  )
}
