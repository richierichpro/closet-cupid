import { animate, motion, useMotionValue, useTransform } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Heart, Sparkle, Star } from './Icons'
import Logo from './Logo'
import { api, money, type Options } from './api'

const KNOB = 60 // px, the draggable knob

/** First screen: two real dresses fanned like profiles, and a swipe-to-start pill. */
export default function Welcome({ onStart }: { onStart: () => void }) {
  const [show, setShow] = useState<Options['showcase']>([])
  const track = useRef<HTMLDivElement>(null)
  const x = useMotionValue(0)
  const hint = useTransform(x, [0, 120], [1, 0])

  useEffect(() => { api.options().then(o => setShow(o.showcase)).catch(() => {}) }, [])

  const finish = () => {
    const max = (track.current?.offsetWidth ?? 300) - KNOB - 8
    animate(x, max, { duration: 0.2 }).then(onStart)
  }

  return (
    <div className="welcome">
      <div className="welcome-word" aria-hidden>CUPID</div>
      <div className="welcome-brand"><Logo size={22} /></div>

      <div className="fan">
        {show[0] && <FanCard item={show[0]} className="back" />}
        {show[1] && <FanCard item={show[1]} className="front" />}
        <span className="float star"><Star size={20} filled /></span>
        <span className="float sparkle"><Sparkle size={20} /></span>
        <span className="float heart"><Heart size={24} filled /></span>
      </div>

      <div className="welcome-copy">
        <h1>Find Your<br /><em>Perfect</em> Fit</h1>
        <p>An AI stylist that learns your taste with every swipe, and shows you how it looks on you.</p>
      </div>

      <div className="slide" ref={track}>
        <motion.button
          className="slide-knob" aria-label="Get started" style={{ x }}
          drag="x" dragConstraints={track} dragElastic={0} dragMomentum={false}
          onDragEnd={() => {
            const max = (track.current?.offsetWidth ?? 300) - KNOB - 8
            if (x.get() > max * 0.6) finish()
            else animate(x, 0, { type: 'spring', stiffness: 400, damping: 30 })
          }}
          onTap={finish}
        >
          <ArrowRight size={22} weight={2.4} />
        </motion.button>
        <motion.span className="slide-label" style={{ opacity: hint }}>Get Started</motion.span>
        <motion.span className="slide-chevrons" style={{ opacity: hint }} aria-hidden>›››</motion.span>
      </div>
    </div>
  )
}

function FanCard({ item, className }: { item: Options['showcase'][number]; className: string }) {
  return (
    <div className={`fan-card ${className}`}>
      <img src={item.image} alt="" />
      <div className="fan-meta">
        <b>{item.title.split(/[|,(]/)[0].split(' ').slice(0, 4).join(' ')}</b>
        <span>{money(item.price)}</span>
      </div>
    </div>
  )
}
