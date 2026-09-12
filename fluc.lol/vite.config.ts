import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  // build: {
  //   rollupOptions: {
  //     output: {
  //       entryFileNames: 'chunk/[name].js',
  //       chunkFileNames: 'chunk/[name].js',
  //       // chunkFileNames: 'chunk/[name]-[hash].js',
  //       assetFileNames: 'assets/[name].[ext]'
  //     }
  //   }
  // }
})
