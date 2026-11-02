import { useEffect, useState } from 'react'
import { api, type ChosenFilters, type FilterGroup, type Looking } from './api'

const SHOW = 10      // options per filter before "more"
const SHOW_ALL = 12  // a filter this short shows everything

/** Amazon's real filters for what you're shopping for. You set the ones you care about;
 *  Cupid learns the rest from your swipes. */
export default function FiltersStep({ goal, looking, value, onChange, only }: {
  goal: string
  looking: Looking
  value: ChosenFilters
  onChange: (v: ChosenFilters) => void
  only?: string[] // show just these filters (by label), e.g. ['Size']
}) {
  const [groups, setGroups] = useState<FilterGroup[] | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})

  useEffect(() => {
    setGroups(null)
    api.filters(goal, looking)
      .then(r => setGroups(only ? r.groups.filter(g => only.includes(g.label)) : r.groups))
      .catch(e => setError(e.message))
  }, [goal, looking, only])

  const toggle = (group: string, name: string) => {
    const now = value[group] ?? []
    const next = now.includes(name) ? now.filter(x => x !== name) : [...now, name]
    const out = { ...value }
    if (next.length) out[group] = next
    else delete out[group]
    onChange(out)
  }

  if (error) return <div className="error">{error}</div>
  if (!groups) {
    return (
      <div className="center" style={{ flex: 'none', padding: '48px 0' }}>
        <div><div className="spinner" /><p className="sub">Loading filters</p></div>
      </div>
    )
  }

  return (
    <div>
      {groups.map(g => {
        const chosen = value[g.group] ?? []
        const all = open[g.group] || g.options.length <= SHOW_ALL
        const shown = all ? g.options : g.options.slice(0, SHOW)
        return (
          <div key={g.group} className="filter-group" style={{ marginBottom: 18 }}>
            <div className="filter-label">{g.label}{chosen.length > 0 && <span>{chosen.join(', ')}</span>}</div>
            <div className="chips">
              {shown.map(o => (
                <button key={o.name} className={`chip ${chosen.includes(o.name) ? 'on' : ''}`} aria-pressed={chosen.includes(o.name)}
                  onClick={() => toggle(g.group, o.name)}>
                  {o.label}
                </button>
              ))}
              {!all && (
                <button className="chip more" onClick={() => setOpen({ ...open, [g.group]: true })}>{g.options.length - SHOW} more</button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export const filterCount = (v: ChosenFilters) => Object.values(v).reduce((n, x) => n + x.length, 0)
