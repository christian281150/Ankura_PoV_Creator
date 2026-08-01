import type { Config } from 'tailwindcss';

/**
 * Design direction: "audit workpaper".
 * The subject is the German commercial register and the Bundesanzeiger filing —
 * dense, typed, footnoted documents. The UI borrows their vernacular: hairline
 * rules, tabular numerals, marginalia, no rounded corners above 2px, no shadows.
 * Every figure is auditable, so every figure is set in tabular mono.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: { DEFAULT: '#F7F8F7', sunk: '#EFF1F0', raised: '#FFFFFF' },
        ink: { DEFAULT: '#12211E', 2: '#43524E', 3: '#77837F', 4: '#A8B1AE' },
        rule: { DEFAULT: '#D5DBD9', hair: '#E6EAE8' },
        pine: { DEFAULT: '#0E3B37', 600: '#2E7D6F', 100: '#E7F1EE' },
        amber: { DEFAULT: '#8A6410', 600: '#A8791C', 100: '#FBF3DF' },
        rust: { DEFAULT: '#8E3521', 600: '#A8412B', 100: '#FAECE8' },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        micro: ['10px', { lineHeight: '14px', letterSpacing: '0.06em' }],
        xs: ['11px', { lineHeight: '16px' }],
        sm: ['12.5px', { lineHeight: '18px' }],
        base: ['14px', { lineHeight: '21px' }],
        lg: ['17px', { lineHeight: '24px' }],
        xl: ['22px', { lineHeight: '28px', letterSpacing: '-0.01em' }],
      },
      borderRadius: { DEFAULT: '2px', sm: '1px', md: '2px', lg: '3px' },
      spacing: { 4.5: '1.125rem', 18: '4.5rem' },
    },
  },
  plugins: [],
} satisfies Config;
