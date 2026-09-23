// Dev-server overlay for the gb10.zhuopu.net deployment: adds the domain to
// Vite's host allowlist (there is no CLI flag for it) and binds all interfaces
// so the webproxy container network can reach it via the bridge gateway IP.
// See docs/guides/linux-server-ops.md; on another host, edit allowedHosts.
import { defineConfig } from 'vite'
import baseConfig from './vite.config'

const base = baseConfig as unknown as Record<string, unknown>

export default defineConfig({
  ...base,
  server: {
    ...(base.server as Record<string, unknown>),
    host: '0.0.0.0',
    allowedHosts: ['kiro-dev.gb10.zhuopu.net'],
  },
})
