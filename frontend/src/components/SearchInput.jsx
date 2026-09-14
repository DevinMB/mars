// A compact filter box for lists that grow. Deliberately plain: it sits inside
// panels and should read as part of the surface, not as a separate control.
export default function SearchInput({ value, onChange, placeholder = 'Filter…', count }) {
  return (
    <div className="relative">
      <svg
        className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none"
        viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2"
        aria-hidden="true"
      >
        <circle cx="9" cy="9" r="6" />
        <path d="M14 14l4 4" strokeLinecap="round" />
      </svg>
      <input
        className="input pl-8 pr-14 py-1.5 text-[13px]"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400
                     hover:text-slate-700 px-1"
          aria-label="Clear filter"
        >
          clear
        </button>
      ) : count != null ? (
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px]
                         tabular-nums text-slate-400">
          {count}
        </span>
      ) : null}
    </div>
  )
}
