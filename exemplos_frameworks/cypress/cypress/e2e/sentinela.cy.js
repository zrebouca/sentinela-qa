// Gerado pelo Sentinela QA a partir do roteiro: web_site_treino.yaml
// Rodar: npm install && npx cypress run

describe('Loja Treino (site local)', () => {
  it('CT01 - Login com usuário válido', () => {
    cy.visit("http://127.0.0.1:8000/index.html");
    cy.campoPorRotulo("Usuário").clear().type("qa");
    cy.campoPorRotulo("Senha").clear().type((process.env.TREINO_SENHA ?? "treino123"), { log: false });
    cy.campo("Entrar").click();
    cy.url().should('include', "painel.html");
    cy.contains("Bem-vindo, qa!").should('be.visible');
  });

  it('CT02 - Login com senha errada', () => {
    cy.visit("http://127.0.0.1:8000/index.html");
    cy.campoPorRotulo("Usuário").clear().type("qa");
    cy.campoPorRotulo("Senha").clear().type("errada");
    cy.campoPorRotulo("Senha").type('{enter}');
    cy.contains("Usuário ou senha inválidos.").should('be.visible');
    cy.url().should('include', "index.html");
  });

  it('CT03 - Login com campos vazios', () => {
    cy.visit("http://127.0.0.1:8000/index.html");
    cy.campo("Entrar").click();
    cy.contains("Preencha usuário e senha.").should('be.visible');
  });

  it('CT04 - Buscar produto e carregar ofertas', () => {
    cy.visit("http://127.0.0.1:8000/index.html");
    cy.get("#usuario").first().clear().type("qa");
    cy.get("#senha").first().clear().type((process.env.TREINO_SENHA ?? "treino123"), { log: false });
    cy.get("#entrar").first().click();
    cy.get(`[placeholder="${"Buscar produto"}"]`).clear().type("mochila" + '{enter}');
    cy.contains("Mochila escolar").should('be.visible');
    cy.get("#lista li").first().should('be.visible');
    cy.campo("Carregar ofertas").click();
    cy.contains("3 ofertas disponíveis hoje!").should('be.visible');
    cy.contains("Carregando...").should('not.exist');
  });

  it('CT05 - Cadastro com dados válidos (Faker pt_BR)', () => {
    cy.visit("http://127.0.0.1:8000/cadastro.html");
    cy.campoPorRotulo("Nome completo").clear().type("Marina Lopes");
    cy.campoPorRotulo("E-mail").clear().type("diasdanilo@example.net");
    cy.campoPorRotulo("CPF").clear().type("603.961.272-07");
    cy.campoPorRotulo("CEP").clear().type("24368518");
    cy.campoPorRotulo("Telefone").clear().type("93 91218-1465");
    cy.campo("Salvar cadastro").click();
    cy.url().should('include', "sucesso.html");
    cy.contains("Cadastro realizado com sucesso!").should('be.visible');
  });

  it('CT06 - Cadastro com CPF inválido', () => {
    cy.visit("http://127.0.0.1:8000/cadastro.html");
    cy.get("#nome").first().clear().type("Juliana Fernandes");
    cy.get("#email").first().clear().type("ana-liz92@example.net");
    cy.get("#cpf").first().clear().type("111.111.111-11");
    cy.get("#cep").first().clear().type("60963-125");
    cy.get("#salvar").first().click();
    cy.get("#erro-cpf").first().should('contain.text', "CPF inválido.");
    cy.url().should('include', "cadastro.html");
  });

});
