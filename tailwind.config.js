const typographyPlugin = require('@tailwindcss/typography')
const formsPlugin = require('@tailwindcss/forms')
const aspectRatioPlugin = require('@tailwindcss/aspect-ratio')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/**/*.py',
    './app/static/**/*.js',
  ],
  darkMode: 'class',
  theme: {
    extend: {
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