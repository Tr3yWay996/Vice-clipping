import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react-swc';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['ui-src/**/*.test.{ts,tsx}'],
    setupFiles: ['ui-src/test/setup.ts'],
  },
});
