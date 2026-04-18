const typographyPlugin = require('@tailwindcss/typography')
const formsPlugin = require('@tailwindcss/forms')
const aspectRatioPlugin = require('@tailwindcss/aspect-ratio')
const colors = require('tailwindcss/colors')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/**/*.py',
    './app/static/**/*.js',
  ],
  safelist: [
    'snap-x',
    'snap-mandatory',
    'snap-start',
    'scroll-smooth',
    'overflow-x-auto',
    // Discussion card topic colours (set dynamically via Jinja2 namespace)
    { pattern: /^border-(emerald|green|blue|purple|yellow|red|orange|gray|indigo|teal|pink|slate)-500$/ },
    { pattern: /^bg-(emerald|green|blue|purple|yellow|red|orange|gray|indigo|teal|pink|slate)-(100|600)$/ },
    { pattern: /^text-(emerald|green|blue|purple|yellow|red|orange|gray|indigo|teal|pink|slate)-800$/ },
    { pattern: /^bg-(emerald|green|blue|purple|yellow|red|orange|gray|indigo|teal|pink|slate)-700$/, variants: ['hover'] },
  ],
  darkMode: 'class',
  theme: {
    extend: {
      /** Single marketing primary — maps to blue; use bg-primary-600, text-primary-600, etc. */
      colors: {
        primary: colors.blue,
      },
      typography: require('./typography'),  // This links to our simplified typography
      minHeight: {
        '11': '2.75rem', // 44px - mobile touch target minimum
      },
      minWidth: {
        '11': '2.75rem', // 44px - mobile touch target minimum
      },
    }
  },
  plugins: [
    typographyPlugin,
    formsPlugin,
    aspectRatioPlugin,
  ],
}