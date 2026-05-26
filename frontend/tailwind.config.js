/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: '#0d9488',
          dark: '#0f766e',
        },
        app: {
          bg: '#eef1f7',
          surface: '#ffffff',
          surface2: '#e4e9f2',
          border: '#c9d4e5',
          text: '#1e293b',
          muted: '#64748b',
        },
      },
      boxShadow: {
        card: '0 4px 24px rgba(15, 23, 42, 0.08)',
      },
      borderRadius: {
        card: '10px',
      },
    },
  },
  plugins: [],
}
