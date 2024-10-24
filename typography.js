module.exports = {
  DEFAULT: {
    css: {
      maxWidth: '65ch',
      color: '#334155', // slate-700
      p: {
        marginTop: '1.25em',
        marginBottom: '1.25em',
      },
      'h1, h2, h3': {
        color: '#0f172a', // slate-900
        fontWeight: '700',
      },
      h1: {
        fontSize: '2.25em',
        marginBottom: '1em',
      },
      h2: {
        fontSize: '1.5em',
        marginTop: '2em',
        marginBottom: '1em',
      },
      h3: {
        fontSize: '1.25em',
        marginTop: '1.6em',
        marginBottom: '0.6em',
      },
      a: {
        color: '#2563eb', // blue-600
        textDecoration: 'underline',
        '&:hover': {
          color: '#1d4ed8', // blue-700
        },
      },
      'ul, ol': {
        paddingLeft: '1.25em',
      },
      li: {
        marginTop: '0.5em',
        marginBottom: '0.5em',
      },
      blockquote: {
        fontStyle: 'italic',
        borderLeftWidth: '4px',
        borderLeftColor: '#e2e8f0', // slate-200
        paddingLeft: '1em',
        color: '#64748b', // slate-500
      },
      code: {
        color: '#dc2626', // red-600
        '&::before': {
          content: '"`"',
        },
        '&::after': {
          content: '"`"',
        },
      },
      pre: {
        backgroundColor: '#1e293b', // slate-800
        color: '#e2e8f0', // slate-200
        padding: '1em',
        borderRadius: '0.375rem',
        overflowX: 'auto',
      },
      'pre code': {
        color: 'inherit',
        '&::before': {
          content: '""',
        },
        '&::after': {
          content: '""',
        },
      },
      img: {
        marginTop: '2em',
        marginBottom: '2em',
        borderRadius: '0.375rem',
      },
      hr: {
        borderColor: '#e2e8f0', // slate-200
        marginTop: '2em',
        marginBottom: '2em',
      }
    }
  }
}