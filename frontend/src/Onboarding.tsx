import { useEffect, useRef, useState } from 'react'
import FiltersStep, { filterCount } from './FiltersStep'
import { ArrowLeft, Check } from './Icons'
import Logo from './Logo'
import { api, money, type ChosenFilters, type Colouring, type Options } from './api'

const BUDGET_STEPS = [30, 40, 50, 60, 80, 100, 150, 0] // 0 = no limit
const LOOKING = { looking: ['dresses'], text: null }
const SIZE_ONLY = ['Size']
const VIBES = [
  { id: 'minimal', label: 'Minimal', hint: 'Clean lines, quiet colour' },
  { id: 'boho', label: 'Boho', hint: 'Flowy, earthy, free' },
  { id: 'romantic', label: 'Romantic', hint: 'Soft, floral, feminine' },
  { id: 'glam', label: 'Glam', hint: 'Shine and drama' },
  { id: 'classic', label: 'Classic', hint: 'Timeless and polished' },
  { id: 'edgy', label: 'Edgy', hint: 'Bold and dark' },
  { id: 'casual', label: 'Casual', hint: 'Easy, every day' },
  { id: 'y2k', label: 'Y2K', hint: 'Playful 2000s' },
]
const MAX_VIBES = 2
// Swatches for the colours Cupid suggests after reading your colouring.
export const SWATCH: Record<string, string> = {
  olive: '#6b7038', mustard: '#c9a227', orange: '#e07a3f', brown: '#7a4e2d', cream: '#efe6d2', green: '#2f7d4f',
  navy: '#1f2f5a', blue: '#2f6fd1', pink: '#e58fb1', purple: '#6c4bb6', maroon: '#7a1f35', teal: '#1f7f84',
  black: '#111111', white: '#f7f7f5', red: '#c8262f', beige: '#d8c3a5', pastel: '#c9b8e6', grey: '#8e8e8e',
}
export const PALETTE: Record<Colouring['undertone'], string[]> = {
  warm: ['olive', 'mustard', 'orange', 'brown', 'cream', 'green'],
  cool: ['navy', 'blue', 'pink', 'purple', 'maroon', 'teal'],
  neutral: ['teal', 'maroon', 'navy', 'green', 'cream', 'pink'],
}

export default function Onboarding({ onStart }: { onStart: (sid: string) => void }) {
  const [step, setStep] = useState(0)
  const [options, setOptions] = useState<Options | null>(null)
  const [goal, setGoal] = useState('date')
  const [vibes, setVibes] = useState<string[]>([])
  const [photo, setPhoto] = useState<{ id: string; url: string } | null>(null)
  const [colouring, setColouring] = useState<Colouring | null>(null)
  const [reading, setReading] = useState(false)
  const [photoError, setPhotoError] = useState('')
  const [filters, setFilters] = useState<ChosenFilters>({})
  const [budgetIdx, setBudgetIdx] = useState(BUDGET_STEPS.length - 1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.options().then(setOptions).catch(e => setError(e.message))
  }, [])

  const budget = BUDGET_STEPS[budgetIdx] || null
  const n = filterCount(filters)

  const toggleVibe = (v: string) =>
    setVibes(p => (p.includes(v) ? p.filter(x => x !== v) : p.length < MAX_VIBES ? [...p, v] : [p[1], v]))

  const pickPhoto = async (file: File | undefined) => {
    if (!file) return
    setPhotoError('')
    setColouring(null)
    setReading(true)
    try {
      const { photo_id } = await api.uploadPhoto(file)
      setPhoto({ id: photo_id, url: URL.createObjectURL(file) })
      for (let i = 0; i < 40; i++) { // Skin Tone Analysis runs in the background; poll for up to ~30 s
        const st = await api.photoStatus(photo_id)
        if (st.ready) {
          setColouring(st.colouring)
          if (st.error) setPhotoError(st.error.includes('face') ? st.error : 'Cupid couldn’t read your colouring from this photo. Try-on may still work.')
          break
        }
        await new Promise(r => setTimeout(r, 750))
      }
    } catch (e) {
      setPhotoError((e as Error).message)
    } finally {
      setReading(false)
    }
  }

  const go = async () => {
    setBusy(true)
    setError('')
    try {
      const s = await api.start({ ...LOOKING, filters, goal, vibes, budget, photo_id: photo?.id ?? null })
      onStart(s.id)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  if (busy) {
    return (
      <div className="center">
        <div>
          <div className="spinner" />
          <p style={{ fontWeight: 600 }}>Cupid is scanning the collection</p>
          <p className="sub" style={{ marginTop: 4 }}>Matching every dress to your occasion, vibe and colouring.</p>
        </div>
      </div>
    )
  }

  const canContinue = step !== 1 || vibes.length > 0

  return (
    <div className="flow">
      <div className="flow-head">
        {step === 0 ? <Logo /> : (
          <button className="icon-btn" onClick={() => setStep(step - 1)} aria-label="Back"><ArrowLeft size={18} /></button>
        )}
        <div className="steps" aria-label={`Step ${step + 1} of 4`}>{[0, 1, 2, 3].map(i => <i key={i} className={i <= step ? 'on' : ''} />)}</div>
      </div>

      <div className="flow-body">
        {step === 0 && (
          <>
            <div>
              <h1 className="flow-title">Your <em>styling agent</em><br />for the moment.</h1>
              <p className="sub" style={{ marginTop: 10 }}>Tell Cupid where you're going. It picks your dress, then learns your taste with every swipe.</p>
            </div>
            {options && (
              <div className="options" role="radiogroup" aria-label="Occasion">
                {options.goals.map(g => (
                  <button key={g.id} role="radio" aria-checked={goal === g.id} className={`option ${goal === g.id ? 'on' : ''}`}
                    onClick={() => { setGoal(g.id); setFilters({}) }}>
                    {g.label}
                    <span className="radio">{goal === g.id && <Check size={12} weight={3} />}</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {step === 1 && (
          <>
            <div>
              <h1 className="flow-title">What's your<br />vibe?</h1>
              <p className="sub" style={{ marginTop: 10 }}>Pick up to two. It's Cupid's starting point; your swipes take it from there.</p>
            </div>
            <div className="cats">
              {VIBES.map(v => {
                const on = vibes.includes(v.id)
                return (
                  <button key={v.id} className={`cat ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => toggleVibe(v.id)}>
                    <span className="t">{v.label}</span>
                    <span className="h">{v.hint}</span>
                    {on && <span className="tick"><Check size={12} weight={3} /></span>}
                  </button>
                )
              })}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <h1 className="flow-title">Add a photo<br />of you</h1>
              <p className="sub" style={{ marginTop: 10 }}>
                Cupid reads your colouring to know which shades flatter you, and dresses you in anything you super like.
                Full length, facing forward, good light.
              </p>
            </div>
            <input ref={fileRef} type="file" accept="image/*" hidden onChange={e => pickPhoto(e.target.files?.[0])} />
            {photo ? (
              <div className="photo-row">
                <img className="photo-thumb" src={photo.url} alt="Your photo" />
                <div className="photo-info">
                  {reading && <><div className="spinner" style={{ margin: '0 0 10px' }} /><p className="sub">Reading your colouring…</p></>}
                  {colouring && (
                    <>
                      <p className="eyebrow">Your colouring</p>
                      <p style={{ fontWeight: 600, textTransform: 'capitalize' }}>
                        {colouring.undertone} undertone{colouring.contrast ? ` · ${colouring.contrast} contrast` : ''}
                      </p>
                      <div className="swatches">
                        {PALETTE[colouring.undertone].map(c => <span key={c} title={c} style={{ background: SWATCH[c] }} />)}
                      </div>
                      <p className="sub" style={{ fontSize: 13 }}>Shades Cupid will lean towards first.</p>
                    </>
                  )}
                  {photoError && <p className="sub" style={{ fontSize: 13 }}>{photoError}</p>}
                  <button className="btn btn-text" style={{ height: 36, width: 'auto', padding: 0 }} onClick={() => fileRef.current?.click()}>Use another photo</button>
                </div>
              </div>
            ) : (
              <button className="photo-drop" onClick={() => fileRef.current?.click()}>
                <span style={{ fontWeight: 600 }}>Choose a photo</span>
                <span className="sub" style={{ fontSize: 13 }}>Used only for your colouring and try-ons</span>
              </button>
            )}
            {photoError && !photo && <div className="error">{photoError}</div>}
          </>
        )}

        {step === 3 && (
          <>
            <div>
              <h1 className="flow-title">Size and<br />budget</h1>
              <p className="sub" style={{ marginTop: 10 }}>The only hard rules. Everything else, Cupid learns.</p>
            </div>
            <FiltersStep goal={goal} looking={LOOKING} value={filters} onChange={setFilters} only={SIZE_ONLY} />
            <div className="filter-group">
              <div className="filter-label">Budget per dress<span>{budget ? `Up to ${money(budget)}` : 'No limit'}</span></div>
              <input type="range" min={0} max={BUDGET_STEPS.length - 1} value={budgetIdx}
                onChange={e => setBudgetIdx(Number(e.target.value))} aria-label="Budget per dress" />
            </div>
          </>
        )}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="flow-foot">
        {step < 3 ? (
          <>
            <button className="btn btn-primary" disabled={!canContinue || (step === 2 && reading)} onClick={() => setStep(step + 1)}>
              {step === 2 && !photo ? 'Continue without a photo' : 'Continue'}
            </button>
          </>
        ) : (
          <button className="btn btn-primary" onClick={go}>{n ? 'Find my dress · size set' : 'Find my dress'}</button>
        )}
      </div>
    </div>
  )
}
