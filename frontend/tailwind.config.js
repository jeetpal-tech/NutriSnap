/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#F5F2E9',
        surface: '#FFFDF7',
        ink: '#171717',
        muted: '#6B665F',
        lime: '#C9F25D',
        yellow: '#FFE269',
        lavender: '#DCD4FF',
        coral: '#FF8D82',
      },
      maxWidth: { content: '1180px' },
    },
  },
  plugins: [],
}
