/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // The neutral scale is theme-aware. Every page here already used slate
        // consistently for text, borders and surfaces, so redefining the scale
        // itself flips the whole console -- rather than editing 393 class names
        // and getting three of them wrong.
        slate: {
          50: 'rgb(var(--s-50) / <alpha-value>)',
          100: 'rgb(var(--s-100) / <alpha-value>)',
          200: 'rgb(var(--s-200) / <alpha-value>)',
          300: 'rgb(var(--s-300) / <alpha-value>)',
          400: 'rgb(var(--s-400) / <alpha-value>)',
          500: 'rgb(var(--s-500) / <alpha-value>)',
          600: 'rgb(var(--s-600) / <alpha-value>)',
          700: 'rgb(var(--s-700) / <alpha-value>)',
          800: 'rgb(var(--s-800) / <alpha-value>)',
          900: 'rgb(var(--s-900) / <alpha-value>)',
        },
        // Cards and inputs. Was bg-white, which cannot be themed.
        surface: 'rgb(var(--surface) / <alpha-value>)',
        // Deliberately dark in both themes: code blocks and the editor gutter
        // read as dark surfaces on purpose, and inverting them would be wrong.
        code: {
          bg: 'rgb(var(--code-bg) / <alpha-value>)',
          fg: 'rgb(var(--code-fg) / <alpha-value>)',
        },
        // Tints behind alerts and pills. Only the steps actually used are
        // themed; the mid-range (500, 600) is the same ink on both grounds.
        red: {
          50: 'rgb(var(--red-50) / <alpha-value>)',
          200: 'rgb(var(--red-200) / <alpha-value>)',
          300: 'rgb(var(--red-300) / <alpha-value>)',
          500: '#ef4444',
          600: 'rgb(var(--red-600) / <alpha-value>)',
          700: 'rgb(var(--red-700) / <alpha-value>)',
          800: 'rgb(var(--red-800) / <alpha-value>)',
          900: 'rgb(var(--red-900) / <alpha-value>)',
        },
        amber: {
          50: 'rgb(var(--amber-50) / <alpha-value>)',
          200: 'rgb(var(--amber-200) / <alpha-value>)',
          500: '#f59e0b',
          700: 'rgb(var(--amber-700) / <alpha-value>)',
          800: 'rgb(var(--amber-800) / <alpha-value>)',
          900: 'rgb(var(--amber-900) / <alpha-value>)',
        },
        emerald: {
          50: 'rgb(var(--emerald-50) / <alpha-value>)',
          200: 'rgb(var(--emerald-200) / <alpha-value>)',
          500: '#10b981',
          700: 'rgb(var(--emerald-700) / <alpha-value>)',
          900: 'rgb(var(--emerald-900) / <alpha-value>)',
        },
        // One blue scale, defined once. Everything accent-coloured refers here.
        // One brand scale, taken from the logo. There used to be a blue for
        // actions and an orange for identity, on the theory that they would not
        // compete -- in practice a saturated blue button in an otherwise orange
        // and neutral interface is the loudest thing on the page. Orange carries
        // both jobs now, and everything else is slate.
        accent: {
          50: 'rgb(var(--accent-50) / <alpha-value>)',
          100: '#ffedd5',
          200: '#fed7aa',
          300: '#fdba74',
          400: '#fb923c',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
        },
        brand: {
          50: 'rgb(var(--brand-50) / <alpha-value>)',
          100: '#ffedd5',
          200: '#fed7aa',
          300: '#fdba74',
          400: '#fb923c',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        // Deliberately soft: the design leans on hairline borders, not shadows.
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
      },
    },
  },
  plugins: [],
}
