"""
Exploração leve de formulários (somente web).

Para cada campo configurado no roteiro, o robô:
  1. prepara a tela (ex.: faz login e chega no formulário);
  2. preenche TODOS os campos com dados válidos (Faker pt_BR)...
  3. ...menos o campo em teste, que recebe um valor inválido
     (vazio, só espaços, caracteres especiais, CPF/e-mail inválido, texto longo...);
  4. envia e observa: o sistema bloqueou (mensagem de erro / validação do
     navegador) ou aceitou e seguiu em frente?

Se ACEITOU um dado inválido -> vira um defeito (origem "Exploração").
Se BLOQUEOU -> vira uma observação positiva, com a mensagem mostrada.

Exemplo no roteiro:

exploracao:
  preparar:                         # passos para chegar ao formulário
    - abrir: /checkout
  campos:
    "#nome":  { tipo: nome }
    "#email": { tipo: email }
    "#cep":   { tipo: cep, testes: [vazio, cep_letras] }   # opcional: escolher testes
  enviar: "#continuar"
  sucesso_se: { url_contem: "passo-2" }   # como saber que o sistema ACEITOU
"""

import time

from sentinela import dados as massa
from sentinela.executor_web import SELETOR_MENSAGENS
from sentinela.roteiro import ErroRoteiro, _ler_passos


class Explorador:
    def __init__(self, executor):
        self.ex = executor
        self.reg = executor.registro
        cfg = executor.roteiro.exploracao or {}
        if not cfg.get("campos") or not cfg.get("enviar") or not cfg.get("sucesso_se"):
            raise ErroRoteiro("A seção 'exploracao' precisa de 'campos', 'enviar' e 'sucesso_se'")
        self.preparar = _ler_passos(cfg.get("preparar"), "exploracao.preparar")
        self.campos = cfg["campos"]
        self.enviar = cfg["enviar"]
        self.sucesso_se = cfg["sucesso_se"]
        self.max_tentativas = int(cfg.get("max_tentativas", 30))

    def rodar(self):
        self.reg.log("\n▶ Exploração leve de validações")
        contador = 0
        for seletor, conf in self.campos.items():
            conf = conf or {}
            tipo = conf.get("tipo", "texto")
            for codigo, desc, valor, severidade in massa.valores_invalidos(tipo, conf.get("testes")):
                contador += 1
                if contador > self.max_tentativas:
                    self.reg.avisar(f"Exploração parou no limite de {self.max_tentativas} tentativas")
                    return
                self._tentativa(f"EXP{contador:02d}", seletor, tipo, codigo, desc, valor, severidade)

    # -------------------------------------------------------------------------
    def _tentativa(self, eid, seletor, tipo, codigo, desc, valor, severidade):
        ex, reg = self.ex, self.reg
        ex.caso_atual = eid
        t0 = time.time()
        descricao = f"Exploração: '{seletor}' com {desc}"
        passos_feitos = []
        try:
            ex.preparar_caso()
            for passo in self.preparar:
                ex.executar_passo(passo)
                passos_feitos.append(passo.descricao)
            # Preenche os outros campos com dados válidos
            for outro, conf_outro in self.campos.items():
                tipo_outro = (conf_outro or {}).get("tipo", "texto")
                v = valor if outro == seletor else massa.valor_valido(tipo_outro)
                ex.localizar(outro).fill(v)
                mostra = (v[:30] + "...") if len(v) > 30 else v
                passos_feitos.append(f"Preencher '{outro}' com '{mostra}'")
            ex.localizar(self.enviar).click()
            passos_feitos.append(f"Clicar em '{self.enviar}'")
            resultado, mensagem = self._avaliar(seletor)
        except Exception as e:
            print_rel = ex.capturar("exploracao_erro")
            reg.registrar_acao(eid, "explorar", descricao, "falha", print_rel,
                               int((time.time() - t0) * 1000), f"Não foi possível explorar: {str(e).splitlines()[0][:150]}")
            ex.encerrar_caso()
            return

        print_rel = ex.capturar(f"exploracao_{codigo}")
        mostra_valor = (valor[:40] + "...") if len(valor) > 40 else valor
        if resultado == "aceito":
            reg.registrar_acao(eid, "explorar", descricao, "falha", print_rel,
                               int((time.time() - t0) * 1000), "Sistema ACEITOU o valor inválido")
            reg.novo_defeito(
                descricao=f"O campo '{seletor}' aceita {desc} ('{mostra_valor}') sem validação",
                severidade=severidade,
                passos_reproducao=passos_feitos,
                esperado=f"O sistema deveria bloquear {desc} e mostrar uma mensagem clara",
                obtido="O formulário foi aceito e o fluxo seguiu para a próxima etapa",
                evidencia=print_rel, origem="Exploração", caso_id=eid,
            )
        else:
            reg.registrar_acao(eid, "explorar", descricao, "ok", print_rel,
                               int((time.time() - t0) * 1000), mensagem)
            reg.observar("Exploração", f"'{seletor}' com {desc}: bloqueado corretamente — {mensagem}", print_rel)
        ex.encerrar_caso()

    def _avaliar(self, seletor) -> tuple[str, str]:
        """Observa a tela por até ~3s depois de enviar o formulário."""
        page = self.ex.page
        limite = time.time() + 3
        while time.time() < limite:
            # 1) O próprio navegador bloqueou (validação HTML5: required, type=email...)?
            try:
                msg_html5 = self.ex.localizar(seletor).evaluate(
                    "e => e.validationMessage || ''", timeout=500)
            except Exception:
                msg_html5 = ""
            if msg_html5:
                return "bloqueado", f"validação do navegador: \"{msg_html5}\""
            # 2) O sistema seguiu em frente (aceitou)?
            if "url_contem" in self.sucesso_se and self.sucesso_se["url_contem"] in page.url:
                return "aceito", ""
            if "texto" in self.sucesso_se and page.get_by_text(self.sucesso_se["texto"]).count():
                return "aceito", ""
            # 3) Apareceu mensagem de erro?
            caixas = page.locator(SELETOR_MENSAGENS).filter(visible=True)
            for i in range(min(caixas.count(), 10)):   # pega a primeira mensagem que tenha texto
                texto = caixas.nth(i).inner_text().strip().replace("\n", " ")[:150]
                if texto:
                    return "bloqueado", f"mensagem exibida: \"{texto}\""
            page.wait_for_timeout(250)
        return "bloqueado", "o formulário não avançou (sem mensagem visível — avaliar se o usuário entende o motivo)"
