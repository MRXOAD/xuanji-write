import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const NODE_MODULES_RE = String.raw`[\\/]node_modules[\\/]`

function packageGroupRE(packages) {
  const pattern = packages
    .map(pkg => pkg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace('/', String.raw`[\\/]`))
    .join('|')
  return new RegExp(`${NODE_MODULES_RE}(?:${pattern})(?:[\\/]|$)`)
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
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'react-vendor',
              test: packageGroupRE(['react', 'react-dom', 'scheduler']),
              priority: 30,
            },
            {
              name: 'three-vendor',
              test: packageGroupRE(['three']),
              priority: 25,
            },
            {
              name: 'graph-vendor',
              test: packageGroupRE([
                'react-force-graph-3d',
                '3d-force-graph',
                'three-forcegraph',
                'three-render-objects',
                'three-spritetext',
                '@tweenjs/tween.js',
                'accessor-fn',
                'data-bind-mapper',
                'd3-array',
                'd3-binarytree',
                'd3-color',
                'd3-dispatch',
                'd3-force-3d',
                'd3-format',
                'd3-interpolate',
                'd3-octree',
                'd3-quadtree',
                'd3-scale',
                'd3-scale-chromatic',
                'd3-selection',
                'd3-time',
                'd3-time-format',
                'd3-timer',
                'float-tooltip',
                'jerrypick',
                'kapsule',
                'lodash-es',
                'ngraph.events',
                'ngraph.forcelayout',
                'ngraph.graph',
                'ngraph.merge',
                'ngraph.random',
                'polished',
                'preact',
                'prop-types',
                'react-is',
                'react-kapsule',
                'tinycolor2',
              ]),
              priority: 20,
            },
          ],
        },
      },
    },
  },
})
