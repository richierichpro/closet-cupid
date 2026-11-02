import { Check, Search } from './Icons'
import type { Looking, Options } from './api'

/** "What are you shopping for?": one category, or type it. */
export default function LookingPicker({ options, value, onChange, onSubmit }: {
  options: Options
  value: Looking
  onChange: (v: Looking) => void
  onSubmit?: () => void
}) {
  return (
    <>
      <div className="cats">
        {options.looking.map(o => {
          const on = value.looking.includes(o.id)
          return (
            <button key={o.id} className={`cat ${on ? 'on' : ''}`} aria-pressed={on}
              onClick={() => onChange({ looking: on ? [] : [o.id], text: '' })}>
              <span className="t">{o.label}</span>
              <span className="h">{o.hint}</span>
              {on && <span className="tick"><Check size={12} weight={3} /></span>}
            </button>
          )
        })}
      </div>
      <label className="search">
        <Search size={18} />
        <input placeholder="Or describe it: black linen kurta under 1500" value={value.text ?? ''}
          onChange={e => onChange({ looking: [], text: e.target.value })} onKeyDown={e => e.key === 'Enter' && onSubmit?.()} />
      </label>
    </>
  )
}

export const hasLooking = (v: Looking) => v.looking.length > 0 || !!v.text?.trim()
