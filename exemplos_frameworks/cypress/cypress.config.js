const { defineConfig } = require('cypress');

module.exports = defineConfig({
  e2e: { supportFile: 'cypress/support/e2e.js', specPattern: 'cypress/e2e/**/*.cy.js' },
  reporter: 'junit', reporterOptions: { mochaFile: 'resultados/junit-[hash].xml' },
});
