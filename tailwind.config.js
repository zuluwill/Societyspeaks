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
    }
  },
  plugins: [
    typographyPlugin,
    formsPlugin,
    aspectRatioPlugin,
  ],
}