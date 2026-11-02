/** Wordmark: a monoline heart pierced by an arrow, and the name set in the display serif. */
export default function Logo({ size = 22 }: { size?: number }) {
  return (
    <span className="logo" style={{ fontSize: size }}>
      <svg width={size * 0.95} height={size * 0.95} viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M12 20.5s-8.5-5-8.5-11.2A4.6 4.6 0 0 1 12 6.6a4.6 4.6 0 0 1 8.5 2.7c0 6.2-8.5 11.2-8.5 11.2z"
          fill="var(--accent)" />
        <path d="M3 21 21 3" stroke="var(--ink)" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M21 3h-4.2M21 3v4.2" stroke="var(--ink)" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span>Closet Cupid</span>
    </span>
  )
}
