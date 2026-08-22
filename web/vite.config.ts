import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const devAllowedHosts = process.env.AUDELLE_VITE_ALLOWED_HOSTS?.split(',').map((host) => host.trim()).filter(Boolean)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    // Dev-only host allowlisting. Never use the broad `true` setting: a Vite
    // server exposed on a network interface must not accept arbitrary Host
    // headers (DNS-rebinding/host-header abuse). Set AUDELLE_VITE_ALLOWED_HOSTS
    // for a private preview hostname when needed.
    ...(devAllowedHosts?.length ? { allowedHosts: devAllowedHosts } : {}),
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
