/**
 * The MARS mark: an acorn with a stream running into it.
 *
 * Flink's own mark is a squirrel, so an acorn reads as a deliberate companion
 * rather than something derivative — and it is a fair picture of what a stream job
 * holds: something small and self-contained that gets stored, kept, and found
 * again later. The resemblance stays visual. Flink is an Apache Software
 * Foundation trademark and the mark never implies endorsement.
 *
 * It simplifies itself when small. The three inbound lines are the whole point of
 * the design at 28 pixels and a grey smudge at 16, where a favicon lives, so below
 * 20 they are dropped and the acorn is centred and grown to fill the space it left.
 * Same family, drawn for the size it is actually used at — which is the reason the
 * previous mark existed at all: a scaled-down illustration read as a blur.
 */
export default function MarsMark({ size = 28, className = '', title }) {
  // Unique per instance: two marks on one page must not share gradient ids, or the
  // second silently inherits the first's.
  const id = `mars-${size}`
  const detailed = size >= 20

  const acorn = (
    <>
      <rect x="15.6" y="1.8" width="2.2" height="4.6" rx="1.1" fill="#7c2d12" />
      <path d="M6.7 15.2c0-5.6 4.5-9.6 10-9.6s10 4 10 9.6Z" fill={`url(#${id}-cap)`} />
      {/* The cap's scales. Fine enough to disappear gracefully rather than muddy. */}
      <path
        d="M10.3 11.4h12.8M8.9 13.6h15.6"
        stroke="#fdba74"
        strokeOpacity="0.28"
        strokeWidth="1.1"
        strokeLinecap="round"
      />
      <path
        d="M16.7 30.2C11.7 27 7.9 22 7.9 16.9c0-1.3 1-2.2 2.3-2.2h13c1.3 0 2.3.9 2.3 2.2 0 5.1-3.8 10.1-8.8 13.3Z"
        fill={`url(#${id}-nut)`}
      />
      <path
        d="M13.1 19.4c0 3 1.2 5.6 3 7.4"
        stroke="#ffffff"
        strokeOpacity="0.22"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </>
  )

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role={title ? 'img' : 'presentation'}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={`${id}-nut`} x1="8" y1="15" x2="24" y2="30"
                        gradientUnits="userSpaceOnUse">
          <stop stopColor="#fb923c" />
          <stop offset="0.6" stopColor="#ea580c" />
          <stop offset="1" stopColor="#b8430b" />
        </linearGradient>
        <linearGradient id={`${id}-cap`} x1="6" y1="6" x2="26" y2="15"
                        gradientUnits="userSpaceOnUse">
          <stop stopColor="#c2410c" />
          <stop offset="1" stopColor="#7c2d12" />
        </linearGradient>
      </defs>

      {detailed ? (
        <>
          {/* Uneven on purpose: a feed arrives in bursts, not in a comb. */}
          <path
            d="M1.6 11.8h5.2M1.6 16h3.4M1.6 20.2h4.4"
            stroke="#fdba74"
            strokeWidth="2"
            strokeLinecap="round"
          />
          {acorn}
        </>
      ) : (
        // Centred on the acorn's own axis (16.7) and grown into the space the
        // lines vacated, so the small mark fills its box instead of sitting
        // off to one side.
        <g transform="translate(16 16) scale(1.08) translate(-16.7 -16)">{acorn}</g>
      )}
    </svg>
  )
}
