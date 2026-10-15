import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_BACKEND_URL || process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

  return {
    root: '.',
    publicDir: false,
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/api': backendTarget,
        '/stream': backendTarget,
        '/frames': backendTarget
      }
    }
  }
})