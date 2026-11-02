export type Action = 'nope' | 'like' | 'crush' | 'pricey' | 'noton'

export interface Card {
  id: string
  title: string
  price: number | null
  old_price: number | null
  brand: string
  rating: number | null
  reviews: number | null
  bought: string | null
  store: string
  link: string
  image: string
  n_stores: number
  match: number
  slot: string
  bet: 'like' | 'nope' | null
  line: string
  // set when Cupid chose this card: its LLM's picks, its dates, or a look-alike of a dress you loved ('of' is that dress)
  pick: { purpose: 'best' | 'test' | 'surprise' | 'date' | 'alike'; label: string; of?: string | null } | null
  tryon?: string | null   // the shopper wearing it, when Cupid tried it on them on a date
  green: string[]
  red: string[]
  tags: Record<string, string>
  action?: Action
  verdict?: Verdict | null
}

export interface YourType {
  loves: Record<string, string[]>
  avoids: Record<string, string[]>
  summary: string
}

export interface Search {
  round: number
  query: string
  by: 'you' | 'cupid'
  source: string
  items: number
  why?: string | null
}

export interface Payoff {
  round: number
  liked: number
  swipes: number
  your_type: YourType
  cupid_search: Search | null
}

export interface SwipeResult {
  its_a_fit: boolean
  called_it: boolean | null
  thought: string
  early_refresh: boolean
  payoff: Payoff | null
  swipes: number
  next: Card | null
}

export interface Report {
  session: string
  goal: string
  swipes: number
  minutes: number
  report: {
    rounds: {
      round: number; swipes: number; accuracy: number; baseline_accuracy: number; like_rate: number; brier: number
      cupid_like_rate: number | null; random_like_rate: number | null
    }[]
    slots: Record<string, { n: number; likes: number; like_rate: number }>
    calibration: { bucket: string; n: number; predicted: number; actual: number }[]
  }
  taste: { feature: string; label: string; score: number; evidence: number }[]
  your_type: YourType
  searches: Search[]
  bets: { made: number; right: number }
  recent: { title: string; image: string; action: Action; match: number; correct: boolean; slot: string }[]
  thoughts: { n: number; text: string; by?: string }[]
  turning_points: { n: number; text: string; action: Action | 'told'; question?: string; shift: number; changes: string[]; item: { image: string; title: string } }[]
  colouring: Colouring | null
  tryons: number
  profile: Profile | null
  experiments: { hypothesis: string; status: 'testing' | 'confirmed' | 'rejected'; evidence: string }[]
  planned_shown: number
  dates: DateRound[]
  llm: string | null
}

export interface Brand {
  shoppers: number
  swipes: number
  minutes: number
  loved: { label: string; like_rate: number; n: number }[]
  too_pricey: { label: string; pricey_rate: number; n: number }[]
  tryon: { tries: number; not_on: number; dresses: { title: string; image: string; tries: number; not_on: number }[] }
  undertones: Record<Undertone, number>
  by_undertone: { label: string; gap: number; tones: Record<Undertone, { rate: number | null; n: number }> }[]
  profiled: number
  dislikes: { label: string; shoppers: number; why: string[] }[]
}

export type Undertone = 'warm' | 'neutral' | 'cool'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export interface Verdict {
  verdict: 'match' | 'pass'
  confidence: number
  reason: string
  green_flags: string[]
  red_flags: string[]
}

export interface MindEvent {
  id: number
  type: 'thought' | 'error' | 'dates'
  text: string
  item: { id: string; image: string; title: string } | null
}

// Near each round's end Cupid sums the shopper up and asks what its swipes couldn't settle.
export interface Side {
  attribute: string
  label: string
  id: string
  image: string
}

// This or that: a real dress for each side, alike except for the one thing Cupid is unsure about.
export interface Question {
  question: string
  a: Side
  b: Side
  a_reply: string
  b_reply: string
  answer: 'a' | 'b' | 'neither' | null
  reply: string | null
}

export interface Interview {
  status: 'thinking' | 'done' | 'none'
  read: string | null
  questions: Question[]
}

// Every dress the shopper has seen on themselves: their super likes ('you') and Cupid's dates.
export interface Look {
  id: string
  title: string
  price: number | null
  link: string
  image: string
  tryon: string
  by: 'you' | 'cupid'
  verdict: Verdict | null
}

// After each round Cupid tries a few dresses on the shopper by itself and keeps only what works on them.
export interface DateRound {
  round: number
  status: 'trying' | 'done'
  tried: { id: string; title: string; image: string; found: boolean; tryon: string | null; verdict: Verdict | null; error: string | null }[]
}

export interface Profile {
  summary: string
  likes: { attribute: string; strength: number; why: string }[]
  dislikes: { attribute: string; strength: number; why: string }[]
  testing: string
  thought: string
}

export interface Colouring {
  undertone: 'warm' | 'cool' | 'neutral'
  contrast: 'high' | 'medium' | 'low' | null
  skin: string
  hair: string | null
  eyes: string | null
}

export interface Options {
  looking: { id: string; label: string; hint: string }[]
  ready: Record<string, string[]> // occasion → answers already cached (instant)
  goals: { id: string; label: string }[]
  showcase: { image: string; title: string; price: number | null }[]
}

export interface Looking {
  looking: string[]
  text: string | null
}

export type ChosenFilters = Record<string, string[]> // Amazon filter group → option names

export interface FilterGroup {
  group: string
  label: string
  options: { name: string; rh: string; label: string }[]
}

export const api = {
  options: () => call<Options>('/api/options'),
  filters: (goal: string, v: Looking) => {
    const q = new URLSearchParams({ goal })
    if (v.text?.trim()) q.set('text', v.text.trim())
    else if (v.looking[0]) q.set('looking', v.looking[0])
    return call<{ label: string; items: number; groups: FilterGroup[] }>(`/api/filters?${q}`)
  },
  start: (body: Looking & { filters: ChosenFilters; goal: string; vibes: string[]; budget: number | null; photo_id: string | null }) =>
    call<{ id: string; pool: number; budget: number | null; searches: Search[]; first_pick: Card | null; colouring: Colouring | null }>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  changeLooking: (sid: string, body: Looking & { filters: ChosenFilters }) =>
    call<Card>(`/api/sessions/${sid}/looking`, { method: 'POST', body: JSON.stringify(body) }),
  session: (sid: string) =>
    call<{ looking: { id: string; label: string }[]; swipes: number; goal: string; has_photo: boolean; has_mind: boolean }>(`/api/sessions/${sid}`),
  events: (sid: string, after: number) => call<MindEvent[]>(`/api/sessions/${sid}/events?after=${after}`),
  uploadPhoto: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/photo', { method: 'POST', body: form })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Upload failed')
    return res.json() as Promise<{ photo_id: string }>
  },
  photoStatus: (pid: string) => call<{ ready: boolean; colouring: Colouring | null; error: string | null }>(`/api/photo/${pid}`),
  tryOn: (sid: string, itemId: string) => call<{ image: string; card: Card; verdict: (Verdict & { error?: string }) | null }>(`/api/sessions/${sid}/tryon/${itemId}`, { method: 'POST' }),
  next: (sid: string) => call<Card>(`/api/sessions/${sid}/next`),
  swipe: (sid: string, item_id: string, action: Action, dwell_ms: number) =>
    call<SwipeResult>(`/api/sessions/${sid}/swipe`, {
      method: 'POST',
      body: JSON.stringify({ item_id, action, dwell_ms }),
    }),
  rewind: (sid: string) => call<Card>(`/api/sessions/${sid}/rewind`, { method: 'POST' }),
  matches: (sid: string) => call<Card[]>(`/api/sessions/${sid}/matches`),
  report: (sid: string) => call<Report>(`/api/sessions/${sid}/report`),
  dates: (sid: string) => call<DateRound[]>(`/api/sessions/${sid}/dates`),
  questions: (sid: string, round: number) => call<Interview>(`/api/sessions/${sid}/questions/${round}`),
  answer: (sid: string, round: number, i: number, answer: 'a' | 'b' | 'neither') =>
    call<Question>(`/api/sessions/${sid}/questions/${round}/${i}`, { method: 'POST', body: JSON.stringify({ answer }) }),
  tryons: (sid: string) => call<Look[]>(`/api/sessions/${sid}/tryons`),
  board: () => call<{ live: Report | null }>('/api/board'),
  brand: () => call<Brand>('/api/brand'),
}

export const money = (n: number | null) =>
  n == null ? '' : `$${n.toLocaleString('en-US', { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 })}`
