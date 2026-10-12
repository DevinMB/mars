/** A job's tags as small chips; clicking one filters by it, when onPick is given. */
export default function TagChips({ tags, active, onPick, className = '' }) {
  if (!tags || tags.length === 0) return null
  return (
    <span className={`inline-flex flex-wrap gap-1 ${className}`}>
      {tags.map((t) => {
        const on = t === active
        const look = `text-[11px] leading-4 rounded-sm px-1.5 ${on
          ? 'bg-accent-100 text-accent-800' : 'bg-slate-100 text-slate-600'}`
        return onPick
          ? <button key={t} type="button" className={`${look} hover:bg-slate-200`} title={`Show jobs tagged ${t}`}
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); onPick(t) }}>{t}</button>
          : <span key={t} className={look}>{t}</span>
      })}
    </span>
  )
}
