"""
Executor WEB com Selenium WebDriver (alternativa ao Playwright).

Use no roteiro:   motor: selenium
O Selenium Manager (já vem no Selenium 4) baixa sozinho o chromedriver certo para o Chrome instalado.

Os comandos são os mesmos dos roteiros web. Seletores aceitos:
    "#id", ".classe", "input[name=x]"   CSS
    "xpath=//div[1]"                    XPath
    "texto=Entrar"                      elemento com esse texto
    "rotulo=E-mail"                     campo ligado ao <label>
    "placeholder=Buscar"                campo com esse placeholder
    "testid=login"                      atributo data-testid (configurável com atributo_testid)
    "papel=button:Entrar"               botão/link com esse nome
    "Entrar"                            sem prefixo: rótulo, placeholder, botão, link e texto
(As extensões exclusivas do Playwright, como ">> nth=0" e ":visible", não funcionam no Selenium.)
"""

import os
import re
import time
from urllib.parse import urljoin

from sentinela.executor_api import ComandosApi
from sentinela.executor_base import ErroPasso, ExecutorBase

TECLAS = {"enter": "ENTER", "tab": "TAB", "esc": "ESCAPE", "escape": "ESCAPE", "espaco": "SPACE", "espaço": "SPACE",
          "backspace": "BACKSPACE", "apagar": "BACKSPACE", "delete": "DELETE", "seta_cima": "ARROW_UP",
          "seta_baixo": "ARROW_DOWN", "seta_esquerda": "ARROW_LEFT", "seta_direita": "ARROW_RIGHT", "home": "HOME",
          "end": "END", "ctrl": "CONTROL", "control": "CONTROL", "shift": "SHIFT", "alt": "ALT"}


def _xpath_texto(t: str) -> str:
    """Literal XPath seguro mesmo com aspas no texto."""
    if "'" not in t:
        return f"'{t}'"
    if '"' not in t:
        return f'"{t}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in t.split("'")) + ")"


class ExecutorSelenium(ComandosApi, ExecutorBase):
    tipo = "web"

    def iniciar(self):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        self.By = By
        opcoes = webdriver.ChromeOptions()
        if not self.opcoes.get("visivel"):
            opcoes.add_argument("--headless=new")
        opcoes.add_argument("--window-size=1280,800")
        opcoes.add_argument("--lang=pt-BR")
        try:
            self.driver = webdriver.Chrome(options=opcoes)
        except Exception as e:
            raise RuntimeError(f"Não foi possível abrir o Chrome pelo Selenium: {str(e).splitlines()[0]}")
        self.driver.implicitly_wait(0)
        versao = self.driver.capabilities.get("browserVersion", "")
        self.navegador = f"Google Chrome {versao} (Selenium WebDriver)"
        self.registro.log(f"Navegador: {self.navegador}")

    def finalizar(self):
        try:
            self.driver.quit()
        except Exception:
            pass

    def preparar_caso(self, caso=None):
        # Sessão limpa a cada caso (como no Playwright): apaga cookies e armazenamento
        try:
            self.driver.delete_all_cookies()
            if self.driver.current_url.startswith("http"):
                self.driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
        except Exception:
            pass

    def capturar(self, comando: str):
        caminho, rel = self.registro.novo_print(self.caso_atual, comando)
        try:
            self.driver.save_screenshot(caminho)
            return rel
        except Exception:
            return None

    # ------------------------------------------------------------ localizar com espera
    def _estrategias(self, alvo: str) -> list[tuple]:
        By = self.By
        prefixo, _, resto = alvo.partition("=")
        p = prefixo.lower()
        if resto and p == "texto":
            return [(By.XPATH, f"//*[contains(normalize-space(text()), {_xpath_texto(resto)})]")]
        if resto and p == "rotulo":
            return [("rotulo", resto)]
        if resto and p == "placeholder":
            return [(By.CSS_SELECTOR, f'[placeholder="{resto}"]')]
        if resto and p == "testid":
            return [(By.CSS_SELECTOR, f'[{self.roteiro.atributo_testid}="{resto}"]')]
        if resto and p == "papel":
            papel, _, nome = resto.partition(":")
            tags = {"button": "button", "link": "a"}.get(papel, "*")
            cond = f"[normalize-space()={_xpath_texto(nome)} or @aria-label={_xpath_texto(nome)} or @value={_xpath_texto(nome)}]" if nome else ""
            return [(By.XPATH, f"//{tags}{cond} | //*[@role='{papel}']{cond}" + (" | //input[@type='submit' or @type='button']" + cond if papel == "button" else ""))]
        if resto and p == "xpath":
            return [(By.XPATH, resto)]
        if resto and p in ("css", "id"):
            return [(By.CSS_SELECTOR, resto if p == "css" else f"[id='{resto}']")]
        if re.match(r"^([#.\[*]|[a-zA-Z][\w-]*([#.\[\]>:]|$))", alvo) and not re.match(r"^[A-ZÀ-Ú][a-zà-ú]+( |$)", alvo):
            return [(By.CSS_SELECTOR, alvo)]
        t = _xpath_texto(alvo)
        return [("rotulo", alvo), (By.CSS_SELECTOR, f'[placeholder="{alvo}"]'),
                (By.XPATH, f"//button[normalize-space()={t}] | //input[(@type='submit' or @type='button') and @value={t}]"),
                (By.XPATH, f"//a[normalize-space()={t}]"), (By.XPATH, f"//*[normalize-space(text())={t}]")]

    def _achar(self, estrategia):
        By = self.By
        tipo, valor = estrategia
        if tipo == "rotulo":
            for label in self.driver.find_elements(By.XPATH, f"//label[normalize-space()={_xpath_texto(valor)}]"):
                alvo = label.get_attribute("for")
                if alvo:
                    achados = self.driver.find_elements(By.ID, alvo)
                    if achados:
                        return achados[0]
                internos = label.find_elements(By.CSS_SELECTOR, "input, select, textarea")
                if internos:
                    return internos[0]
            return None
        achados = [e for e in self.driver.find_elements(tipo, valor) if e.is_displayed()]
        return achados[0] if achados else None

    def localizar(self, alvo, visivel=True):
        if not alvo:
            raise ErroPasso("Faltou informar o elemento (alvo/campo)")
        limite = time.time() + self.roteiro.tempo_limite
        estrategias = self._estrategias(str(alvo).strip())
        while True:
            for e in estrategias:
                try:
                    el = self._achar(e)
                except Exception:
                    el = None
                if el is not None:
                    return el
            if time.time() > limite:
                raise ErroPasso(f"Elemento '{alvo}' não encontrado em {self.roteiro.tempo_limite:g}s (Selenium)")
            time.sleep(0.2)

    def _esperar(self, condicao, mensagem):
        limite = time.time() + self.roteiro.tempo_limite
        while time.time() <= limite:
            try:
                if condicao():
                    return
            except Exception:
                pass
            time.sleep(0.2)
        raise ErroPasso(mensagem)

    @staticmethod
    def _arg(args, chave, *outras, obrigatorio=True):
        if not isinstance(args, dict):
            return args
        for k in (chave, *outras):
            if k in args:
                return args[k]
        if obrigatorio:
            raise ErroPasso(f"Faltou o parâmetro '{chave}' no passo")
        return None

    def _texto_pagina(self) -> str:
        return self.driver.find_element(self.By.TAG_NAME, "body").text

    # ------------------------------------------------------------ comandos
    def cmd_abrir(self, args):
        url = self._arg(args, "url", obrigatorio=False) or "/"
        if not url.startswith(("http://", "https://")):
            url = urljoin(self.alvo.rstrip("/") + "/", url.lstrip("/"))
        self.driver.get(url)
        return f"Página aberta: {self.driver.current_url}"

    def cmd_clicar(self, args):
        alvo = self._arg(args, "alvo")
        el = self.localizar(alvo)
        try:
            el.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", el)   # elemento coberto por outro
        return f"Clicou em '{alvo}'"

    def cmd_clicar_duplo(self, args):
        from selenium.webdriver import ActionChains
        alvo = self._arg(args, "alvo")
        ActionChains(self.driver).double_click(self.localizar(alvo)).perform()
        return f"Duplo clique em '{alvo}'"

    def cmd_passar_mouse(self, args):
        from selenium.webdriver import ActionChains
        alvo = self._arg(args, "alvo")
        ActionChains(self.driver).move_to_element(self.localizar(alvo)).perform()
        return f"Mouse sobre '{alvo}'"

    def cmd_preencher(self, args):
        campo, valor = self._arg(args, "campo"), str(self._arg(args, "valor"))
        el = self.localizar(campo)
        el.clear()
        el.send_keys(valor)
        return f"'{campo}' preenchido"

    def cmd_digitar(self, args):
        texto = str(self._arg(args, "texto"))
        campo = args.get("campo") if isinstance(args, dict) else None
        alvo = self.localizar(campo) if campo else self.driver.switch_to.active_element
        for letra in texto:
            alvo.send_keys(letra)
            time.sleep(0.02)
        return f"Digitou '{texto}'"

    def cmd_apertar_tecla(self, args):
        from selenium.webdriver.common.keys import Keys
        tecla = str(self._arg(args, "tecla"))
        teclas = [getattr(Keys, TECLAS.get(t.strip().lower(), t.strip().upper()), t.strip()) for t in tecla.split("+")]
        campo = args.get("campo") if isinstance(args, dict) else None
        alvo = self.localizar(campo) if campo else self.driver.switch_to.active_element
        alvo.send_keys(*teclas)
        return f"Tecla {tecla} pressionada"

    def cmd_esperar(self, args):
        if isinstance(args, (int, float)):
            time.sleep(float(args))
            return f"Esperou {args}s"
        if isinstance(args, dict) and "texto" in args:
            self._esperar(lambda: str(args["texto"]) in self._texto_pagina(), f"Texto '{args['texto']}' não apareceu")
            return f"Texto '{args['texto']}' apareceu"
        if isinstance(args, dict) and "sumir" in args:
            By = self.By
            self._esperar(lambda: not any(e.is_displayed() for e in self.driver.find_elements(By.CSS_SELECTOR, args["sumir"])),
                          f"'{args['sumir']}' não sumiu")
            return f"'{args['sumir']}' sumiu"
        alvo = self._arg(args, "elemento", "alvo")
        self.localizar(alvo)
        return f"'{alvo}' apareceu"

    def cmd_selecionar(self, args):
        from selenium.webdriver.support.ui import Select
        campo, opcao = self._arg(args, "campo"), str(self._arg(args, "opcao"))
        sel = Select(self.localizar(campo))
        try:
            sel.select_by_visible_text(opcao)
        except Exception:
            sel.select_by_value(opcao)
        return f"Opção '{opcao}' selecionada"

    def cmd_marcar(self, args):
        el = self.localizar(self._arg(args, "alvo"))
        if not el.is_selected():
            el.click()
        return "Marcado"

    def cmd_desmarcar(self, args):
        el = self.localizar(self._arg(args, "alvo"))
        if el.is_selected():
            el.click()
        return "Desmarcado"

    def cmd_enviar_arquivo(self, args):
        campo, arquivo = self._arg(args, "campo"), self._arg(args, "arquivo")
        caminho = arquivo if os.path.isabs(arquivo) else os.path.join(self.roteiro.pasta, arquivo)
        By = self.By
        el = self.driver.find_element(By.CSS_SELECTOR, campo) if campo.startswith(("#", ".", "input")) else self.localizar(campo)
        el.send_keys(os.path.abspath(caminho))
        return f"Arquivo '{os.path.basename(caminho)}' selecionado"

    def cmd_arrastar(self, args):
        from selenium.webdriver import ActionChains
        de, para = self._arg(args, "de"), self._arg(args, "para")
        ActionChains(self.driver).drag_and_drop(self.localizar(de), self.localizar(para)).perform()
        return f"'{de}' arrastado para '{para}'"

    def cmd_rolar(self, args):
        if isinstance(args, dict) and "ate" in args:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", self.localizar(args["ate"]))
            return f"Rolou até '{args['ate']}'"
        y = {"baixo": "window.scrollBy(0, 600)", "cima": "window.scrollBy(0, -600)",
             "fim": "window.scrollTo(0, document.body.scrollHeight)", "topo": "window.scrollTo(0, 0)"}.get(args, f"window.scrollBy(0, {int(args)})")
        self.driver.execute_script(y)
        return f"Rolou ({args})"

    def cmd_logar(self, args):
        self.cmd_preencher({"campo": args.get("campo_usuario") or "input[type=email], input[name*=user], input[id*=usuario], input[name*=email]",
                            "valor": self._arg(args, "usuario")})
        self.cmd_preencher({"campo": args.get("campo_senha") or "input[type=password]", "valor": self._arg(args, "senha")})
        self.cmd_clicar(args.get("botao") or "button[type=submit], input[type=submit]")
        return f"Login enviado com o usuário '{args['usuario']}'"

    def cmd_cadastrar(self, args):
        from selenium.webdriver.support.ui import Select
        campos = self._arg(args, "campos")
        for campo, valor in campos.items():
            el = self.localizar(campo)
            if el.tag_name.lower() == "select":
                Select(el).select_by_visible_text(str(valor))
            else:
                el.clear()
                el.send_keys(str(valor))
        if args.get("enviar"):
            self.cmd_clicar(args["enviar"])
        return f"{len(campos)} campo(s) preenchido(s)"

    def cmd_buscar(self, args):
        from selenium.webdriver.common.keys import Keys
        termo = self._arg(args, "termo")
        campo = (args.get("campo") if isinstance(args, dict) else None) or "input[type=search], input[name=q]"
        el = self.localizar(campo)
        el.clear()
        el.send_keys(str(termo), Keys.ENTER)
        return f"Busca por '{termo}' enviada"

    def cmd_recarregar(self, args):
        self.driver.refresh()
        return "Página recarregada"

    def cmd_voltar(self, args):
        self.driver.back()
        return f"Voltou para {self.driver.current_url}"

    def cmd_capturar_tela(self, args):
        return "Tela capturada"

    # ------------------------------------------------------------ verificações
    def cmd_verificar_texto(self, args):
        texto = str(self._arg(args, "texto"))
        elemento = args.get("elemento") if isinstance(args, dict) else None
        if elemento:
            self._esperar(lambda: texto in self.localizar(elemento).text,
                          f"'{elemento}' não contém '{texto}' (Selenium)")
            return f"'{elemento}' contém '{texto}'"
        self._esperar(lambda: texto in self._texto_pagina(), f"Texto '{texto}' não está visível na página (Selenium)")
        return f"Texto '{texto}' visível"

    def cmd_verificar_sem_texto(self, args):
        texto = str(self._arg(args, "texto"))
        if texto in self._texto_pagina():
            raise ErroPasso(f"O texto '{texto}' aparece, mas não deveria")
        return f"Texto '{texto}' não aparece (correto)"

    def cmd_verificar_elemento(self, args):
        alvo = self._arg(args, "alvo")
        if isinstance(args, dict) and "quantidade" in args:
            By = self.By
            self._esperar(lambda: len([e for e in self.driver.find_elements(By.CSS_SELECTOR, alvo) if e.is_displayed()])
                          == int(args["quantidade"]), f"'{alvo}' não aparece {args['quantidade']} vez(es)")
            return f"'{alvo}' aparece {args['quantidade']} vez(es)"
        self.localizar(alvo)
        return f"Elemento '{alvo}' visível"

    def cmd_verificar_url(self, args):
        if isinstance(args, dict) and "igual" in args:
            self._esperar(lambda: self.driver.current_url == args["igual"], f"URL é {self.driver.current_url}, esperado {args['igual']}")
            return f"URL é {args['igual']}"
        trecho = str(self._arg(args, "contem"))
        self._esperar(lambda: trecho in self.driver.current_url, f"URL {self.driver.current_url} não contém '{trecho}'")
        return f"URL contém '{trecho}' ({self.driver.current_url})"

    def cmd_verificar_titulo(self, args):
        trecho = str(self._arg(args, "contem"))
        self._esperar(lambda: trecho in self.driver.title, f"Título '{self.driver.title}' não contém '{trecho}'")
        return f"Título contém '{trecho}'"

    def cmd_verificar_valor(self, args):
        campo, valor = self._arg(args, "campo"), str(self._arg(args, "valor"))
        self._esperar(lambda: self.localizar(campo).get_attribute("value") == valor, f"'{campo}' não tem o valor '{valor}'")
        return f"'{campo}' tem o valor '{valor}'"

    def cmd_verificar_mensagem(self, args):
        texto = args.get("texto") if isinstance(args, dict) else args
        self._esperar(lambda: str(texto) in self._texto_pagina(), f"A mensagem '{texto}' não apareceu (Selenium)")
        return f"Mensagem exibida: '{texto}'"

    def traduzir_erro(self, erro, passo):
        if isinstance(erro, ErroPasso):
            return str(erro)
        primeira = (str(erro).strip().splitlines() or [type(erro).__name__])[0]
        return f"{type(erro).__name__}: {primeira[:250]}"
