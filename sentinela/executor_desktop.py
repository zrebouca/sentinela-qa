"""
Executor de testes DESKTOP (programas .exe do Windows) com pywinauto.

Usa a árvore de automação do Windows (UI Automation, backend "uia"):
os elementos são encontrados pelo id de automação ou pelo nome, que não
mudam quando a janela muda de posição ou de tamanho — ao contrário das
coordenadas de tela. PyAutoGUI (coordenadas) fica só como último recurso.

Como escrever o alvo de um elemento no roteiro:
    "id=num7Button"             -> AutomationId (o mais estável)
    "nome=Sete"                 -> nome visível do controle
    "tipo=Button;nome=Igual a"  -> combinação (tipo de controle + nome)
    "num7Button"                -> sem prefixo: tenta id, depois nome
    { x: 120, y: 300 }          -> coordenada relativa à janela (último recurso)

Dica: para descobrir ids e nomes, use o "Accessibility Insights for Windows"
ou rode:  python -c "from pywinauto import Desktop; Desktop(backend='uia').window(title_re='.*Calculadora.*').print_control_identifiers()"
"""

import os
import re
import shutil
import subprocess
import time

from sentinela.executor_base import ErroPasso, ExecutorBase

# Teclas com nome em português -> formato do pywinauto
TECLAS = {
    "enter": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}",
    "espaco": "{SPACE}", "espaço": "{SPACE}", "backspace": "{BACKSPACE}",
    "apagar": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}",
    "seta_cima": "{UP}", "seta_baixo": "{DOWN}", "seta_esquerda": "{LEFT}",
    "seta_direita": "{RIGHT}", "home": "{HOME}", "end": "{END}", "f1": "{F1}",
    "f5": "{F5}", "ctrl": "^", "alt": "%", "shift": "+",
}

TIPOS_CONTROLE = {"botao": "Button", "botão": "Button", "campo": "Edit", "texto": "Text",
                  "lista": "List", "menu": "MenuItem", "caixa": "CheckBox", "combo": "ComboBox"}


CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"


def compilar_cs(fonte: str, exe: str):
    """Compila um programa WinForms (.cs) com o compilador C# que já vem no Windows."""
    if not os.path.isfile(CSC):
        raise ErroPasso("Compilador C# do Windows (csc.exe) não encontrado para gerar o programa de treino.")
    # Roda dentro da pasta do código e usa só os nomes dos arquivos: o csc se confunde com
    # caminhos relativos ("..") e com acentos no caminho (ex.: "Automação").
    fonte, exe = os.path.normpath(os.path.abspath(fonte)), os.path.normpath(os.path.abspath(exe))
    r = subprocess.run([CSC, "/nologo", "/target:winexe", f"/out:{os.path.basename(exe)}", "/r:System.Windows.Forms.dll",
                        "/r:System.Drawing.dll", os.path.basename(fonte)], cwd=os.path.dirname(fonte),
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ErroPasso(f"Falha ao compilar {os.path.basename(fonte)}: {r.stdout[-300:]}")


def resolver_exe(alvo: str, pasta_roteiro: str) -> str:
    """Acha o .exe: caminho direto, relativo ao roteiro/projeto ou no PATH (ex.: calc.exe).
    Se for um programa de treino com o código .cs ao lado e sem .exe, compila na hora."""
    from sentinela.painel.banco import pasta_base
    candidatos = [alvo] if os.path.isabs(alvo) else [alvo, os.path.join(pasta_roteiro, alvo),
                                                      os.path.join(pasta_base(), alvo)]
    for c in (os.path.normpath(x) for x in candidatos):
        if os.path.isfile(c):
            return os.path.abspath(c)
        fonte = os.path.splitext(c)[0] + ".cs"
        if c.lower().endswith(".exe") and os.path.isfile(fonte):
            compilar_cs(fonte, os.path.abspath(c))
            return os.path.abspath(c)
    return shutil.which(alvo) or alvo


def _escapar(texto: str) -> str:
    """Escapa caracteres que o pywinauto entende como comandos (+ ^ % ~ ( ) { })."""
    return re.sub(r"([+^%~(){}\[\]])", r"{\1}", texto)


class ExecutorDesktop(ExecutorBase):
    tipo = "desktop"

    def iniciar(self):
        # Importa aqui para o modo web funcionar mesmo sem pywinauto
        from pywinauto import Desktop
        from pywinauto.application import Application
        self._Desktop, self._Application = Desktop, Application
        self.janela = None
        self.processo = None
        self.navegador = "Windows UI Automation (pywinauto)"
        self._abrir_programa()

    def finalizar(self):
        if self.janela is not None and not self.opcoes.get("manter_aberto"):
            try:
                self.janela.close()
            except Exception:
                pass

    # ------------------------------------------------------------ janela
    def _abrir_programa(self):
        if not self.alvo:
            raise ErroPasso("Informe o caminho do .exe em 'alvo'")
        exe = resolver_exe(self.alvo, self.roteiro.pasta)
        self.registro.log(f"Abrindo o programa: {exe}")
        self.processo = subprocess.Popen([exe])
        limite = time.time() + max(15, self.roteiro.tempo_limite)
        erro = None
        while time.time() < limite:
            try:
                if self.roteiro.janela:
                    # Programas modernos (ex.: Calculadora) abrem outro processo;
                    # por isso procuramos a janela pelo título.
                    janela = self._Desktop(backend="uia").window(title_re=self.roteiro.janela)
                else:
                    app = self._Application(backend="uia").connect(process=self.processo.pid, timeout=2)
                    janela = app.top_window()
                janela.wait("visible", timeout=2)
                self.janela = janela
                self.janela.set_focus()
                self.registro.log(f"Janela encontrada: '{self.janela.window_text()}'")
                return
            except Exception as e:  # ainda abrindo
                erro = e
                time.sleep(0.5)
        raise ErroPasso(f"A janela do programa não apareceu a tempo ({erro})")

    def capturar(self, comando: str) -> str | None:
        if self.janela is None:
            return None
        caminho, rel = self.registro.novo_print(self.caso_atual, comando)
        try:
            self.janela.set_focus()
            time.sleep(0.15)  # deixa a janela terminar de desenhar
            self.janela.capture_as_image().save(caminho)
            return rel
        except Exception:
            return None

    # ------------------------------------------------------------ localizar
    def _criterios(self, alvo: str) -> list[dict]:
        alvo = str(alvo).strip()
        if "=" not in alvo:
            return [{"auto_id": alvo}, {"title": alvo}]
        crit = {}
        for parte in alvo.split(";"):
            chave, _, valor = parte.partition("=")
            chave = chave.strip().lower()
            valor = valor.strip()
            if chave == "id":
                crit["auto_id"] = valor
            elif chave == "nome":
                crit["title"] = valor
            elif chave == "nome_contem":
                crit["title_re"] = f".*{re.escape(valor)}.*"
            elif chave == "tipo":
                crit["control_type"] = TIPOS_CONTROLE.get(valor.lower(), valor)
            elif chave == "classe":
                crit["class_name"] = valor
            else:
                raise ErroPasso(f"Prefixo desconhecido no alvo desktop: '{chave}'")
        return [crit]

    def localizar(self, alvo):
        """Espera o elemento existir (sem pausa fixa) e devolve o controle."""
        limite = time.time() + self.roteiro.tempo_limite
        opcoes = self._criterios(alvo)
        while True:
            for crit in opcoes:
                spec = self.janela.child_window(**crit)
                if spec.exists(timeout=0.3):
                    return spec.wrapper_object()
            if time.time() > limite:
                raise ErroPasso(f"Elemento '{alvo}' não encontrado na janela em {self.roteiro.tempo_limite:g}s")

    def _coordenada(self, args) -> tuple[int, int] | None:
        if isinstance(args, dict) and "x" in args and "y" in args:
            r = self.janela.rectangle()
            return r.left + int(args["x"]), r.top + int(args["y"])
        return None

    @staticmethod
    def _arg(args, chave, *outras):
        if not isinstance(args, dict):
            return args
        for k in (chave, *outras):
            if k in args:
                return args[k]
        raise ErroPasso(f"Faltou o parâmetro '{chave}' no passo")

    # ------------------------------------------------------------ comandos
    def cmd_abrir(self, args):
        if self.janela is None or not self.janela.exists(timeout=1):
            self._abrir_programa()
        self.janela.set_focus()
        return f"Programa aberto: '{self.janela.window_text()}'"

    def cmd_clicar(self, args):
        xy = self._coordenada(args)
        if xy:
            import pyautogui  # último recurso
            pyautogui.click(*xy)
            return f"Clique por coordenada {xy} (último recurso)"
        alvo = self._arg(args, "alvo")
        el = self.localizar(alvo)
        try:
            el.invoke()          # aciona pelo UI Automation (não depende do mouse)
        except Exception:
            el.click_input()     # se o controle não suportar, clica com o mouse
        return f"Clicou em '{alvo}'"

    def cmd_clicar_duplo(self, args):
        alvo = self._arg(args, "alvo")
        self.localizar(alvo).double_click_input()
        return f"Duplo clique em '{alvo}'"

    def cmd_passar_mouse(self, args):
        alvo = self._arg(args, "alvo")
        el = self.localizar(alvo)
        r = el.rectangle()
        from pywinauto import mouse
        mouse.move(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2))
        return f"Mouse sobre '{alvo}'"

    def cmd_preencher(self, args):
        campo, valor = self._arg(args, "campo"), str(self._arg(args, "valor"))
        el = self.localizar(campo)
        try:
            senha = bool(el.element_info.element.CurrentIsPassword)
        except Exception:
            senha = False
        if senha:
            # Campos de senha não aceitam valor via UI Automation (proteção do Windows): digita pelo teclado
            el.set_focus()
            el.type_keys("^a{BACKSPACE}" + _escapar(valor), with_spaces=True, pause=0.02)
            return f"'{campo}' preenchido (campo de senha, digitado pelo teclado)"
        try:
            el.set_edit_text(valor)
        except Exception:
            el.set_focus()
            el.type_keys("^a{DELETE}" + _escapar(valor), with_spaces=True)
        return f"'{campo}' preenchido"

    def cmd_digitar(self, args):
        texto = str(self._arg(args, "texto"))
        campo = args.get("campo") if isinstance(args, dict) else None
        alvo = self.localizar(campo) if campo else self.janela
        alvo.set_focus()
        alvo.type_keys(_escapar(texto), with_spaces=True, pause=0.03)
        return f"Digitou '{texto}'"

    def cmd_apertar_tecla(self, args):
        tecla = str(self._arg(args, "tecla"))
        partes = [TECLAS.get(t.strip().lower(), t.strip()) for t in tecla.split("+")]
        sequencia = "".join(partes) if len(partes) > 1 else partes[0]
        self.janela.set_focus()
        self.janela.type_keys(sequencia)
        return f"Tecla {tecla} pressionada"

    def cmd_esperar(self, args):
        if isinstance(args, (int, float)):
            time.sleep(float(args))
            return f"Esperou {args}s"
        alvo = self._arg(args, "elemento", "alvo")
        self.localizar(alvo)
        return f"'{alvo}' apareceu"

    def cmd_selecionar(self, args):
        campo, opcao = self._arg(args, "campo"), str(self._arg(args, "opcao"))
        el = self.localizar(campo)
        try:
            el.select(opcao)
            return f"Opção '{opcao}' selecionada"
        except Exception:
            pass
        # Plano B (ComboBox DropDownList do WinForms): teclado — Home e setas até chegar na opção
        def atual():
            for leitura in (lambda: el.selected_text(), lambda: el.get_value(), lambda: el.window_text()):
                try:
                    v = leitura()
                    if v:
                        return str(v)
                except Exception:
                    continue
            return ""
        el.set_focus()
        el.type_keys("{HOME}")
        for _ in range(60):
            if atual().strip().lower() == opcao.strip().lower():
                return f"Opção '{opcao}' selecionada (pelo teclado)"
            el.type_keys("{DOWN}")
            time.sleep(0.05)
        raise ErroPasso(f"A opção '{opcao}' não existe em '{campo}' (último valor: '{atual()}')")

    def cmd_marcar(self, args):
        el = self.localizar(self._arg(args, "alvo"))
        if el.get_toggle_state() == 0:
            el.toggle()
        return "Marcado"

    def cmd_desmarcar(self, args):
        el = self.localizar(self._arg(args, "alvo"))
        if el.get_toggle_state() == 1:
            el.toggle()
        return "Desmarcado"

    def cmd_arrastar(self, args):
        de = self.localizar(self._arg(args, "de")).rectangle()
        para = self.localizar(self._arg(args, "para")).rectangle()
        from pywinauto import mouse
        mouse.press(coords=de.mid_point())
        mouse.move(coords=para.mid_point())
        mouse.release(coords=para.mid_point())
        return "Arrastado"

    def cmd_rolar(self, args):
        from pywinauto import mouse
        r = self.janela.rectangle()
        passos = {"baixo": -5, "cima": 5}.get(args, -5)
        mouse.scroll(coords=r.mid_point(), wheel_dist=passos)
        return f"Rolou ({args})"

    def cmd_capturar_tela(self, args):
        return "Tela capturada"

    def cmd_fechar(self, args):
        self.janela.close()
        self.janela = None
        return "Programa fechado"

    # ------------------------------------------------------------ verificações
    def _texto_do(self, el) -> str:
        partes = [el.window_text()]
        try:
            partes.append(el.get_value())
        except Exception:
            pass
        return " ".join(p for p in partes if p)

    def cmd_verificar_texto(self, args):
        """Verifica se um texto aparece em um elemento ou em qualquer lugar da janela.
        Tenta várias vezes até o tempo limite (o programa pode demorar a atualizar)."""
        texto = str(self._arg(args, "texto", "contem"))
        elemento = args.get("elemento") if isinstance(args, dict) else None
        limite = time.time() + self.roteiro.tempo_limite
        visto = ""
        while time.time() <= limite:
            if elemento:
                visto = self._texto_do(self.localizar(elemento))
                if texto.lower() in visto.lower():
                    return f"'{elemento}' contém '{texto}' (exibido: '{visto}')"
            else:
                nomes = [d.window_text() for d in self.janela.descendants()]
                if any(texto.lower() in n.lower() for n in nomes if n):
                    return f"Texto '{texto}' visível"
            time.sleep(0.3)
        onde = f"em '{elemento}' (exibido: '{visto}')" if elemento else "na janela"
        raise ErroPasso(f"Texto '{texto}' não encontrado {onde}")

    def cmd_verificar_sem_texto(self, args):
        texto = str(self._arg(args, "texto"))
        nomes = [d.window_text() for d in self.janela.descendants()]
        if any(texto.lower() in n.lower() for n in nomes if n):
            raise ErroPasso(f"O texto '{texto}' aparece, mas não deveria")
        return f"Texto '{texto}' não aparece (correto)"

    def cmd_verificar_elemento(self, args):
        alvo = self._arg(args, "alvo")
        el = self.localizar(alvo)
        if not el.is_visible():
            raise ErroPasso(f"Elemento '{alvo}' existe, mas não está visível")
        return f"Elemento '{alvo}' existe"

    def cmd_verificar_titulo(self, args):
        trecho = str(self._arg(args, "contem"))
        titulo = self.janela.window_text()
        if trecho.lower() not in titulo.lower():
            raise ErroPasso(f"Título da janela é '{titulo}', esperado conter '{trecho}'")
        return f"Título contém '{trecho}'"

    def cmd_verificar_valor(self, args):
        campo, valor = self._arg(args, "campo"), str(self._arg(args, "valor"))
        visto = self._texto_do(self.localizar(campo))
        if valor not in visto:
            raise ErroPasso(f"'{campo}' mostra '{visto}', esperado '{valor}'")
        return f"'{campo}' tem o valor '{valor}'"

    def cmd_verificar_mensagem(self, args):
        texto = self._arg(args, "texto")
        return self.cmd_verificar_texto({"texto": texto})
