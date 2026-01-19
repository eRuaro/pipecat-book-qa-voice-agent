/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        camb: {
          bg: '#0f0f0f',
          card: '#1a1a1a',
          border: '#2a2a2a',
          orange: '#E8784A',
          'orange-hover': '#d66a3f',
          'orange-light': '#f5a67a',
        }
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
