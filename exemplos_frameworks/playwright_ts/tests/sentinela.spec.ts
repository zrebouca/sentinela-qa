import { test, expect } from '@playwright/test';

// Gerado pelo Sentinela QA a partir do roteiro: web_site_treino.yaml
// Rodar: npm install && npx playwright test

/** Procura um campo como uma pessoa faria, NESTA ordem: rótulo, placeholder, botão, link, texto. */
async function campo(page, texto) {
  const candidatos = [page.getByLabel(texto), page.getByPlaceholder(texto), page.getByRole('button', { name: texto }),
    page.getByRole('link', { name: texto }), page.getByText(texto, { exact: true })];
  for (const c of candidatos) if (await c.count()) return c.first();
  return candidatos.reduce((a, b) => a.or(b)).first();   // ainda não apareceu: o Playwright espera
}

test.describe('Loja Treino (site local)', () => {
  test('CT01 - Login com usuário válido', async ({ page, request }) => {
    let resposta; let json;
    await page.goto("http://127.0.0.1:8000/index.html");
    await page.getByLabel("Usuário").first().fill("qa");
    await page.getByLabel("Senha").first().fill((process.env.TREINO_SENHA ?? "treino123"));
    await (await campo(page, "Entrar")).click();
    await expect(page).toHaveURL(new RegExp("painel\\.html"));
    await expect(page.getByText("Bem-vindo, qa!").first()).toBeVisible();
  });

  test('CT02 - Login com senha errada', async ({ page, request }) => {
    let resposta; let json;
    await page.goto("http://127.0.0.1:8000/index.html");
    await page.getByLabel("Usuário").first().fill("qa");
    await page.getByLabel("Senha").first().fill("errada");
    await page.getByLabel("Senha").first().press('Enter');
    await expect(page.getByText("Usuário ou senha inválidos.").first()).toBeVisible();
    await expect(page).toHaveURL(new RegExp("index\\.html"));
  });

  test('CT03 - Login com campos vazios', async ({ page, request }) => {
    let resposta; let json;
    await page.goto("http://127.0.0.1:8000/index.html");
    await (await campo(page, "Entrar")).click();
    await expect(page.getByText("Preencha usuário e senha.").first()).toBeVisible();
  });

  test('CT04 - Buscar produto e carregar ofertas', async ({ page, request }) => {
    let resposta; let json;
    await page.goto("http://127.0.0.1:8000/index.html");
    await page.locator("#usuario").first().fill("qa");
    await page.locator("#senha").first().fill((process.env.TREINO_SENHA ?? "treino123"));
    await page.locator("#entrar").first().click();
    await page.getByPlaceholder("Buscar produto").first().fill("mochila");
    await page.getByPlaceholder("Buscar produto").first().press('Enter');
    await expect(page.getByText("Mochila escolar").first()).toBeVisible();
    await expect(page.locator("#lista li:visible").first()).toBeVisible();
    await (await campo(page, "Carregar ofertas")).click();
    await page.getByText("3 ofertas disponíveis hoje!").first().waitFor();
    await expect(page.getByText("Carregando...").filter({ visible: true })).toHaveCount(0);
  });

  test('CT05 - Cadastro com dados válidos (Faker pt_BR)', async ({ page, request }) => {
    let resposta; let json;
    await page.goto("http://127.0.0.1:8000/cadastro.html");
    await page.getByLabel("Nome completo").first().fill("Otávio Cardoso");
    await page.getByLabel("E-mail").first().fill("nunesmariane@example.org");
    await page.getByLabel("CPF").first().fill("122.734.143-15");
    await page.getByLabel("CEP").first().fill("85484-034");
    await page.getByLabel("Telefone").first().fill("+55 88 91880-7440");
    await (await campo(page, "Salvar cadastro")).click();
    await expect(page).toHaveURL(new RegExp("sucesso\\.html"));
    await expect(page.getByText("Cadastro realizado com sucesso!").first()).toBeVisible();
  });

  test('CT06 - Cadastro com CPF inválido', async ({ page, request }) => {
    let resposta; let json;
    await page.goto("http://127.0.0.1:8000/cadastro.html");
    await page.locator("#nome").first().fill("Ester Sales");
    await page.locator("#email").first().fill("lais82@example.net");
    await page.locator("#cpf").first().fill("111.111.111-11");
    await page.locator("#cep").first().fill("26720270");
    await page.locator("#salvar").first().click();
    await expect(page.locator("#erro-cpf").first()).toContainText("CPF inválido.");
    await expect(page).toHaveURL(new RegExp("cadastro\\.html"));
  });

});
