"""
Executor de testes WEB com Playwright.

Por que Playwright e não coordenadas de tela?
- Localiza elementos por texto, rótulo, id, data-testid etc. (seletores estáveis).
- Espera automaticamente o elemento aparecer/ficar clicável (sem "sleep" fixo).
- Cada caso roda numa sessão limpa do navegador (sem cookies do caso anterior).

Como escrever o alvo de um elemento no roteiro:
    "#user-name"            -> CSS (id)
    ".btn-primary"          -> CSS (classe)
    "input[name=email]"     -> CSS (atributo)
    "texto=Entrar"          -> elemento com esse texto
    "rotulo=E-mail"         -> campo com esse <label>
    "placeholder=Buscar"    -> campo com esse placeholder
    "testid=login-button"   -> atributo data-testid (configurável no roteiro)
    "papel=button:Entrar"   -> papel de acessibilidade (role) + nome
    "xpath=//div[1]"        -> XPath (evite se puder)
    "Entrar"                -> sem prefixo: tenta rótulo, placeholder, botão,
                               link e texto, nessa ordem
"""

import os
import re
from urllib.parse import urljoin

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import expect, sync_playwright

from sentinela.executor_api import ComandosApi
from sentinela.executor_qualidade import ComandosQualidade
from sentinela.seguranca import ComandosSeguranca
from sentinela.ux import ComandosUx
from sentinela.executor_base import ErroPasso, ExecutorBase

# Teclas com nome em português -> nome usado pelo Playwright
TECLAS = {
    "enter": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
    "espaco": "Space", "espaço": "Space", "backspace": "Backspace", "apagar": "Backspace",
    "delete": "Delete", "del": "Delete", "seta_cima": "ArrowUp", "seta_baixo": "ArrowDown",
    "seta_esquerda": "ArrowLeft", "seta_direita": "ArrowRight", "home": "Home", "end": "End",
    "fim": "End", "inicio": "Home", "pagedown": "PageDown", "pageup": "PageUp",
}

# Onde costumam aparecer mensagens de sucesso/erro
SELETOR_MENSAGENS = (
    "[role=alert], [role=status], .flash, .alert, .toast, .notification, .message, "
    "[data-test=error], [class*=error], [class*=success], [class*=sucesso], "
    "[class*=erro], .invalid-feedback, .help-block"
)

# Verificação rápida de acessibilidade feita a cada página aberta
JS_ACESSIBILIDADE = """
() => {
  const problemas = [];
  if (!document.documentElement.getAttribute('lang'))
    problemas.push('A página não declara o idioma (atributo lang no <html>).');
  const imgs = [...document.querySelectorAll('img')].filter(i => !i.hasAttribute('alt'));
  if (imgs.length) problemas.push(`${imgs.length} imagem(ns) sem texto alternativo (alt).`);
  const campos = [...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea')]
    .filter(c => !(c.labels && c.labels.length) && !c.getAttribute('aria-label') && !c.getAttribute('aria-labelledby'));
  if (campos.length) problemas.push(`${campos.length} campo(s) de formulário sem <label> associado (leitores de tela não anunciam o nome; placeholder não substitui label).`);
  const botoes = [...document.querySelectorAll('button, a[href]')]
    .filter(b => !(b.innerText || '').trim() && !b.getAttribute('aria-label') && !b.getAttribute('title') && !b.querySelector('img[alt]'));
  if (botoes.length) problemas.push(`${botoes.length} botão(ões)/link(s) sem texto acessível.`);
  if (!document.title.trim()) problemas.push('A página não tem título (<title>).');
  return problemas;
}
"""


TAGS_HTML = {"button", "input", "select", "textarea", "form", "table", "img", "a",
             "h1", "h2", "h3", "h4", "nav", "header", "footer", "main", "ul", "li", "label"}


def _eh_css(alvo: str) -> bool:
    """Decide se o alvo parece um seletor CSS (ex.: '#id', '.classe',
    'input[name=x]', 'div > a') ou um texto comum (ex.: 'Entrar')."""
    if alvo[0] in "#.[*/(":
        return True
    if alvo.lower() in TAGS_HTML:
        return True
    return bool(re.search(r"[\[\]>#]|:has\(|:nth|^[a-zA-Z][\w-]*\.[\w-]", alvo))


class ExecutorWeb(ComandosQualidade, ComandosSeguranca, ComandosUx, ComandosApi, ExecutorBase):
    """Também aceita os comandos de API (requisitar, verificar_status...) no mesmo roteiro."""
    tipo = "web"

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self):
        self.pw = sync_playwright().start()
        headless = not self.opcoes.get("visivel", False)
        self.browser = None
        # Usa o Chrome instalado; se não tiver, o Edge (que vem no Windows);
        # por último, o Chromium do próprio Playwright (se instalado).
        preferido = (self.roteiro.navegador or "").lower()
        canais = [preferido] if preferido in ("chrome", "msedge") else []
        for canal in canais + ["chrome", "msedge", None]:
            try:
                self.browser = self.pw.chromium.launch(channel=canal, headless=headless)
                self.navegador = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}.get(canal, "Chromium")
                break
            except PWError:
                continue
        if self.browser is None:
            raise RuntimeError("Nenhum navegador encontrado. Instale o Google Chrome.")
        self.navegador += f" {self.browser.version}"
        self.registro.log(f"Navegador: {self.navegador} ({'invisível' if headless else 'visível'})")
        self.pw.selectors.set_test_id_attribute(self.roteiro.atributo_testid)
        self.context = None
        self.page = None
        self._paginas_checadas = set()

    def finalizar(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            self.pw.stop()

    def preparar_caso(self, caso=None):
        """Cada caso começa numa sessão limpa (sem cookies/localStorage)."""
        opcoes = {"viewport": {"width": 1280, "height": 800}, "locale": "pt-BR"}
        if self.roteiro.dispositivo:
            # Emulação de celular/tablet (lista de aparelhos do Playwright, ex.: "iPhone 13", "Pixel 7")
            aparelho = self.pw.devices.get(self.roteiro.dispositivo)
            if not aparelho:
                raise RuntimeError(f"Dispositivo desconhecido: {self.roteiro.dispositivo}")
            opcoes.update({k: v for k, v in aparelho.items() if k != "default_browser_type"})
        self.context = self.browser.new_context(**opcoes)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.tempo_limite_ms)
        expect.set_options(timeout=self.tempo_limite_ms)
        # Captura erros do console e respostas HTTP com erro, para "O que foi encontrado"
        self.page.on("console", self._ao_console)
        self.page.on("pageerror", lambda e: self.registro.observar(
            "Console", f"Erro de JavaScript na página: {str(e)[:200]}"))
        self.page.on("response", self._ao_resposta)

    def encerrar_caso(self, caso=None):
        if self.context:
            self.context.close()
            self.context = None

    def _ao_console(self, msg):
        if msg.type == "error":
            self.registro.observar("Console", f"Erro no console do navegador: {msg.text[:200]}")

    def _ao_resposta(self, resp):
        if resp.status >= 400:
            self.registro.observar("Rede", f"Requisição com erro HTTP {resp.status}: {resp.url[:150]}")

    def capturar(self, comando: str) -> str | None:
        if not self.page or self.page.is_closed():
            return None
        caminho, rel = self.registro.novo_print(self.caso_atual, comando)
        try:
            self.page.screenshot(path=caminho, timeout=5000)
            return rel
        except PWError:
            return None

    def _checar_acessibilidade(self):
        url = self.page.url.split("?")[0]
        if url in self._paginas_checadas:
            return
        self._paginas_checadas.add(url)
        try:
            for problema in self.page.evaluate(JS_ACESSIBILIDADE):
                self.registro.observar("Acessibilidade", f"{url}: {problema}")
        except PWError:
            pass

    # ------------------------------------------------------------ localizar
    def localizar(self, alvo: str):
        """Transforma o texto do roteiro num Locator do Playwright."""
        if not alvo:
            raise ErroPasso("Faltou informar o elemento (alvo/campo)")
        alvo = str(alvo).strip()
        p = self.page
        prefixo, _, resto = alvo.partition("=")
        prefixo = prefixo.lower()
        if resto:
            if prefixo == "texto":
                return p.get_by_text(resto).first
            if prefixo == "rotulo":
                return p.get_by_label(resto).first
            if prefixo == "placeholder":
                return p.get_by_placeholder(resto).first
            if prefixo == "testid":
                return p.get_by_test_id(resto).first
            if prefixo == "papel":
                papel, _, nome = resto.partition(":")
                return p.get_by_role(papel, name=nome or None).first
            if prefixo in ("css", "xpath"):
                return p.locator(alvo).first
            if prefixo == "id":
                return p.locator(f"[id='{resto}']").first
        if _eh_css(alvo):
            return p.locator(alvo).first
        # Sem prefixo: procura do jeito que uma pessoa procuraria, NESTA ordem de prioridade
        # (um botão "Entrar" vence um título "Entrar" que aparece antes na página)
        candidatos = [p.get_by_label(alvo), p.get_by_placeholder(alvo), p.get_by_role("button", name=alvo),
                      p.get_by_role("link", name=alvo), p.get_by_text(alvo, exact=True)]
        for c in candidatos:
            if c.count():
                return c.first
        # Nada ainda na tela: devolve a combinação (o Playwright espera algum aparecer)
        combinado = candidatos[0]
        for c in candidatos[1:]:
            combinado = combinado.or_(c)
        return combinado.first

    @staticmethod
    def _arg(args, chave, *outras, obrigatorio=True):
        """Lê um argumento que pode vir como texto simples ou dicionário."""
        if not isinstance(args, dict):
            return args
        for k in (chave, *outras):
            if k in args:
                return args[k]
        if obrigatorio:
            raise ErroPasso(f"Faltou o parâmetro '{chave}' no passo")
        return None

    # ------------------------------------------------------------ comandos
    def cmd_abrir(self, args):
        url = self._arg(args, "url", obrigatorio=False) or "/"
        if not url.startswith(("http://", "https://")):
            if not self.alvo:
                raise ErroPasso("URL relativa sem alvo definido")
            url = urljoin(self.alvo.rstrip("/") + "/", url.lstrip("/"))
        resp = self.page.goto(url, wait_until="load")
        self._checar_acessibilidade()
        codigo = f" (HTTP {resp.status})" if resp else ""
        return f"Página aberta: {self.page.url}{codigo}"

    def cmd_clicar(self, args):
        alvo = self._arg(args, "alvo")
        self.localizar(alvo).click()
        self.page.wait_for_load_state("load")
        self._checar_acessibilidade()
        return f"Clicou em '{alvo}'"

    def cmd_clicar_duplo(self, args):
        alvo = self._arg(args, "alvo")
        self.localizar(alvo).dblclick()
        return f"Duplo clique em '{alvo}'"

    def cmd_passar_mouse(self, args):
        alvo = self._arg(args, "alvo")
        self.localizar(alvo).hover()
        return f"Mouse sobre '{alvo}'"

    def cmd_preencher(self, args):
        campo, valor = self._arg(args, "campo"), self._arg(args, "valor")
        self.localizar(campo).fill(str(valor))
        return f"'{campo}' preenchido"

    def cmd_digitar(self, args):
        texto = self._arg(args, "texto")
        campo = args.get("campo") if isinstance(args, dict) else None
        if campo:
            self.localizar(campo).press_sequentially(str(texto), delay=30)
        else:
            self.page.keyboard.type(str(texto), delay=30)
        return f"Digitou '{texto}'"

    def cmd_apertar_tecla(self, args):
        tecla = str(self._arg(args, "tecla"))
        nome = "+".join(TECLAS.get(t.strip().lower(), t.strip()) for t in tecla.split("+"))
        campo = args.get("campo") if isinstance(args, dict) else None
        if campo:
            self.localizar(campo).press(nome)
        else:
            self.page.keyboard.press(nome)
        return f"Tecla {nome} pressionada"

    def cmd_esperar(self, args):
        # Número = segundos (use pouco! prefira esperar por um elemento/texto)
        if isinstance(args, (int, float)):
            self.page.wait_for_timeout(float(args) * 1000)
            return f"Esperou {args}s"
        if isinstance(args, dict) and "texto" in args:
            self.page.get_by_text(str(args["texto"])).first.wait_for(state="visible")
            return f"Texto '{args['texto']}' apareceu"
        if isinstance(args, dict) and "sumir" in args:
            self.localizar(args["sumir"]).wait_for(state="hidden")
            return f"'{args['sumir']}' sumiu"
        alvo = self._arg(args, "elemento", "alvo")
        self.localizar(alvo).wait_for(state="visible")
        return f"'{alvo}' apareceu"

    def cmd_selecionar(self, args):
        campo, opcao = self._arg(args, "campo"), str(self._arg(args, "opcao"))
        loc = self.localizar(campo)
        try:
            loc.select_option(label=opcao, timeout=3000)
        except PWError:
            loc.select_option(value=opcao)
        return f"Opção '{opcao}' selecionada"

    def cmd_marcar(self, args):
        alvo = self._arg(args, "alvo")
        self.localizar(alvo).check()
        return f"'{alvo}' marcado"

    def cmd_desmarcar(self, args):
        alvo = self._arg(args, "alvo")
        self.localizar(alvo).uncheck()
        return f"'{alvo}' desmarcado"

    def cmd_enviar_arquivo(self, args):
        campo, arquivo = self._arg(args, "campo"), self._arg(args, "arquivo")
        caminho = arquivo if os.path.isabs(arquivo) else os.path.join(self.roteiro.pasta, arquivo)
        if not os.path.isfile(caminho):
            raise ErroPasso(f"Arquivo para envio não encontrado: {caminho}")
        self.localizar(campo).set_input_files(caminho)
        return f"Arquivo '{os.path.basename(caminho)}' selecionado"

    def cmd_arrastar(self, args):
        de, para = self._arg(args, "de"), self._arg(args, "para")
        self.localizar(de).drag_to(self.localizar(para))
        return f"'{de}' arrastado para '{para}'"

    def cmd_rolar(self, args):
        if isinstance(args, dict) and "ate" in args:
            self.localizar(args["ate"]).scroll_into_view_if_needed()
            return f"Rolou até '{args['ate']}'"
        direcoes = {"baixo": 600, "cima": -600}
        if args in ("fim", "topo"):
            self.page.evaluate("y => window.scrollTo(0, y)", 10**7 if args == "fim" else 0)
        else:
            self.page.mouse.wheel(0, direcoes.get(args, int(args) if str(args).lstrip("-").isdigit() else 600))
        return f"Rolou ({args})"

    def cmd_logar(self, args):
        """Login completo: preenche usuário e senha e clica no botão."""
        usuario = self._arg(args, "usuario")
        senha = self._arg(args, "senha")
        campo_u = args.get("campo_usuario") or (
            "input[type=email], input[name*=user i], input[id*=user i], input[name*=usuario i], input[id*=usuario i], "
            "input[name*=login i], input[name*=email i]")
        campo_s = args.get("campo_senha") or "input[type=password]"
        botao = args.get("botao") or "button[type=submit], input[type=submit], [id*=login i][type=submit], button:has-text('Entrar'), button:has-text('Login')"
        self.localizar(campo_u).fill(str(usuario))
        self.localizar(campo_s).fill(str(senha))
        self.localizar(botao).click()
        self.page.wait_for_load_state("load")
        self._checar_acessibilidade()
        return f"Login enviado com o usuário '{usuario}'"

    def cmd_cadastrar(self, args):
        """Preenche vários campos de uma vez e (opcionalmente) envia."""
        campos = self._arg(args, "campos")
        if not isinstance(campos, dict):
            raise ErroPasso("Em 'cadastrar', 'campos' deve ser uma lista campo: valor")
        for campo, valor in campos.items():
            loc = self.localizar(campo)
            if loc.evaluate("e => e.tagName") == "SELECT":
                loc.select_option(label=str(valor))
            else:
                loc.fill(str(valor))
        if args.get("enviar"):
            self.localizar(args["enviar"]).click()
            self.page.wait_for_load_state("load")
        return f"{len(campos)} campo(s) preenchido(s)"

    def cmd_buscar(self, args):
        termo = self._arg(args, "termo")
        campo = (args.get("campo") if isinstance(args, dict) else None) or (
            "input[type=search], input[name=q], input[name*=search i], input[name*=busca i], "
            "input[placeholder*=Buscar i], input[placeholder*=Pesquisar i], input[placeholder*=Search i]")
        loc = self.localizar(campo)
        loc.fill(str(termo))
        loc.press("Enter")
        self.page.wait_for_load_state("load")
        return f"Busca por '{termo}' enviada"

    def cmd_recarregar(self, args):
        self.page.reload()
        return "Página recarregada"

    def cmd_voltar(self, args):
        self.page.go_back()
        return f"Voltou para {self.page.url}"

    def cmd_capturar_tela(self, args):
        return "Tela capturada"

    # ------------------------------------------------------------ verificações
    def cmd_verificar_texto(self, args):
        texto = str(self._arg(args, "texto"))
        elemento = args.get("elemento") if isinstance(args, dict) else None
        if elemento:
            expect(self.localizar(elemento)).to_contain_text(texto)
            return f"'{elemento}' contém '{texto}'"
        expect(self.page.get_by_text(texto).first).to_be_visible()
        return f"Texto '{texto}' visível"

    def cmd_verificar_sem_texto(self, args):
        texto = str(self._arg(args, "texto"))
        # Só conta o que está VISÍVEL (elementos escondidos não aparecem para o usuário)
        expect(self.page.get_by_text(texto).filter(visible=True)).to_have_count(0, timeout=3000)
        return f"Texto '{texto}' não aparece (correto)"

    def cmd_verificar_elemento(self, args):
        alvo = self._arg(args, "alvo")
        loc = self.localizar(alvo)
        if isinstance(args, dict) and "quantidade" in args:
            css = self.page.locator(alvo)
            expect(css).to_have_count(int(args["quantidade"]))
            return f"'{alvo}' aparece {args['quantidade']} vez(es)"
        if isinstance(args, dict) and args.get("visivel") is False:
            expect(loc).to_be_hidden()
            return f"'{alvo}' não está visível (correto)"
        expect(loc).to_be_visible()
        return f"Elemento '{alvo}' visível"

    def cmd_verificar_url(self, args):
        if isinstance(args, dict) and "igual" in args:
            expect(self.page).to_have_url(str(args["igual"]))
            return f"URL é {args['igual']}"
        trecho = str(self._arg(args, "contem"))
        expect(self.page).to_have_url(re.compile(re.escape(trecho)))
        return f"URL contém '{trecho}' ({self.page.url})"

    def cmd_verificar_titulo(self, args):
        trecho = str(self._arg(args, "contem"))
        expect(self.page).to_have_title(re.compile(re.escape(trecho)))
        return f"Título contém '{trecho}'"

    def cmd_verificar_valor(self, args):
        campo, valor = self._arg(args, "campo"), str(self._arg(args, "valor"))
        expect(self.localizar(campo)).to_have_value(valor)
        return f"'{campo}' tem o valor '{valor}'"

    def cmd_verificar_mensagem(self, args):
        """Procura uma mensagem de sucesso ou erro nos lugares de costume
        (alertas, flash, toast...). Se não achar, procura na página toda."""
        tipo = str(self._arg(args, "tipo", obrigatorio=False) or "").lower()
        texto = args.get("texto") if isinstance(args, dict) else args
        if tipo in ("sucesso", "erro") and isinstance(args, str):
            texto = None
        caixas = self.page.locator(SELETOR_MENSAGENS)
        if texto:
            alvo = caixas.filter(has_text=str(texto)).first.or_(self.page.get_by_text(str(texto)).first)
            try:
                expect(alvo.first).to_be_visible()
            except AssertionError:
                # Diz no relatório qual mensagem apareceu de fato (vira o "Obtido")
                visiveis = caixas.filter(visible=True)
                exibida = visiveis.first.inner_text().replace("×", "").strip().replace("\n", " ")[:150] if visiveis.count() else ""
                raise ErroPasso(f"A mensagem '{texto}' não apareceu. "
                                + (f"Mensagem exibida: '{exibida}'" if exibida else "Nenhuma mensagem foi exibida."))
            achado = texto
        else:
            palavras = {"sucesso": "success|sucesso|ok|confirm", "erro": "error|erro|danger|invalid|fail"}
            padrao = palavras.get(tipo, "")
            alvo = self.page.locator(", ".join(
                f"[class*={p}]" for p in padrao.split("|"))) if padrao else caixas
            expect(alvo.first).to_be_visible()
            achado = alvo.first.inner_text().strip()[:120]
        return f"Mensagem{' de ' + tipo if tipo else ''} exibida: '{achado}'"

    # ------------------------------------------------------------ erros
    def traduzir_erro(self, erro, passo):
        texto = str(erro)
        linhas = [l.strip() for l in texto.splitlines() if l.strip()]
        primeira = linhas[0] if linhas else type(erro).__name__
        recebido = next((l for l in linhas if l.lower().startswith(("actual value", "received"))), "")
        if isinstance(erro, ErroPasso):
            return texto
        if isinstance(erro, AssertionError):
            msg = f"Verificação não passou ({passo.descricao})."
            if recebido and "None" not in recebido:
                msg += f" {recebido.replace('Actual value', 'Valor encontrado').replace('Received', 'Recebido')}"
            return msg
        if isinstance(erro, PWTimeout) or "Timeout" in primeira:
            return (f"Tempo esgotado ({self.roteiro.tempo_limite:g}s): o elemento não apareceu ou "
                    f"não ficou disponível ({passo.descricao}).")
        if "net::" in primeira:
            return f"Não foi possível acessar a página: {primeira}"
        return primeira[:300]
