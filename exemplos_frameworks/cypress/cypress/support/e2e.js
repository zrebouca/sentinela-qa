// Comandos de apoio para achar campos como uma pessoa faria (gerado pelo Sentinela QA)
Cypress.Commands.add('campoPorRotulo', (texto) =>
  cy.contains('label', texto).invoke('attr', 'for').then((id) => cy.get(`#${id}`)));

Cypress.Commands.add('campo', (texto) =>
  cy.get('body').then(($b) => {
    const label = [...$b.find('label')].find((l) => l.innerText.trim() === texto);
    if (label && label.htmlFor) return cy.get(`#${label.htmlFor}`);
    if ($b.find(`[placeholder="${texto}"]`).length) return cy.get(`[placeholder="${texto}"]`).first();
    return cy.contains('button, a, input[type=submit], *', texto).first();
  }));
