import { useState } from 'react'
import Board from './Board'
import Deck from './Deck'
import Matches from './Matches'
import Onboarding from './Onboarding'
import Welcome from './Welcome'

const SESSION_KEY = 'cupid-session'

function load(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function save(sid: string | null) {
  try {
    if (sid) sessionStorage.setItem(SESSION_KEY, sid)
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    /* private mode: the session just won't survive a reload */
  }
}

export default function App() {
  const [sid, setSid] = useState<string | null>(load)
  const [screen, setScreen] = useState<'deck' | 'matches'>('deck')
  const [welcomed, setWelcomed] = useState(false)

  if (window.location.pathname.startsWith('/board')) return <Board />

  const start = (id: string) => {
    save(id)
    setSid(id)
    setScreen('deck')
  }
  const restart = () => {
    save(null)
    setSid(null)
  }

  return (
    <div className="shell">
      <div className="phone">
        {!sid && !welcomed && <Welcome onStart={() => setWelcomed(true)} />}
        {!sid && welcomed && <Onboarding onStart={start} />}
        {sid && screen === 'deck' && <Deck sid={sid} onMatches={() => setScreen('matches')} onRestart={restart} />}
        {sid && screen === 'matches' && <Matches sid={sid} onBack={() => setScreen('deck')} />}
      </div>
    </div>
  )
}
