import { useEffect, useState } from 'react'
import './board.css'
import Logo from './Logo'
import { api, type Brand, type Grid, type MindMap, type Report, type Undertone } from './api'

type Tip = { x: number; y: number; text: string } | null
type SetTip = (t: Tip) => void

const pct = (v: number | null | undefined) => (v == null ? '–' : `${Math.round(v * 100)}%`)
const ACTION_EMOJI = { like: '♥ Liked', crush: '★ Loved on me', nope: '✕ Passed', pricey: '$ Too pricey', noton: '✕ Not on me' }

export default function Board() {
  const [live, setLive] = useState<Report | null>(null)
  const [brand, setBrand] = useState<Brand | null>(null)
  const [tab, setTab] = useState<'shopper' | 'brand'>('shopper')
  const [tip, setTip] = useState<Tip>(null)

  useEffect(() => {
    let stop = false
    const tick = async () => {
      try {
        const [b, br] = await Promise.all([api.board(), api.brand()])
        if (!stop) { setLive(b.live); setBrand(br) }
      } catch { /* API restarting; try again next tick */ }
    }
    tick()
    const id = setInterval(tick, 1500)
    return () => { stop = true; clearInterval(id) }
  }, [])

  return (
    <div className="board">
      <div className="board-head">
        <Logo size={30} />
        <div className="live"><i /> Live analytics{live ? ` · ${live.goal}` : ''}</div>
        <div className="tabs">
          <button className={tab === 'shopper' ? 'on' : ''} onClick={() => setTab('shopper')}>Shopper insights</button>
          <button className={tab === 'brand' ? 'on' : ''} onClick={() => setTab('brand')}>Brand insights</button>
        </div>
        <a className="back-link" href="/">← Open the app</a>
      </div>
      {tab === 'shopper' && (live ? <Shopper r={live} setTip={setTip} /> : <div className="empty">Waiting for someone to swipe… open the app on a phone 📱</div>)}
      {tab === 'brand' && (brand && brand.swipes ? <BrandView b={brand} setTip={setTip} /> : <div className="empty">No swipes yet.</div>)}
      {tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </div>
  )
}

function Shopper({ r, setTip }: { r: Report; setTip: SetTip }) {
  const rounds = r.report.rounds
  const slots = r.report.slots
  const random = slots.random
  const cupidSlots = Object.entries(slots).filter(([k]) => k !== 'random')
  const cupidN = cupidSlots.reduce((a, [, d]) => a + d.n, 0)
  const cupidRate = cupidN ? cupidSlots.reduce((a, [, d]) => a + d.likes, 0) / cupidN : null

  return (
    <>
      <div className="tiles">
        <div className="tile hero">
          <div className="k">Cupid's picks liked</div>
          <div className="v">{pct(cupidRate)}</div>
          <div className="s">vs {pct(random?.like_rate)} for random cards ({random?.n ?? 0} shown)</div>
        </div>
        <div className="tile">
          <div className="k">Called shots</div>
          <div className="v">{r.bets.made ? `${r.bets.right}/${r.bets.made}` : '–'}</div>
          <div className="s">Cupid bet on the swipe before it happened</div>
        </div>
        <div className="tile">
          <div className="k">Swipes</div>
          <div className="v">{r.swipes}</div>
          <div className="s">every one taught Cupid something</div>
        </div>
        <div className="tile">
          <div className="k">Browsing time captured</div>
          <div className="v">{r.minutes} min</div>
          <div className="s">a normal shop forgets all of this</div>
        </div>
      </div>

      <div className="grid2">
        <MindPanel m={r.mind_map} setTip={setTip} />
        <Learned r={r} />

        <div className="panel">
          <h3>Cupid's experiments</h3>
          <div className="sub">
            Every few swipes Cupid's LLM checks its guesses about the shopper, then picks the next cards to test them.
            {r.planned_shown > 0 && <> It chose <b>{r.planned_shown}</b> of the {r.swipes} cards so far; the rest were warm-up and random checks.</>}
          </div>
          {r.experiments.length === 0 ? <div className="note">Cupid starts experimenting after the first few swipes.</div> : (
            <div className="exps">
              {r.experiments.map(e => (
                <div key={e.hypothesis} className="exp">
                  <span className={`exp-status ${e.status}`}>{e.status === 'confirmed' ? '✓ Confirmed' : e.status === 'rejected' ? '✕ Wrong' : '… Testing'}</span>
                  <div><b>{e.hypothesis}</b><span>{e.evidence}</span></div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <h3>Cupid's mind, live</h3>
          <div className="sub">
            {r.llm ? <>An LLM ({r.llm}) rewrites its profile of the shopper after every swipe.</> : 'What the agent concluded after each swipe.'}
          </div>
          {r.profile && (
            <div className="mind">
              <p className="mind-summary">{r.profile.summary}</p>
              <div className="mind-beliefs">
                {r.profile.likes.map(b => (
                  <span key={b.attribute} className="belief yes" title={b.why} style={{ opacity: 0.45 + 0.55 * b.strength }}>
                    + {b.attribute.split(':')[1]}
                  </span>
                ))}
                {r.profile.dislikes.map(b => (
                  <span key={b.attribute} className="belief no" title={b.why} style={{ opacity: 0.45 + 0.55 * b.strength }}>
                    − {b.attribute.split(':')[1]}
                  </span>
                ))}
              </div>
              <p className="mind-testing">Testing next: {r.profile.testing}</p>
            </div>
          )}
          {r.colouring && (
            <p className="note" style={{ marginTop: 0, marginBottom: 10, color: 'var(--text-secondary)', fontSize: 13 }}>
              Started from a photo: <b style={{ textTransform: 'capitalize' }}>{r.colouring.undertone}</b> undertone
              {r.colouring.contrast ? `, ${r.colouring.contrast} contrast` : ''} · {r.tryons} try-on{r.tryons === 1 ? '' : 's'} so far
            </p>
          )}
          <div className="timeline">
            {r.thoughts.length === 0 && <div className="note">Waiting for the first swipe.</div>}
            {r.thoughts.map(t => (
              <div key={t.n} className="q"><span className="who cupid">Swipe {t.n + 1}</span><span>{t.text}</span></div>
            ))}
          </div>
        </div>

        <div className="panel">
          <h3>Does Cupid learn? Liked: Cupid's picks vs random cards</h3>
          <div className="sub">Random cards are mixed in as a control group. If Cupid is learning, its bars pull ahead.</div>
          <PairBars setTip={setTip} rounds={rounds.map(x => ({ label: `R${x.round}`, a: x.cupid_like_rate, b: x.random_like_rate }))}
            names={["Cupid's picks", 'Random cards']} />
        </div>

        <div className="panel">
          <h3>Cupid's guesses right, by round</h3>
          <div className="sub">Scored on the guess made <b>before</b> each swipe, against a guesser that always picks your usual answer.</div>
          <PairBars setTip={setTip} rounds={rounds.map(x => ({ label: `R${x.round}`, a: x.accuracy, b: x.baseline_accuracy }))}
            names={['Cupid', 'Always-guess-usual']} />
        </div>

        <div className="panel">
          <h3>Taste, as Cupid sees it right now</h3>
          <div className="sub">Each attribute compared with its alternatives. Longer bar = more evidence.</div>
          <Taste items={r.taste} setTip={setTip} />
        </div>

        <div className="panel">
          <h3>What Cupid searched for</h3>
          <div className="sub">A normal shop runs what you typed. Cupid rewrites the search from what it learned.</div>
          <div className="timeline">
            {r.searches.length === 0 && <div className="note">No searches yet. Cupid goes shopping 5 cards before each round ends.</div>}
            {r.searches.map((s, i) => (
              <div key={i} className="q">
                <span className={`who ${s.by}`}>{s.by === 'you' ? 'You' : `Cupid · R${s.round}`}</span>
                <span><code>"{s.query}"</code>{s.why && <span className="why-line">{s.why}</span>}</span>
                <span className="src">{s.source === 'live' ? 'new search' : s.source === 'cache' || s.source === 'catalogue' ? 'from catalogue' : s.source}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <h3>When Cupid says X%, is it right?</h3>
          <div className="sub">Calibration: the match % should mean what it says.</div>
          <table className="cal">
            <thead><tr><th>Cupid said</th><th>Cards</th><th>Average guess</th><th>Actually liked</th></tr></thead>
            <tbody>
              {r.report.calibration.map(c => (
                <tr key={c.bucket}><td>{c.bucket}</td><td>{c.n}</td><td>{pct(c.predicted)}</td><td><b>{pct(c.actual)}</b></td></tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h3>Latest swipes</h3>
          <div className="sub">Cupid's guess before each swipe, and whether it was right.</div>
          <div className="recent">
            {r.recent.map((x, i) => (
              <div key={i} className="r">
                <img src={x.image} alt={x.title} />
                <b>{x.match}%</b><span style={{ display: 'block', color: 'var(--text-secondary)' }}>{ACTION_EMOJI[x.action]}</span>
                <span style={{ color: x.correct ? '#006300' : '#c0213f' }}>{x.correct ? '✓ guessed' : '✗ missed'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

// A change of mind reads as a gain (towards liking), a loss (towards disliking) or a nudge.
const changeKind = (c: string) =>
  c.startsWith('New like') || c.startsWith('You want') || c.endsWith('→ like') ? 'yes'
    : c.startsWith('New dislike') || c.startsWith('Less keen') || c.endsWith('→ dislike') ? 'no' : 'meh'

function Learned({ r }: { r: Report }) {
  const rounds = r.report.rounds.filter(x => x.swipes > 0)
  const first = rounds[0], last = rounds.at(-1)
  return (
    <div className="panel span2">
      <h3>How Cupid learned you</h3>
      <div className="sub">
        The swipes that changed Cupid's mind most, and what it concluded from each.
        {first && last && last !== first && <> Its guesses went from <b>{pct(first.accuracy)}</b> right in round {first.round} to <b>{pct(last.accuracy)}</b> in round {last.round}.</>}
      </div>
      {r.turning_points.length === 0
        ? <div className="note">Cupid's first impressions are still forming. Turning points show up after a few swipes.</div>
        : (
          <div className="turns">
            {r.turning_points.map((t, i) => (
              <div key={i} className="turn">
                {t.item.image && <img src={t.item.image} alt={t.item.title} />}
                <div>
                  <div className="when">{t.action === 'told'
                    ? <>After swipe {t.n} · Cupid asked: {t.question}</>
                    : <>Swipe {t.n + 1} · {ACTION_EMOJI[t.action]}</>}</div>
                  <p>{t.text}</p>
                  <div className="chips">
                    {t.changes.map(c => <span key={c} className={`belief ${changeKind(c)}`}>{c}</span>)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
    </div>
  )
}

const TONES: Undertone[] = ['warm', 'neutral', 'cool']

function BrandInsights({ b, setTip }: { b: Brand; setTip: SetTip }) {
  const t = b.tryon
  return (
    <div className="grid2" style={{ marginBottom: 14 }}>
      <StylePanel g={b.style_map} setTip={setTip} />
      <div className="panel">
        <h3>Loved on the model, not on them</h3>
        <div className="sub">
          Every super like is tried on the shopper's own photo with YouCam Clothes Try-On.
          A "Not on me" is a return that never had to happen.
        </div>
        {t.tries === 0 ? <div className="note">No try-ons yet.</div> : (
          <>
            <p className="headline"><b>{t.not_on} of {t.tries}</b> try-ons rejected once shoppers saw it on themselves</p>
            <div className="recent">
              {t.dresses.map(d => (
                <div key={d.image} className="r">
                  <img src={d.image} alt={d.title} />
                  <b>{d.tries} try-on{d.tries === 1 ? '' : 's'}</b>
                  <span style={{ color: d.not_on ? '#c0213f' : '#006300' }}>{d.not_on ? `✕ ${d.not_on} not on me` : '★ loved on them'}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="panel">
        <h3>Colour, by skin undertone</h3>
        <div className="sub">
          Share of right swipes per colour, split by the undertone YouCam Skin Tone Analysis read from each shopper's photo
          ({TONES.map(x => `${b.undertones[x]} ${x}`).join(', ')}): which shades to make and show for whom.
        </div>
        <Heatmap g={b.undertone_map} what="colour" setTip={setTip} />
      </div>

      <div className="panel">
        <h3>Why shoppers pass</h3>
        <div className="sub">What Cupid's LLM concluded each shopper dislikes, pooled across {b.profiled} shopper{b.profiled === 1 ? '' : 's'}, in its own words.</div>
        {b.dislikes.length === 0 ? <div className="note">No dislikes learned yet.</div> : (
          <div className="why">
            {b.dislikes.map(d => (
              <div key={d.label} className="why-row">
                <span className="belief no">{d.label}</span>
                <span className="n">{d.shoppers} shopper{d.shoppers === 1 ? '' : 's'}</span>
                <span className="quote">{d.why.map(w => `"${w}"`).join(' · ')}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function BrandView({ b, setTip }: { b: Brand; setTip: SetTip }) {
  return (
    <>
      <div className="tiles">
        <div className="tile hero"><div className="k">Shoppers</div><div className="v">{b.shoppers}</div><div className="s">pooled, never individual</div></div>
        <div className="tile"><div className="k">Swipes</div><div className="v">{b.swipes}</div><div className="s">each one a taste signal</div></div>
        <div className="tile"><div className="k">Browsing time captured</div><div className="v">{b.minutes} min</div><div className="s">turned into demand data</div></div>
      </div>
      <BrandInsights b={b} setTip={setTip} />
      <div className="grid2">
        <div className="panel">
          <h3>Most loved attributes</h3>
          <div className="sub">Share of swipes that were a like or crush (attributes seen at least 5 times).</div>
          <HBars rows={b.loved.map(x => ({ label: x.label, value: x.like_rate, n: x.n }))} setTip={setTip} />
        </div>
        <div className="panel">
          <h3>Where price blocks demand</h3>
          <div className="sub">"Love it, too pricey" swipes: demand nobody is serving at that price.</div>
          {b.too_pricey.length ? <HBars rows={b.too_pricey.map(x => ({ label: x.label, value: x.pricey_rate, n: x.n }))} setTip={setTip} />
            : <div className="note">No "too pricey" swipes yet.</div>}
        </div>
      </div>
    </>
  )
}

/* ---------- charts ---------- */

// Sequential blue ramp (like rate) and a blue ↔ red diverging scale (like ↔ dislike) around a neutral gray.
const SEQ = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']
const NEUTRAL = '#f0efec', LIKE = '#2a78d6', DISLIKE = '#e34948'
const rgb = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
const mix = (a: string, b: string, t: number) =>
  `#${rgb(a).map((v, i) => Math.round(v + (rgb(b)[i] - v) * t).toString(16).padStart(2, '0')).join('')}`
const seq = (t: number) => {
  const x = Math.max(0, Math.min(1, t)) * (SEQ.length - 1), i = Math.min(SEQ.length - 2, Math.floor(x))
  return mix(SEQ[i], SEQ[i + 1], x - i)
}
const div = (v: number) => mix(NEUTRAL, v >= 0 ? LIKE : DISLIKE, Math.min(1, Math.abs(v)))
const inkOn = (h: string) => {
  const [r, g, b] = rgb(h).map(c => c / 255)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? '#0b0b0b' : '#ffffff'
}
const hover = (setTip: SetTip, text: string) => ({
  onMouseMove: (e: React.MouseEvent) => setTip({ x: e.clientX, y: e.clientY, text }),
  onMouseLeave: () => setTip(null),
})

// Like rate by two attributes: one blue ramp, gray where there are too few swipes to say.
function Heatmap({ g, what, setTip }: { g: Grid; what: string; setTip: SetTip }) {
  if (!g.rows.length) return <div className="note">No swipes on these yet.</div>
  return (
    <div className="chart">
      <div className="hm" style={{ gridTemplateColumns: `minmax(84px, max-content) repeat(${g.cols.length}, minmax(44px, 1fr))` }}>
        <span />
        {g.cols.map(c => <span key={c} className="hm-col">{c}</span>)}
        {g.rows.map((r, i) => [
          <span key={r} className="hm-row">{r}</span>,
          ...g.cols.map((c, j) => {
            const cell = g.cells[i][j]
            const fill = cell.rate == null ? undefined : seq(cell.rate)
            const tip = cell.rate == null ? `${r} · ${c}: ${cell.n ? `only ${cell.n} swipe${cell.n === 1 ? '' : 's'}` : 'no swipes'}`
              : `${r} · ${c}: ${pct(cell.rate)} liked (${cell.n} swipes)`
            return (
              <div key={`${r}-${c}`} className={`hm-cell ${fill ? '' : 'thin'}`} style={fill ? { background: fill, color: inkOn(fill) } : undefined}
                aria-label={tip} {...hover(setTip, tip)}>
                {cell.rate == null ? '' : pct(cell.rate)}
              </div>
            )
          }),
        ])}
      </div>
      <div className="hm-legend">
        <span>0% liked</span><i style={{ background: `linear-gradient(90deg, ${SEQ.join(', ')})` }} /><span>100%</span>
        <span className="thin-key"><b className="hm-cell thin" />fewer than 3 swipes</span>
      </div>
      <div className="note">Rows: {what}, most swiped first. Hover a cell for its count.</div>
    </div>
  )
}

function StylePanel({ g, setTip }: { g: Grid; setTip: SetTip }) {
  return (
    <div className="panel">
      <h3>What sells: silhouette × colour</h3>
      <div className="sub">Share of right swipes for each cut in each colour, pooled across every shopper. The darkest cells are the combinations to make more of.</div>
      <Heatmap g={g} what="silhouette" setTip={setTip} />
    </div>
  )
}

// Cupid's mind, swipe by swipe: each row a belief, blue = it thinks you like it, red = you don't.
function MindPanel({ m, setTip }: { m: MindMap; setTip: SetTip }) {
  const n = m.swipes.length
  const toldAt = new Map(m.told.map(t => [t.after + 1, t]))
  return (
    <div className="panel span2">
      <h3>How Cupid's mind changed</h3>
      <div className="sub">
        What Cupid's LLM believed about this shopper after every swipe{n ? ` (swipes ${m.swipes[0]}–${m.swipes[n - 1]})` : ''}.
        Watch beliefs appear, flip and firm up. ◆ marks where the shopper answered one of Cupid's this-or-thats.
      </div>
      {n === 0 ? <div className="note">Cupid's beliefs show up here after the first few swipes.</div> : (
        <div className="chart">
          <div className="hm mind" style={{ gridTemplateColumns: `minmax(110px, max-content) repeat(${n}, minmax(6px, 1fr))` }}>
            <span />
            {m.swipes.map(w => {
              const t = toldAt.get(w)
              return <span key={w} className="hm-told" {...(t ? hover(setTip, `You told Cupid: ${t.changes.join(', ')}`) : {})}>{t ? '◆' : ''}</span>
            })}
            {m.rows.map(r => [
              <span key={r.label} className="hm-row">{r.label}</span>,
              ...r.values.map((v, j) => {
                const tip = `After swipe ${m.swipes[j]}: ${v > 0 ? `likes ${r.label}` : v < 0 ? `dislikes ${r.label}` : `no view on ${r.label}`}${v ? ` (${Math.round(Math.abs(v) * 100)}% sure)` : ''}`
                return <div key={`${r.label}-${j}`} className="hm-cell" style={{ background: div(v) }} aria-label={tip} {...hover(setTip, tip)} />
              }),
            ])}
            <span />
            {m.swipes.map((w, j) => <span key={`x${w}`} className="hm-x">{j === 0 || j === n - 1 || w % 5 === 0 ? w : ''}</span>)}
          </div>
          <div className="hm-legend">
            <span>Dislikes</span><i style={{ background: `linear-gradient(90deg, ${DISLIKE}, ${NEUTRAL}, ${LIKE})` }} /><span>Likes</span>
            <span className="thin-key">gray = no opinion yet · columns = swipes</span>
          </div>
        </div>
      )}
    </div>
  )
}

function PairBars({ rounds, names, setTip }: { rounds: { label: string; a: number | null; b: number | null }[]; names: [string, string]; setTip: SetTip }) {
  const W = 460, H = 190, top = 14, bottom = 22, left = 30
  const plotH = H - top - bottom
  const n = Math.max(rounds.length, 1)
  const group = (W - left) / n
  const bw = Math.min(22, group / 3)
  const yOf = (v: number) => top + plotH * (1 - v)
  const last = rounds.length - 1

  // labelY: where the value label sits, so two similar bars don't print on top of each other
  const bar = (v: number | null, x: number, color: string, name: string, label: string, labelY: number | null) => {
    if (v == null) return null
    const y = yOf(v), h = Math.max(plotH * v, 2)
    return (
      <g onMouseMove={e => setTip({ x: e.clientX, y: e.clientY, text: `${label} · ${name}: ${pct(v)}` })} onMouseLeave={() => setTip(null)}>
        <rect x={x - 4} y={top} width={bw + 8} height={plotH} fill="transparent" />
        <path d={roundedTop(x, y, bw, h)} fill={color} />
        {labelY != null && <text className="val" x={x + bw / 2} y={labelY} textAnchor="middle">{pct(v)}</text>}
      </g>
    )
  }
  const labelYs = (a: number | null, b: number | null): [number | null, number | null] => {
    const ya = a == null ? null : yOf(a) - 4
    let yb = b == null ? null : yOf(b) - 4
    if (ya != null && yb != null && Math.abs(ya - yb) < 14) yb = Math.min(ya, yb) - 14
    return [ya, yb]
  }

  return (
    <div className="chart">
      <div className="legend">
        <span><i style={{ background: 'var(--series-1)' }} />{names[0]}</span>
        <span><i style={{ background: 'var(--series-2)' }} />{names[1]}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${names[0]} vs ${names[1]} by round`}>
        {[0, 0.5, 1].map(t => (
          <g key={t}>
            <line x1={left} x2={W} y1={yOf(t)} y2={yOf(t)} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} strokeWidth={1} />
            <text x={left - 6} y={yOf(t) + 4} textAnchor="end">{t * 100}%</text>
          </g>
        ))}
        {rounds.map((r, i) => {
          const cx = left + group * i + group / 2
          const [ya, yb] = i === last ? labelYs(r.a, r.b) : [null, null]
          return (
            <g key={r.label}>
              {bar(r.a, cx - bw - 1, 'var(--series-1)', names[0], r.label, ya)}
              {bar(r.b, cx + 1, 'var(--series-2)', names[1], r.label, yb)}
              <text x={cx} y={H - 6} textAnchor="middle">{r.label}</text>
            </g>
          )
        })}
      </svg>
      {rounds.length === 0 && <div className="note">Fills in as rounds are played.</div>}
    </div>
  )
}

function roundedTop(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, w / 2, h)
  const b = y + h
  return `M${x},${b} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${b} Z`
}

function Taste({ items, setTip }: { items: Report['taste']; setTip: SetTip }) {
  if (!items.length) return <div className="note">Cupid needs a few swipes first.</div>
  const max = Math.max(...items.map(t => Math.abs(t.evidence)), 1)
  const W = 460, row = 24, labelW = 130, mid = labelW + (W - labelW) / 2, half = (W - labelW) / 2 - 8
  const H = items.length * row + 6
  return (
    <div className="chart">
      <div className="legend">
        <span><i style={{ background: 'var(--series-1)' }} />Into it</span>
        <span><i style={{ background: 'var(--neg)' }} />Not feeling it</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Taste by attribute">
        <line x1={mid} x2={mid} y1={0} y2={H} stroke="var(--axis)" />
        {items.map((t, i) => {
          const w = Math.max((Math.abs(t.evidence) / max) * half, 2)
          const pos = t.evidence >= 0
          const y = i * row + 4
          return (
            <g key={t.feature} onMouseMove={e => setTip({ x: e.clientX, y: e.clientY, text: `${t.label}: evidence ${t.evidence}` })} onMouseLeave={() => setTip(null)}>
              <rect x={0} y={y - 2} width={W} height={row} fill="transparent" />
              <text x={labelW - 8} y={y + 13} textAnchor="end" style={{ fill: 'var(--text-secondary)', textTransform: 'capitalize' }}>{t.label}</text>
              <rect x={pos ? mid + 1 : mid - 1 - w} y={y + 2} width={w} height={14} rx={4} fill={pos ? 'var(--series-1)' : 'var(--neg)'} />
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function HBars({ rows, setTip }: { rows: { label: string; value: number; n: number }[]; setTip: SetTip }) {
  const W = 460, row = 26, labelW = 130, valW = 44
  const plot = W - labelW - valW
  const H = rows.length * row + 4
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Attributes">
        {rows.map((r, i) => {
          const y = i * row + 4
          const w = Math.max(r.value * plot, 2)
          return (
            <g key={r.label} onMouseMove={e => setTip({ x: e.clientX, y: e.clientY, text: `${r.label}: ${pct(r.value)} of ${r.n} swipes` })} onMouseLeave={() => setTip(null)}>
              <rect x={0} y={y - 2} width={W} height={row} fill="transparent" />
              <text x={labelW - 8} y={y + 13} textAnchor="end" style={{ fill: 'var(--text-secondary)', textTransform: 'capitalize' }}>{r.label}</text>
              <rect x={labelW} y={y + 2} width={w} height={14} rx={4} fill="var(--series-1)" />
              <text className="val" x={labelW + w + 6} y={y + 13}>{pct(r.value)}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
