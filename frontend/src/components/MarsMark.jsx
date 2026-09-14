/**
 * The MARS mark, drawn for small sizes.
 *
 * The full logo is an illustration -- planet, orbital ring, a squirrel, a dashboard
 * panel, stars, a wordmark. At 28 pixels all of that collapses into noise, which is
 * why a scaled-down PNG of it read as a smudge in the header.
 *
 * So this keeps only what survives: the red planet, the orbital ring, and two data
 * squares riding the ring for the streaming motif. Three shapes, drawn at the size
 * they are actually used, in the logo's own colours.
 *
 * Vector, so it stays crisp on any display and can be recoloured by whatever uses it.
 */
export default function MarsMark({ size = 28, className = '', title }) {
  const id = `mars-${size}`
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
        <linearGradient id={`${id}-planet`} x1="7" y1="6" x2="24" y2="27"
                        gradientUnits="userSpaceOnUse">
          <stop stopColor="#fb923c" />
          <stop offset="0.55" stopColor="#ea580c" />
          <stop offset="1" stopColor="#9a3412" />
        </linearGradient>
        <linearGradient id={`${id}-ring`} x1="2" y1="22" x2="30" y2="10"
                        gradientUnits="userSpaceOnUse">
          <stop stopColor="#f97316" />
          <stop offset="0.5" stopColor="#fdba74" />
          <stop offset="1" stopColor="#ea580c" />
        </linearGradient>
        {/* The ring passes behind the planet; this hides the half that should be
            occluded without needing a second, hand-traced path. */}
        <mask id={`${id}-behind`}>
          <rect width="32" height="32" fill="white" />
          <circle cx="15" cy="15" r="9.6" fill="black" />
        </mask>
      </defs>

      {/* Ring, back half */}
      <g mask={`url(#${id}-behind)`}>
        <ellipse
          cx="16" cy="17" rx="14.4" ry="5.2"
          transform="rotate(-24 16 17)"
          stroke={`url(#${id}-ring)`} strokeWidth="2.1" strokeLinecap="round"
        />
      </g>

      {/* Planet */}
      <circle cx="15" cy="15" r="9" fill={`url(#${id}-planet)`} />
      {/* Two soft craters. Enough to read as a surface, not enough to become detail. */}
      <circle cx="11.6" cy="12.2" r="2.1" fill="#7c2d12" opacity="0.26" />
      <circle cx="17.6" cy="17.9" r="1.4" fill="#7c2d12" opacity="0.22" />

      {/* Ring, front half: the arc that crosses in front, plus the data squares. */}
      <path
        d="M4.1 22.4C7.6 24.4 13.2 24.6 18.8 22.6"
        stroke={`url(#${id}-ring)`} strokeWidth="2.1" strokeLinecap="round"
      />
      <rect x="24.2" y="8.1" width="2.9" height="2.9" rx="0.7"
            transform="rotate(-24 24.2 8.1)" fill="#fb923c" />
      <rect x="4.6" y="20.9" width="2.4" height="2.4" rx="0.6"
            transform="rotate(-24 4.6 20.9)" fill="#fdba74" />
    </svg>
  )
}
