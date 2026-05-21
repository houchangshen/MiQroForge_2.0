import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'MF_')

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: parseInt(env.MF_UI_PORT) || 5273,
      proxy: {
        '/api': {
          target: `http://localhost:${env.MF_API_PORT || '8200'}`,
          changeOrigin: true,
        },
      },
    },
  }
})
