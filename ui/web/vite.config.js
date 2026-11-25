import react from '@vitejs/plugin-react'
export default { plugins: [react()], base: './', build: { outDir: '../dist', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } } }
