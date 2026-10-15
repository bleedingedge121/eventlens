import { defineConfig } from 'vite'

export default defineConfig({
  root: '.',
  publicDir: false,
  build: {
    outDir: '../backend/server/static',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: 'index.html',
        chat: 'chat.html'
      }
    },
    minify: 'esbuild',
    cssCodeSplit: true
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/stream': 'http://127.0.0.1:8000',
      '/frames': 'http://127.0.0.1:8000'
    }
  }
})