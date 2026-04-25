import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function inNodeModule(id, pkg) {
  return id.includes(`/node_modules/${pkg}/`)
}

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (inNodeModule(id, 'three/examples')) {
            return 'three-extras'
          }
          if (inNodeModule(id, 'three')) {
            return 'three-core'
          }
          if (
            [
              'react-force-graph-3d',
              '3d-force-graph',
              'three-forcegraph',
              'three-render-objects',
              'three-spritetext',
            ].some(pkg => inNodeModule(id, pkg))
          ) {
            return 'force-graph'
          }
          if (
            [
              'kapsule',
              'react-kapsule',
              'lodash-es',
              'accessor-fn',
              'float-tooltip',
              'prop-types',
            ].some(pkg => inNodeModule(id, pkg))
          ) {
            return 'graph-runtime'
          }
        },
      },
    },
  },
})
