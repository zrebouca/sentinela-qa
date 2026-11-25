import { defineConfig } from '@playwright/test';

// Usa o Google Chrome instalado (não precisa baixar navegadores)
export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  use: { channel: 'chrome', headless: true, locale: 'pt-BR' },
  reporter: [['list'], ['junit', { outputFile: 'resultados/junit.xml' }]],
});
