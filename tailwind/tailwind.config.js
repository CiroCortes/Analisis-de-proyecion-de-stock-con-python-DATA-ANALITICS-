// Tailwind compilado localmente (antes: cdn.tailwindcss.com, bloqueado en la red de Pesco el 28-oct).
// Regenerar tras agregar clases nuevas: ver tailwind/README.md
module.exports = {
  content: ['./templates/**/*.html', './apps/**/*.py', './static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        pesco: {
          cyan: '#0099DE',
          darkcyan: '#007BB8',
          lightcyan: '#E6F4FC',
          red: '#D32F2F',
          dark: '#0A0A0A',
          slate: '#1E293B'
        }
      }
    }
  }
}
