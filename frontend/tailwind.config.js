/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: { extend: {
    colors: { page:'#F7F8F6', surface:'#FFFFFF', ink:'#1B1F1D', muted:'#5F6B66', line:'#E2E6E3', primary:'#2E7D32', 'primary-soft':'#E8F5E9', warning:'#995A00', 'warning-soft':'#FFF4E0', danger:'#C62828', 'danger-soft':'#FDECEA' },
    maxWidth: { content:'1100px' }, boxShadow:{ card:'0 8px 24px rgba(27,31,29,.04)' }
  }}, plugins: []
}
