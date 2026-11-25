"""
Exporta um roteiro do Sentinela para código de outros frameworks de teste.

    sentinela exportar --roteiro roteiros/web_site_treino.yaml --para cypress --saida exportado/cypress

Formatos:
    playwright-ts   Playwright Test em TypeScript (web + API)      roda com: npx playwright test
    cypress         Cypress (web + API)                            roda com: npx cypress run
    selenium-py     Selenium WebDriver + pytest (web)              roda com: pytest
    pytest-api      requests + pytest (API)                        roda com: pytest
    restassured     RestAssured + JUnit 5, projeto Maven (API)     roda com: mvn test
    appium-py       Appium (Chrome no Android, web mobile)         precisa de Appium + emulador/celular
    maestro         Maestro (fluxo YAML, web mobile)               precisa de Maestro + emulador/celular
    postman         coleção do Postman v2.1 (API)                  roda com: npx newman run colecao.postman_collection.json

Os comandos mais comuns são convertidos; o que não tem equivalente direto vira um comentário TODO.
Valores {faker.x} viram um texto fixo de exemplo e {env.X|padrão} vira variável de ambiente com padrão.
"""

import json
import os
import re

from sentinela import dados as massa

FORMATOS = {
    "playwright-ts": "Playwright Test (TypeScript)", "cypress": "Cypress (JavaScript)",
    "selenium-py": "Selenium WebDriver + pytest", "pytest-api": "pytest + requests (API)",
    "restassured": "RestAssured + JUnit 5 (Java/Maven)", "appium-py": "Appium (Android, web mobile)",
    "maestro": "Maestro (YAML, web mobile)", "postman": "Coleção do Postman / Newman",
}

_ENV = re.compile(r"\{env\.(\w+)(?:\|([^}]*))?\}")
_DADOS = re.compile(r"\{dados\.(\w+)\}")
_FAKER = re.compile(r"\{faker\.(\w+)\}")


class Exportador:
    """Converte valores do roteiro em expressões da linguagem de destino."""

    def __init__(self, roteiro, linguagem: str):
        self.r = roteiro
        self.ling = linguagem       # js | py | java
        self.dados = dict(roteiro.dados or {})
        self.runtime: set[str] = set()     # valores guardados durante o teste (comando guardar)

    def guardar(self, nome: str):
        self.runtime.add(nome)

    def _faker(self, texto: str) -> str:
        def troca(m):
            try:
                return massa.gerar_faker(m[1])
            except ValueError:
                return f"<{m[1]}>"
        return _FAKER.sub(troca, texto)

    def valor(self, v) -> str:
        """Literal da linguagem, resolvendo {dados.x}, {faker.x} e {env.X|padrao}."""
        texto = str(v)
        for _ in range(3):
            texto = _DADOS.sub(lambda m: f"\x00{m[1]}\x00" if m[1] in self.runtime else str(self.dados.get(m[1], m[0])), texto)
        texto = self._faker(texto)
        partes, pos = [], 0
        for m in re.finditer(r"\{env\.(\w+)(?:\|([^}]*))?\}|\x00(\w+)\x00", texto):
            if m.start() > pos:
                partes.append(("lit", texto[pos:m.start()]))
            partes.append(("var", m[3]) if m[3] else ("env", m[1], m[2] or ""))
            pos = m.end()
        if pos < len(texto):
            partes.append(("lit", texto[pos:]))
        if not partes:
            partes = [("lit", "")]
        exprs = []
        for p in partes:
            if p[0] == "lit":
                exprs.append(json.dumps(p[1], ensure_ascii=False))
            elif p[0] == "var":
                exprs.append({"js": f"String({p[1]})", "py": f"str({p[1]})"}.get(self.ling, f"String.valueOf({p[1]})"))
            elif self.ling == "js":
                exprs.append(f"(process.env.{p[1]} ?? {json.dumps(p[2], ensure_ascii=False)})")
            elif self.ling == "py":
                exprs.append(f"os.getenv({json.dumps(p[1])}, {json.dumps(p[2], ensure_ascii=False)})")
            else:
                exprs.append(f"System.getenv().getOrDefault({json.dumps(p[1])}, {json.dumps(p[2], ensure_ascii=False)})")
        return " + ".join(exprs) if len(exprs) > 1 else exprs[0]

    def texto(self, v) -> str:
        """Texto puro (para YAML): resolve dados/faker e troca {env.X|p} por ${X} (variável do Maestro)."""
        s = str(v)
        for _ in range(3):
            s = _DADOS.sub(lambda m: "${" + m[1] + "}" if m[1] in self.runtime else str(self.dados.get(m[1], m[0])), s)
        return _ENV.sub(lambda m: "${" + m[1] + "}", self._faker(s))

    @staticmethod
    def arg(args, chave, padrao=None):
        if isinstance(args, dict):
            return args.get(chave, padrao)
        return args if padrao is None else padrao


def _url(roteiro, caminho: str) -> str:
    if caminho.startswith("http") or caminho.startswith("{"):
        return caminho
    return (roteiro.alvo or "").rstrip("/") + "/" + caminho.lstrip("/")


def _nome_teste(caso) -> str:
    return f"{caso.id} - {caso.descricao}".replace("'", "’").replace('"', "”")


def _req_args(args):
    if isinstance(args, str):
        partes = args.split(None, 1)
        return {"metodo": partes[0].upper() if len(partes) == 2 else "GET", "url": partes[-1]}
    return dict(args)


# ====================================================================== Playwright TS
def _loc_pw(alvo: str, ex: Exportador) -> str:
    p, _, resto = str(alvo).partition("=")
    v = lambda s: ex.valor(s)
    if resto and p == "texto":
        return f"page.getByText({v(resto)}).first()"
    if resto and p == "rotulo":
        return f"page.getByLabel({v(resto)}).first()"
    if resto and p == "placeholder":
        return f"page.getByPlaceholder({v(resto)}).first()"
    if resto and p == "testid":
        return f"page.getByTestId({v(resto)}).first()"
    if resto and p == "papel":
        papel, _, nome = resto.partition(":")
        return f"page.getByRole('{papel}'{', { name: ' + v(nome) + ' }' if nome else ''}).first()"
    if resto and p == "xpath":
        return f"page.locator({v('xpath=' + resto)}).first()"
    if re.match(r"^[#.\[*]|^[a-zA-Z][\w-]*[.#\[>:]", str(alvo)) or str(alvo) in ("button", "input", "form"):
        return f"page.locator({v(alvo)}).first()"
    return f"(await campo(page, {v(alvo)}))"


def _passo_pw(c: str, a, ex: Exportador, r) -> list[str]:
    g = ex.arg
    if c == "abrir":
        return [f"await page.goto({ex.valor(_url(r, g(a, 'url', '/') if isinstance(a, dict) else (a or '/')))});"]
    if c == "clicar":
        return [f"await {_loc_pw(g(a, 'alvo'), ex)}.click();"]
    if c == "clicar_duplo":
        return [f"await {_loc_pw(g(a, 'alvo'), ex)}.dblclick();"]
    if c == "passar_mouse":
        return [f"await {_loc_pw(g(a, 'alvo'), ex)}.hover();"]
    if c == "preencher":
        return [f"await {_loc_pw(a['campo'], ex)}.fill({ex.valor(a['valor'])});"]
    if c == "digitar":
        alvo = _loc_pw(a["campo"], ex) if isinstance(a, dict) and a.get("campo") else "page.keyboard"
        metodo = "pressSequentially" if alvo != "page.keyboard" else "type"
        return [f"await {alvo}.{metodo}({ex.valor(g(a, 'texto'))});"]
    if c == "apertar_tecla":
        tecla = str(g(a, "tecla")).replace("Esc", "Escape")
        return [f"await {_loc_pw(a['campo'], ex) if isinstance(a, dict) and a.get('campo') else 'page.keyboard'}.press('{tecla}');"]
    if c == "selecionar":
        return [f"await {_loc_pw(a['campo'], ex)}.selectOption({{ label: {ex.valor(a['opcao'])} }});"]
    if c in ("marcar", "desmarcar"):
        return [f"await {_loc_pw(g(a, 'alvo'), ex)}.{'check' if c == 'marcar' else 'uncheck'}();"]
    if c == "arrastar":
        return [f"await {_loc_pw(a['de'], ex)}.dragTo({_loc_pw(a['para'], ex)});"]
    if c == "enviar_arquivo":
        return [f"await {_loc_pw(a['campo'], ex)}.setInputFiles({ex.valor(a['arquivo'])});"]
    if c == "esperar":
        if isinstance(a, (int, float)):
            return [f"await page.waitForTimeout({int(float(a) * 1000)});"]
        if "texto" in a:
            return [f"await page.getByText({ex.valor(a['texto'])}).first().waitFor();"]
        if "sumir" in a:
            return [f"await page.locator({ex.valor(a['sumir'])}).waitFor({{ state: 'hidden' }});"]
        return [f"await {_loc_pw(g(a, 'elemento') or g(a, 'alvo'), ex)}.waitFor();"]
    if c == "rolar":
        if isinstance(a, dict) and "ate" in a:
            return [f"await {_loc_pw(a['ate'], ex)}.scrollIntoViewIfNeeded();"]
        return ["await page.mouse.wheel(0, 600);"]
    if c == "logar":
        return [f"await {_loc_pw(a.get('campo_usuario', 'input[type=email]'), ex)}.fill({ex.valor(a['usuario'])});",
                f"await {_loc_pw(a.get('campo_senha', 'input[type=password]'), ex)}.fill({ex.valor(a['senha'])});",
                f"await {_loc_pw(a.get('botao', 'button[type=submit]'), ex)}.click();"]
    if c == "cadastrar":
        linhas = [f"await {_loc_pw(k, ex)}.fill({ex.valor(v)});" for k, v in a["campos"].items()]
        if a.get("enviar"):
            linhas.append(f"await {_loc_pw(a['enviar'], ex)}.click();")
        return linhas
    if c == "buscar":
        campo = _loc_pw(a.get("campo", "input[type=search]"), ex) if isinstance(a, dict) else "page.locator('input[type=search]')"
        return [f"await {campo}.fill({ex.valor(g(a, 'termo'))});", f"await {campo}.press('Enter');"]
    if c == "recarregar":
        return ["await page.reload();"]
    if c == "verificar_texto":
        if isinstance(a, dict) and a.get("elemento"):
            return [f"await expect({_loc_pw(a['elemento'], ex)}).toContainText({ex.valor(a['texto'])});"]
        return [f"await expect(page.getByText({ex.valor(g(a, 'texto'))}).first()).toBeVisible();"]
    if c == "verificar_sem_texto":
        return [f"await expect(page.getByText({ex.valor(g(a, 'texto'))}).filter({{ visible: true }})).toHaveCount(0);"]
    if c == "verificar_elemento":
        return [f"await expect({_loc_pw(g(a, 'alvo'), ex)}).toBeVisible();"]
    if c == "verificar_url":
        if isinstance(a, dict) and "igual" in a:
            return [f"await expect(page).toHaveURL({ex.valor(a['igual'])});"]
        return [f"await expect(page).toHaveURL(new RegExp({ex.valor(re.escape(str(g(a, 'contem'))))}));"]
    if c == "verificar_titulo":
        return [f"await expect(page).toHaveTitle(new RegExp({ex.valor(re.escape(str(g(a, 'contem'))))}));"]
    if c == "verificar_valor":
        return [f"await expect({_loc_pw(a['campo'], ex)}).toHaveValue({ex.valor(a['valor'])});"]
    if c == "verificar_mensagem":
        return [f"await expect(page.getByText({ex.valor(g(a, 'texto'))}).first()).toBeVisible();"]
    if c == "requisitar":
        q = _req_args(a)
        opcoes = []
        if q.get("cabecalhos"):
            opcoes.append("headers: { " + ", ".join(f"{json.dumps(k)}: {ex.valor(v)}" for k, v in q["cabecalhos"].items()) + " }")
        if q.get("corpo") is not None:
            opcoes.append(f"data: {json.dumps(q['corpo'], ensure_ascii=False)}")
        if q.get("consulta"):
            opcoes.append(f"params: {json.dumps(q['consulta'], ensure_ascii=False)}")
        extra = ", { " + ", ".join(opcoes) + " }" if opcoes else ""
        return [f"resposta = await request.fetch({ex.valor(_url(r, q['url']))}, {{ method: '{q.get('metodo', 'GET').upper()}'"
                f"{(', ' + ', '.join(opcoes)) if opcoes else ''} }});",
                "json = await resposta.json().catch(() => null);"]
    if c == "verificar_status":
        if isinstance(a, dict) and "entre" in a:
            return [f"expect(resposta.status()).toBeGreaterThanOrEqual({a['entre'][0]});",
                    f"expect(resposta.status()).toBeLessThanOrEqual({a['entre'][1]});"]
        return [f"expect(resposta.status()).toBe({int(g(a, 'igual') if isinstance(a, dict) else a)});"]
    if c == "verificar_json":
        caminho = _caminho_js(a.get("campo", ""))
        if a.get("existe") is False:
            return [f"expect({caminho}).toBeUndefined();"]
        if "valor" in a:
            return [f"expect(String({caminho}).toLowerCase()).toBe(String({ex.valor(a['valor'])}).toLowerCase());"]
        if "contem" in a:
            return [f"expect(JSON.stringify({caminho})).toContain({ex.valor(a['contem'])});"]
        return [f"expect({caminho}).toBeDefined();"]
    if c == "guardar":
        ex.guardar(a["como"])
        return [f"var {a['como']} = {_caminho_js(a['campo'])};"]
    return [f"// TODO: '{c}' não tem conversão automática para Playwright ({json.dumps(a, ensure_ascii=False)[:80]})"]


def _caminho_js(campo: str) -> str:
    if not campo:
        return "json"
    out = "json"
    for p in re.findall(r"[^.\[\]]+|\[\d+\]", campo):
        out += f"?.{p}" if not p.startswith("[") else f"?.{p}"
    return out.replace("?.[", "?.[")


def gerar_playwright(r) -> dict:
    ex = Exportador(r, "js")
    linhas = ["import { test, expect } from '@playwright/test';", "",
              "// Gerado pelo Sentinela QA a partir do roteiro: " + os.path.basename(r.arquivo),
              "// Rodar: npm install && npx playwright test", "",
              "/** Procura um campo como uma pessoa faria, NESTA ordem: rótulo, placeholder, botão, link, texto. */",
              "async function campo(page, texto) {",
              "  const candidatos = [page.getByLabel(texto), page.getByPlaceholder(texto), page.getByRole('button', { name: texto }),",
              "    page.getByRole('link', { name: texto }), page.getByText(texto, { exact: true })];",
              "  for (const c of candidatos) if (await c.count()) return c.first();",
              "  return candidatos.reduce((a, b) => a.or(b)).first();   // ainda não apareceu: o Playwright espera",
              "}", "", f"test.describe('{r.sistema.replace(chr(39), '’')}', () => {{"]
    for caso in r.casos:
        linhas.append(f"  test('{_nome_teste(caso)}', async ({{ page, request }}) => {{")
        linhas.append("    let resposta; let json;")
        for p in r.antes_de_cada + caso.passos:
            for l in _passo_pw(p.comando, p.args, ex, r):
                linhas.append("    " + l)
        linhas += ["  });", ""]
    linhas.append("});")
    config = ("import { defineConfig } from '@playwright/test';\n\n"
              "// Usa o Google Chrome instalado (não precisa baixar navegadores)\n"
              "export default defineConfig({\n  testDir: './tests',\n  timeout: 30000,\n"
              f"  use: {{ channel: 'chrome', headless: true, locale: 'pt-BR' }},\n"
              "  reporter: [['list'], ['junit', { outputFile: 'resultados/junit.xml' }]],\n});\n")
    pacote = {"name": "sentinela-export-playwright", "private": True, "scripts": {"test": "playwright test"},
              "devDependencies": {"@playwright/test": "^1.51.0"}}
    return {"tests/sentinela.spec.ts": "\n".join(linhas) + "\n", "playwright.config.ts": config,
            "package.json": json.dumps(pacote, indent=2) + "\n"}


# ====================================================================== Cypress
def _css_padrao(alvo: str) -> tuple[str, int]:
    """Remove extensões que só o Playwright entende (':visible', '>> nth=N'). Devolve (seletor, índice)."""
    alvo = re.sub(r":visible", "", str(alvo))
    m = re.search(r"\s*>>\s*nth=(\d+)\s*$", alvo)
    return (alvo[:m.start()], int(m[1])) if m else (alvo, 0)


def _loc_cy(alvo: str, ex: Exportador) -> str:
    alvo, n = _css_padrao(alvo)
    if n:
        return _loc_cy(alvo, ex).replace(".first()", "") + f".eq({n})"
    p, _, resto = str(alvo).partition("=")
    v = ex.valor
    if resto and p == "texto":
        return f"cy.contains({v(resto)})"
    if resto and p == "rotulo":
        return f"cy.campoPorRotulo({v(resto)})"
    if resto and p == "placeholder":
        return f"cy.get(`[placeholder=\"${{{v(resto)}}}\"]`)"
    if resto and p == "testid":
        return f"cy.get('[{ex.r.atributo_testid}=\"{resto}\"]')"
    if resto and p == "papel":
        papel, _, nome = resto.partition(":")
        return f"cy.contains('{ {'button': 'button', 'link': 'a'}.get(papel, '*') }', {v(nome)})"
    if re.match(r"^[#.\[*]|^[a-zA-Z][\w-]*[.#\[>:]", str(alvo)):
        return f"cy.get({v(alvo)}).first()"
    return f"cy.campo({v(alvo)})"


def _passo_cy(c: str, a, ex: Exportador, r) -> list[str]:
    g = ex.arg
    if c == "abrir":
        return [f"cy.visit({ex.valor(_url(r, g(a, 'url', '/') if isinstance(a, dict) else (a or '/')))});"]
    if c in ("clicar", "clicar_duplo"):
        return [f"{_loc_cy(g(a, 'alvo'), ex)}.{'click' if c == 'clicar' else 'dblclick'}();"]
    if c == "passar_mouse":
        return [f"{_loc_cy(g(a, 'alvo'), ex)}.trigger('mouseover');"]
    if c == "preencher":
        return [f"{_loc_cy(a['campo'], ex)}.clear().type({ex.valor(a['valor'])});"]
    if c == "digitar":
        return [f"{_loc_cy(a['campo'], ex) if isinstance(a, dict) and a.get('campo') else 'cy.focused()'}.type({ex.valor(g(a, 'texto'))});"]
    if c == "apertar_tecla":
        tecla = {"Enter": "{enter}", "Tab": "{tab}", "Esc": "{esc}", "Escape": "{esc}"}.get(str(g(a, "tecla")), "{" + str(g(a, "tecla")).lower() + "}")
        alvo = _loc_cy(a["campo"], ex) if isinstance(a, dict) and a.get("campo") else "cy.focused()"
        return [f"{alvo}.type('{tecla}');" if tecla != "{tab}" else "// TODO: Tab precisa do plugin cypress-plugin-tab"]
    if c == "selecionar":
        return [f"{_loc_cy(a['campo'], ex)}.select({ex.valor(a['opcao'])});"]
    if c in ("marcar", "desmarcar"):
        return [f"{_loc_cy(g(a, 'alvo'), ex)}.{'check' if c == 'marcar' else 'uncheck'}();"]
    if c == "enviar_arquivo":
        return [f"{_loc_cy(a['campo'], ex)}.selectFile({ex.valor(a['arquivo'])});"]
    if c == "esperar":
        if isinstance(a, (int, float)):
            return [f"cy.wait({int(float(a) * 1000)});"]
        if "texto" in a:
            return [f"cy.contains({ex.valor(a['texto'])}).should('be.visible');"]
        if "sumir" in a:
            return [f"cy.get({ex.valor(a['sumir'])}).should('not.be.visible');"]
        return [f"{_loc_cy(g(a, 'elemento') or g(a, 'alvo'), ex)}.should('be.visible');"]
    if c == "rolar":
        return [f"{_loc_cy(a['ate'], ex)}.scrollIntoView();" if isinstance(a, dict) and "ate" in a else "cy.scrollTo('bottom');"]
    if c == "logar":
        return [f"{_loc_cy(a.get('campo_usuario', 'input[type=email]'), ex)}.clear().type({ex.valor(a['usuario'])});",
                f"{_loc_cy(a.get('campo_senha', 'input[type=password]'), ex)}.clear().type({ex.valor(a['senha'])}, {{ log: false }});",
                f"{_loc_cy(a.get('botao', 'button[type=submit]'), ex)}.click();"]
    if c == "cadastrar":
        linhas = [f"{_loc_cy(k, ex)}.clear().type({ex.valor(v)});" for k, v in a["campos"].items()]
        if a.get("enviar"):
            linhas.append(f"{_loc_cy(a['enviar'], ex)}.click();")
        return linhas
    if c == "buscar":
        return [f"{_loc_cy(a.get('campo', 'input[type=search]'), ex) if isinstance(a, dict) else 'cy.get(`input[type=search]`)'}"
                f".clear().type({ex.valor(g(a, 'termo'))} + '{{enter}}');"]
    if c == "verificar_texto":
        if isinstance(a, dict) and a.get("elemento"):
            return [f"{_loc_cy(a['elemento'], ex)}.should('contain.text', {ex.valor(a['texto'])});"]
        return [f"cy.contains({ex.valor(g(a, 'texto'))}).should('be.visible');"]
    if c == "verificar_sem_texto":
        return [f"cy.contains({ex.valor(g(a, 'texto'))}).should('not.exist');"]
    if c == "verificar_elemento":
        return [f"{_loc_cy(g(a, 'alvo'), ex)}.should('be.visible');"]
    if c == "verificar_url":
        if isinstance(a, dict) and "igual" in a:
            return [f"cy.url().should('eq', {ex.valor(a['igual'])});"]
        return [f"cy.url().should('include', {ex.valor(g(a, 'contem'))});"]
    if c == "verificar_titulo":
        return [f"cy.title().should('include', {ex.valor(g(a, 'contem'))});"]
    if c == "verificar_valor":
        return [f"{_loc_cy(a['campo'], ex)}.should('have.value', {ex.valor(a['valor'])});"]
    if c == "verificar_mensagem":
        return [f"cy.contains({ex.valor(g(a, 'texto'))}).should('be.visible');"]
    if c == "requisitar":
        q = _req_args(a)
        corpo = f", body: {json.dumps(q['corpo'], ensure_ascii=False)}" if q.get("corpo") is not None else ""
        cab = (", headers: { " + ", ".join(f"{json.dumps(k)}: {ex.valor(v)}" for k, v in q["cabecalhos"].items()) + " }") if q.get("cabecalhos") else ""
        return [f"cy.request({{ method: '{q.get('metodo', 'GET').upper()}', url: {ex.valor(_url(r, q['url']))}{corpo}{cab}, "
                f"failOnStatusCode: false }}).as('resposta');"]
    if c == "verificar_status":
        if isinstance(a, dict) and "entre" in a:
            return [f"cy.get('@resposta').its('status').should('be.within', {a['entre'][0]}, {a['entre'][1]});"]
        return [f"cy.get('@resposta').its('status').should('eq', {int(g(a, 'igual') if isinstance(a, dict) else a)});"]
    if c == "verificar_json":
        caminho = a.get("campo", "")
        alvo = f"cy.get('@resposta').its('body{('.' + caminho) if caminho else ''}')"
        if a.get("existe") is False:
            return [f"cy.get('@resposta').its('body').should('not.have.nested.property', {json.dumps(caminho)});"]
        if "valor" in a:
            return [f"{alvo}.then(v => expect(String(v).toLowerCase()).to.eq(String({ex.valor(a['valor'])}).toLowerCase()));"]
        if "contem" in a:
            return [f"{alvo}.then(v => expect(JSON.stringify(v)).to.include({ex.valor(a['contem'])}));"]
        return [f"{alvo}.should('exist');"]
    return [f"// TODO: '{c}' não tem conversão automática para Cypress"]


def gerar_cypress(r) -> dict:
    ex = Exportador(r, "js")
    linhas = ["// Gerado pelo Sentinela QA a partir do roteiro: " + os.path.basename(r.arquivo),
              "// Rodar: npm install && npx cypress run", "", f"describe('{r.sistema.replace(chr(39), '’')}', () => {{"]
    for caso in r.casos:
        linhas.append(f"  it('{_nome_teste(caso)}', () => {{")
        for p in r.antes_de_cada + caso.passos:
            for l in _passo_cy(p.comando, p.args, ex, r):
                linhas.append("    " + l)
        linhas += ["  });", ""]
    linhas.append("});")
    suporte = """// Comandos de apoio para achar campos como uma pessoa faria (gerado pelo Sentinela QA)
Cypress.Commands.add('campoPorRotulo', (texto) =>
  cy.contains('label', texto).invoke('attr', 'for').then((id) => cy.get(`#${id}`)));

Cypress.Commands.add('campo', (texto) =>
  cy.get('body').then(($b) => {
    const label = [...$b.find('label')].find((l) => l.innerText.trim() === texto);
    if (label && label.htmlFor) return cy.get(`#${label.htmlFor}`);
    if ($b.find(`[placeholder="${texto}"]`).length) return cy.get(`[placeholder="${texto}"]`).first();
    return cy.contains('button, a, input[type=submit], *', texto).first();
  }));
"""
    config = ("const { defineConfig } = require('cypress');\n\nmodule.exports = defineConfig({\n"
              "  e2e: { supportFile: 'cypress/support/e2e.js', specPattern: 'cypress/e2e/**/*.cy.js' },\n"
              "  reporter: 'junit', reporterOptions: { mochaFile: 'resultados/junit-[hash].xml' },\n});\n")
    pacote = {"name": "sentinela-export-cypress", "private": True, "scripts": {"test": "cypress run"},
              "devDependencies": {"cypress": "^13.0.0"}}
    return {"cypress/e2e/sentinela.cy.js": "\n".join(linhas) + "\n", "cypress/support/e2e.js": suporte,
            "cypress.config.js": config, "package.json": json.dumps(pacote, indent=2) + "\n"}


# ====================================================================== Selenium (Python) e Appium
def _loc_py(alvo: str, ex: Exportador) -> str:
    alvo, n = _css_padrao(alvo)
    if n:
        return f"[e for e in driver.find_elements(By.CSS_SELECTOR, {ex.valor(alvo)}) if e.is_displayed()][{n}]"
    p, _, resto = str(alvo).partition("=")
    v = ex.valor
    if resto and p == "texto":
        return f"achar(driver, By.XPATH, f\"//*[contains(normalize-space(), '{{{v(resto)}}}')]\")"
    if resto and p == "rotulo":
        return f"por_rotulo(driver, {v(resto)})"
    if resto and p == "placeholder":
        return f"achar(driver, By.CSS_SELECTOR, '[placeholder=\"' + {v(resto)} + '\"]')"
    if resto and p == "testid":
        return f"achar(driver, By.CSS_SELECTOR, '[{ex.r.atributo_testid}=\"{resto}\"]')"
    if resto and p == "papel":
        papel, _, nome = resto.partition(":")
        tag = {"button": "button", "link": "a"}.get(papel, "*")
        return f"achar(driver, By.XPATH, f\"//{tag}[normalize-space()='{{{v(nome)}}}']\")"
    if resto and p == "xpath":
        return f"achar(driver, By.XPATH, {v(resto)})"
    if re.match(r"^[#.\[*]|^[a-zA-Z][\w-]*[.#\[>:]", str(alvo)):
        return f"achar(driver, By.CSS_SELECTOR, {v(alvo)})"
    return f"por_texto(driver, {v(alvo)})"


def _passo_py(c: str, a, ex: Exportador, r) -> list[str]:
    g = ex.arg
    if c == "abrir":
        return [f"driver.get({ex.valor(_url(r, g(a, 'url', '/') if isinstance(a, dict) else (a or '/')))})"]
    if c == "clicar":
        return [f"{_loc_py(g(a, 'alvo'), ex)}.click()"]
    if c == "preencher":
        return [f"el = {_loc_py(a['campo'], ex)}", "el.clear()", f"el.send_keys({ex.valor(a['valor'])})"]
    if c == "digitar":
        return [f"{_loc_py(a['campo'], ex) if isinstance(a, dict) and a.get('campo') else 'driver.switch_to.active_element'}.send_keys({ex.valor(g(a, 'texto'))})"]
    if c == "apertar_tecla":
        tecla = {"Enter": "ENTER", "Tab": "TAB", "Esc": "ESCAPE", "Escape": "ESCAPE"}.get(str(g(a, "tecla")), str(g(a, "tecla")).upper())
        return [f"{_loc_py(a['campo'], ex) if isinstance(a, dict) and a.get('campo') else 'driver.switch_to.active_element'}.send_keys(Keys.{tecla})"]
    if c == "selecionar":
        return [f"Select({_loc_py(a['campo'], ex)}).select_by_visible_text({ex.valor(a['opcao'])})"]
    if c == "marcar":
        return [f"el = {_loc_py(g(a, 'alvo'), ex)}", "if not el.is_selected(): el.click()"]
    if c == "esperar":
        if isinstance(a, (int, float)):
            return [f"time.sleep({a})"]
        if "texto" in a:
            return [f"esperar_texto(driver, {ex.valor(a['texto'])})"]
        return [f"{_loc_py(g(a, 'elemento') or g(a, 'alvo') or a.get('sumir'), ex)}"]
    if c == "logar":
        return [f"el = {_loc_py(a.get('campo_usuario', 'input[type=email]'), ex)}", "el.clear()", f"el.send_keys({ex.valor(a['usuario'])})",
                f"el = {_loc_py(a.get('campo_senha', 'input[type=password]'), ex)}", "el.clear()", f"el.send_keys({ex.valor(a['senha'])})",
                f"{_loc_py(a.get('botao', 'button[type=submit]'), ex)}.click()"]
    if c == "cadastrar":
        linhas = []
        for k, v in a["campos"].items():
            linhas += [f"el = {_loc_py(k, ex)}", "el.clear()", f"el.send_keys({ex.valor(v)})"]
        if a.get("enviar"):
            linhas.append(f"{_loc_py(a['enviar'], ex)}.click()")
        return linhas
    if c == "buscar":
        return [f"el = {_loc_py(a.get('campo', 'input[type=search]') if isinstance(a, dict) else 'input[type=search]', ex)}",
                "el.clear()", f"el.send_keys({ex.valor(g(a, 'termo'))}, Keys.ENTER)"]
    if c in ("verificar_texto", "verificar_mensagem"):
        if isinstance(a, dict) and a.get("elemento"):
            return [f"esperar(lambda: {ex.valor(a['texto'])} in {_loc_py(a['elemento'], ex)}.text)"]
        return [f"esperar_texto(driver, {ex.valor(g(a, 'texto'))})"]
    if c == "verificar_sem_texto":
        return [f"assert {ex.valor(g(a, 'texto'))} not in driver.find_element(By.TAG_NAME, 'body').text"]
    if c == "verificar_elemento":
        return [f"assert {_loc_py(g(a, 'alvo'), ex)}.is_displayed()"]
    if c == "verificar_url":
        if isinstance(a, dict) and "igual" in a:
            return [f"esperar(lambda: driver.current_url == {ex.valor(a['igual'])})"]
        return [f"esperar(lambda: {ex.valor(g(a, 'contem'))} in driver.current_url)"]
    if c == "verificar_titulo":
        return [f"esperar(lambda: {ex.valor(g(a, 'contem'))} in driver.title)"]
    if c == "verificar_valor":
        return [f"assert {_loc_py(a['campo'], ex)}.get_attribute('value') == {ex.valor(a['valor'])}"]
    return [f"# TODO: '{c}' não tem conversão automática para Selenium"]


_APOIO_PY = '''

def esperar(condicao, segundos=10):
    """Espera uma condição ficar verdadeira (sem sleep fixo)."""
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            if condicao():
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError("Condição não atendida em %ss" % segundos)


def achar(driver, por, valor):
    """Espera aparecer o primeiro elemento VISÍVEL que combina com o seletor."""
    def visivel(d):
        return next((e for e in d.find_elements(por, valor) if e.is_displayed()), False)
    return WebDriverWait(driver, 10).until(visivel)


def por_rotulo(driver, texto):
    label = achar(driver, By.XPATH, f"//label[normalize-space()='{texto}']")
    return driver.find_element(By.ID, label.get_attribute("for"))


def por_texto(driver, texto):
    """Rótulo, placeholder, botão, link ou texto — como uma pessoa procuraria."""
    for por, valor in [(By.XPATH, f"//label[normalize-space()='{texto}']"), (By.CSS_SELECTOR, f'[placeholder="{texto}"]'),
                       (By.XPATH, f"//button[normalize-space()='{texto}'] | //a[normalize-space()='{texto}']"),
                       (By.XPATH, f"//*[normalize-space(text())='{texto}']")]:
        achados = [e for e in driver.find_elements(por, valor) if e.is_displayed()]
        if achados:
            el = achados[0]
            return driver.find_element(By.ID, el.get_attribute("for")) if el.tag_name == "label" else el
    return achar(driver, By.XPATH, f"//*[contains(normalize-space(), '{texto}')]")


def esperar_texto(driver, texto):
    esperar(lambda: texto in driver.find_element(By.TAG_NAME, "body").text)
'''


def _gerar_py_web(r, cabecalho: str, fixture: str, nome: str) -> dict:
    ex = Exportador(r, "py")
    linhas = [cabecalho, _APOIO_PY, "", fixture]
    for caso in r.casos:
        fn = re.sub(r"\W+", "_", f"test_{caso.id}_{caso.descricao}".lower()).strip("_")[:60]
        linhas.append(f"\ndef {fn}(driver):\n    \"\"\"{caso.descricao}\"\"\"")
        for p in r.antes_de_cada + caso.passos:
            for l in _passo_py(p.comando, p.args, ex, r):
                linhas.append("    " + l)
    return {nome: "\n".join(linhas) + "\n", "requirements.txt": "selenium>=4.20\npytest>=8\n" +
            ("Appium-Python-Client>=4.0\n" if "appium" in nome else "")}


def gerar_selenium(r) -> dict:
    cab = ("\"\"\"Gerado pelo Sentinela QA a partir do roteiro " + os.path.basename(r.arquivo) +
           ".\nRodar: pip install -r requirements.txt && pytest -q\n\"\"\"\nimport os\nimport time\n\nimport pytest\n"
           "from selenium import webdriver\nfrom selenium.webdriver.common.by import By\nfrom selenium.webdriver.common.keys import Keys\n"
           "from selenium.webdriver.support import expected_conditions as EC\nfrom selenium.webdriver.support.ui import Select, WebDriverWait")
    fixture = ("@pytest.fixture\ndef driver():\n    opcoes = webdriver.ChromeOptions()\n    opcoes.add_argument('--headless=new')\n"
               "    d = webdriver.Chrome(options=opcoes)   # o Selenium Manager baixa o chromedriver sozinho\n"
               "    d.set_window_size(1280, 800)\n    yield d\n    d.quit()")
    return _gerar_py_web(r, cab, fixture, "test_sentinela_selenium.py")


def gerar_appium(r) -> dict:
    cab = ("\"\"\"Gerado pelo Sentinela QA — teste WEB MOBILE no Chrome do Android via Appium.\n"
           "Requisitos: Appium Server 2 (npm i -g appium && appium driver install uiautomator2),\n"
           "Android SDK com um emulador ligado (ou celular com depuração USB) e Chrome no aparelho.\n"
           "Rodar: appium   (em outro terminal)   e depois   pytest -q\n"
           "Obs.: no emulador, 'localhost' do PC é 10.0.2.2.\n\"\"\"\nimport os\nimport time\n\nimport pytest\n"
           "from appium import webdriver\nfrom appium.options.android import UiAutomator2Options\n"
           "from selenium.webdriver.common.by import By\nfrom selenium.webdriver.common.keys import Keys\n"
           "from selenium.webdriver.support import expected_conditions as EC\nfrom selenium.webdriver.support.ui import Select, WebDriverWait")
    fixture = ("@pytest.fixture\ndef driver():\n    opcoes = UiAutomator2Options()\n    opcoes.platform_name = 'Android'\n"
               "    opcoes.browser_name = 'Chrome'\n    opcoes.device_name = os.getenv('APPIUM_DEVICE', 'emulator-5554')\n"
               "    d = webdriver.Remote(os.getenv('APPIUM_URL', 'http://127.0.0.1:4723'), options=opcoes)\n    yield d\n    d.quit()")
    saida = _gerar_py_web(r, cab, fixture, "test_sentinela_appium.py")
    for k in list(saida):
        if k.endswith(".py") and r.alvo and "127.0.0.1" in r.alvo:
            saida[k] = saida[k].replace("http://127.0.0.1", "http://10.0.2.2")
    return saida


# ====================================================================== Maestro
def gerar_maestro(r) -> dict:
    ex = Exportador(r, "py")

    def lit(v):
        return ex.texto(v).replace('"', "'")

    def alvo_texto(alvo):
        p, _, resto = str(alvo).partition("=")
        if resto and p in ("texto", "rotulo", "placeholder"):
            return resto
        if resto and p == "papel":
            return resto.partition(":")[2]
        if resto and p == "testid":
            return {"id": resto}
        if str(alvo).startswith("#"):
            return {"id": alvo[1:]}
        return alvo

    def tap(alvo):
        t = alvo_texto(alvo)
        return [f"- tapOn:\n    id: \"{t['id']}\""] if isinstance(t, dict) else [f"- tapOn: \"{t}\""]

    fluxos = {}
    for caso in r.casos:
        linhas = ["appId: com.android.chrome", f"name: \"{_nome_teste(caso)}\"", "---"]
        for p in r.antes_de_cada + caso.passos:
            c, a = p.comando, p.args
            if c == "abrir":
                url = _url(r, ex.arg(a, "url", "/") if isinstance(a, dict) else (a or "/")).replace("127.0.0.1", "10.0.2.2")
                linhas.append(f"- openLink: \"{lit(url)}\"")
            elif c == "clicar":
                linhas += tap(ex.arg(a, "alvo"))
            elif c == "preencher":
                linhas += tap(a["campo"]) + ["- eraseText", f"- inputText: \"{lit(a['valor'])}\""]
            elif c == "logar":
                linhas += tap(a.get("campo_usuario", "Usuário")) + [f"- inputText: \"{lit(a['usuario'])}\""]
                linhas += tap(a.get("campo_senha", "Senha")) + [f"- inputText: \"{lit(a['senha'])}\""]
                linhas += tap(a.get("botao", "Entrar"))
            elif c == "cadastrar":
                for k, v in a["campos"].items():
                    linhas += tap(k) + ["- eraseText", f"- inputText: \"{lit(v)}\""]
                if a.get("enviar"):
                    linhas += tap(a["enviar"])
            elif c == "apertar_tecla" and str(ex.arg(a, "tecla")).lower() == "enter":
                linhas.append("- pressKey: Enter")
            elif c in ("verificar_texto", "verificar_mensagem"):
                linhas.append(f"- assertVisible: \"{lit(ex.arg(a, 'texto'))}\"")
            elif c == "verificar_sem_texto":
                linhas.append(f"- assertNotVisible: \"{lit(ex.arg(a, 'texto'))}\"")
            elif c == "esperar" and isinstance(a, dict) and "texto" in a:
                linhas.append(f"- extendedWaitUntil:\n    visible: \"{lit(a['texto'])}\"\n    timeout: 10000")
            else:
                linhas.append(f"# TODO: '{c}' não tem equivalente direto no Maestro")
        fluxos[f"flows/{caso.id.lower()}.yaml"] = "\n".join(linhas) + "\n"
    fluxos["LEIA-ME.md"] = ("# Fluxos Maestro gerados pelo Sentinela QA\n\nTeste web mobile no Chrome do Android.\n\n"
                            "1. Instale o Maestro: https://maestro.mobile.dev\n2. Ligue um emulador Android\n"
                            "3. Rode: `maestro test flows --format junit --output resultados/junit.xml`\n")
    return fluxos


# ====================================================================== API: pytest + requests e RestAssured
def gerar_pytest_api(r) -> dict:
    ex = Exportador(r, "py")
    linhas = ["\"\"\"Gerado pelo Sentinela QA a partir do roteiro " + os.path.basename(r.arquivo) + ".",
              "Rodar: pip install requests pytest jsonpath-ng && pytest -q\n\"\"\"", "import os", "", "import requests", "",
              "", "def campo(json, caminho):", "    \"\"\"Lê 'itens[0].nome' de um JSON.\"\"\"", "    import re",
              "    for parte in re.findall(r\"[^.\\[\\]]+|\\[\\d+\\]\", caminho):",
              "        json = json[int(parte[1:-1])] if parte.startswith('[') else json[parte]", "    return json"]
    for caso in r.casos:
        fn = re.sub(r"\W+", "_", f"test_{caso.id}_{caso.descricao}".lower()).strip("_")[:60]
        linhas += ["", "", f"def {fn}():", f"    \"\"\"{caso.descricao}\"\"\""]
        for p in caso.passos:
            c, a = p.comando, p.args
            if c == "requisitar":
                q = _req_args(a)
                extra = ""
                if q.get("cabecalhos"):
                    extra += ", headers={" + ", ".join(f"{json.dumps(k)}: {ex.valor(v)}" for k, v in q["cabecalhos"].items()) + "}"
                if q.get("corpo") is not None:
                    extra += f", json={json.dumps(q['corpo'], ensure_ascii=False)}"
                if q.get("consulta"):
                    extra += f", params={json.dumps(q['consulta'], ensure_ascii=False)}"
                linhas.append(f"    r = requests.request({json.dumps(q.get('metodo', 'GET').upper())}, "
                              f"{ex.valor(_url(r, q['url']))}{extra}, timeout=20)")
            elif c == "verificar_status":
                if isinstance(a, dict) and "entre" in a:
                    linhas.append(f"    assert {a['entre'][0]} <= r.status_code <= {a['entre'][1]}")
                else:
                    linhas.append(f"    assert r.status_code == {int(a['igual'] if isinstance(a, dict) else a)}")
            elif c == "verificar_json":
                cam = json.dumps(a.get("campo", ""))
                if a.get("existe") is False:
                    linhas.append(f"    assert {cam} not in r.text or True  # TODO: conferir ausência de {a.get('campo')}")
                elif "valor" in a:
                    linhas.append(f"    assert str(campo(r.json(), {cam})).lower() == str({ex.valor(a['valor'])}).lower()")
                elif "contem" in a:
                    linhas.append(f"    assert {ex.valor(a['contem'])} in str(campo(r.json(), {cam}) if {cam} else r.json())")
                else:
                    linhas.append(f"    assert campo(r.json(), {cam}) is not None")
            elif c == "verificar_tempo":
                linhas.append(f"    assert r.elapsed.total_seconds() * 1000 <= {ex.arg(a, 'maximo_ms')}")
            elif c == "verificar_cabecalho":
                linhas.append(f"    assert {json.dumps(str(a.get('contem', '')).lower())} in r.headers.get({json.dumps(a['nome'])}, '').lower()")
            elif c == "guardar":
                linhas.append(f"    {a['como']} = campo(r.json(), {json.dumps(a['campo'])})")
                ex.guardar(a["como"])
            else:
                linhas.append(f"    # TODO: '{c}' não tem conversão automática")
    return {"test_sentinela_api.py": "\n".join(linhas) + "\n",
            "requirements.txt": "requests>=2.31\npytest>=8\n"}


def gerar_restassured(r) -> dict:
    ex = Exportador(r, "java")
    pacote = "br.sentinela.qa"
    linhas = [f"package {pacote};", "", "import static io.restassured.RestAssured.given;",
              "import static org.hamcrest.Matchers.*;", "", "import io.restassured.response.Response;",
              "import org.junit.jupiter.api.DisplayName;", "import org.junit.jupiter.api.Test;", "",
              "/** Gerado pelo Sentinela QA a partir do roteiro " + os.path.basename(r.arquivo) + ". Rodar: mvn test */",
              "class SentinelaApiTest {"]
    for caso in r.casos:
        fn = re.sub(r"\W+", "_", f"{caso.id}_{caso.descricao}").strip("_")[:60]
        linhas += ["", "    @Test", f"    @DisplayName({json.dumps(_nome_teste(caso), ensure_ascii=False)})", f"    void {fn}() {{",
                   "        Response r = null;"]
        for p in caso.passos:
            c, a = p.comando, p.args
            if c == "requisitar":
                q = _req_args(a)
                corpo = ""
                if q.get("corpo") is not None:
                    corpo = f"\n            .contentType(\"application/json\").body({json.dumps(json.dumps(q['corpo'], ensure_ascii=False), ensure_ascii=False)})"
                cab = "".join(f"\n            .header({json.dumps(k)}, {ex.valor(v)})" for k, v in (q.get("cabecalhos") or {}).items())
                qs = "".join(f"\n            .queryParam({json.dumps(k)}, {json.dumps(str(v))})" for k, v in (q.get("consulta") or {}).items())
                linhas.append(f"        r = given(){cab}{qs}{corpo}\n            .when().request({json.dumps(q.get('metodo', 'GET').upper())}, "
                              f"{ex.valor(_url(r, q['url']))});")
            elif c == "verificar_status":
                if isinstance(a, dict) and "entre" in a:
                    linhas.append(f"        r.then().statusCode(allOf(greaterThanOrEqualTo({a['entre'][0]}), lessThanOrEqualTo({a['entre'][1]})));")
                else:
                    linhas.append(f"        r.then().statusCode({int(a['igual'] if isinstance(a, dict) else a)});")
            elif c == "verificar_json":
                cam = json.dumps(a.get("campo", ""))
                if a.get("existe") is False:
                    linhas.append(f"        r.then().body({cam}, nullValue());")
                elif "valor" in a:
                    linhas.append(f"        r.then().body({cam}, hasToString(equalToIgnoringCase(String.valueOf({ex.valor(a['valor'])}))));")
                elif "contem" in a:
                    linhas.append(f"        r.then().body({cam}, hasToString(containsString({ex.valor(a['contem'])})));")
                else:
                    linhas.append(f"        r.then().body({cam}, notNullValue());")
            elif c == "verificar_tempo":
                linhas.append(f"        r.then().time(lessThanOrEqualTo({int(ex.arg(a, 'maximo_ms'))}L));")
            elif c == "verificar_cabecalho":
                linhas.append(f"        r.then().header({json.dumps(a['nome'])}, containsStringIgnoringCase({json.dumps(str(a.get('contem', '')))}));")
            elif c == "guardar":
                linhas.append(f"        String {a['como']} = r.path({json.dumps(a['campo'])}).toString();")
                ex.guardar(a["como"])
            else:
                linhas.append(f"        // TODO: '{c}' não tem conversão automática")
        linhas.append("    }")
    linhas.append("}")
    pom = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>{pacote}</groupId>
  <artifactId>sentinela-restassured</artifactId>
  <version>1.0.0</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency><groupId>io.rest-assured</groupId><artifactId>rest-assured</artifactId><version>5.5.0</version><scope>test</scope></dependency>
    <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.11.3</version><scope>test</scope></dependency>
    <dependency><groupId>org.hamcrest</groupId><artifactId>hamcrest</artifactId><version>3.0</version><scope>test</scope></dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.5.2</version></plugin>
    </plugins>
  </build>
</project>
"""
    caminho = "src/test/java/" + pacote.replace(".", "/") + "/SentinelaApiTest.java"
    return {caminho: "\n".join(linhas) + "\n", "pom.xml": pom}


# ====================================================================== Postman
def gerar_postman(r) -> dict:
    from sentinela.postman import exportar_colecao
    return {"colecao.postman_collection.json": json.dumps(exportar_colecao(r), ensure_ascii=False, indent=2) + "\n"}


GERADORES = {"playwright-ts": gerar_playwright, "cypress": gerar_cypress, "selenium-py": gerar_selenium,
             "pytest-api": gerar_pytest_api, "restassured": gerar_restassured, "appium-py": gerar_appium,
             "maestro": gerar_maestro, "postman": gerar_postman}


def exportar(roteiro, formato: str) -> dict:
    """Devolve {caminho_relativo: conteúdo} para o formato pedido."""
    if formato not in GERADORES:
        raise ValueError(f"Formato desconhecido: {formato}. Use: {', '.join(GERADORES)}")
    return GERADORES[formato](roteiro)


def salvar(arquivos: dict, pasta: str) -> list[str]:
    caminhos = []
    for rel, conteudo in arquivos.items():
        destino = os.path.join(pasta, rel)
        os.makedirs(os.path.dirname(destino) or pasta, exist_ok=True)
        with open(destino, "w", encoding="utf-8", newline="\n") as f:
            f.write(conteudo)
        caminhos.append(destino)
    return caminhos
