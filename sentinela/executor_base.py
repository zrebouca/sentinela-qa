"""
Lógica comum aos executores web e desktop:
roda os casos passo a passo, tira print de cada passo, decide
APROVADO/REPROVADO e abre um defeito quando algo falha.
"""

import time

from sentinela import dados as massa
from sentinela.registro import Registro, ResultadoCaso
from sentinela.roteiro import Caso, Passo, Roteiro


from sentinela.erros import ErroPasso  # noqa: F401  (outros módulos importam daqui)
from sentinela.executor_banco import ComandosBanco


class ExecutorBase(ComandosBanco):
    tipo = "base"

    def __init__(self, roteiro: Roteiro, alvo: str, registro: Registro, opcoes: dict):
        self.roteiro = roteiro
        self.alvo = alvo
        self.registro = registro
        self.opcoes = opcoes
        self.tempo_limite_ms = int(roteiro.tempo_limite * 1000)
        self.caso_atual = "-"
        # Resolve uma vez os valores da seção "dados:" (ex.: nome gerado pelo Faker)
        self.dados = {k: massa.resolver(v) for k, v in roteiro.dados.items()}

    # Métodos que cada executor implementa ------------------------------------
    def iniciar(self): ...
    def finalizar(self): ...
    def preparar_caso(self, caso: Caso): ...
    def encerrar_caso(self, caso: Caso): ...
    def capturar(self, comando: str) -> str | None:
        return None

    # -------------------------------------------------------------------------
    def resolver(self, valor):
        """Troca {faker.x}, {env.x}, {dados.x} pelos valores reais."""
        try:
            return massa.resolver(valor, self.dados)
        except ValueError as e:
            raise ErroPasso(str(e)) from e

    def executar_passo(self, passo: Passo) -> str:
        """Chama o método cmd_<comando> do executor. Devolve uma mensagem
        curta do que foi obtido (usada no campo 'Obtido' do relatório)."""
        metodo = getattr(self, f"cmd_{passo.comando}", None)
        if metodo is None:
            raise ErroPasso(f"O comando '{passo.comando}' não é suportado em testes {self.tipo}")
        args = self.resolver(passo.args)
        return metodo(args) or "ok"

    def executar_caso(self, caso: Caso) -> ResultadoCaso:
        self.caso_atual = caso.id
        self.registro.log(f"\n▶ {caso.id} — {caso.descricao}")
        inicio = time.time()
        passos = self.roteiro.antes_de_cada + caso.passos
        verificacoes, falha, ultimo_print = [], None, None
        executados = []

        try:
            self.preparar_caso(caso)
        except Exception as e:  # ex.: navegador não abriu
            falha = (0, "Preparar o caso", f"Não foi possível preparar o caso: {e}")

        for n, passo in enumerate(passos, start=1):
            if falha:
                break
            t0 = time.time()
            executados.append(passo.descricao)
            try:
                msg = self.executar_passo(passo)
                status, detalhe = "ok", msg
                if passo.comando.startswith("verificar"):
                    verificacoes.append(msg)
            except Exception as e:
                status, detalhe = "falha", self.traduzir_erro(e, passo)
                falha = (n, passo.descricao, detalhe)
            ultimo_print = self.capturar(passo.comando if status == "ok" else f"{passo.comando}_FALHA")
            self.registro.registrar_acao(
                caso.id, passo.comando, passo.descricao, status, ultimo_print,
                int((time.time() - t0) * 1000), detalhe,
            )

        try:
            self.encerrar_caso(caso)
        except Exception:
            pass

        if falha:
            n, desc, detalhe = falha
            obtido = f"Falhou no passo {n} ({desc}): {detalhe}"
            status = "REPROVADO"
            self.registro.novo_defeito(
                descricao=f"{caso.id} — {caso.descricao}: {detalhe}",
                severidade=caso.severidade,
                passos_reproducao=executados,
                esperado=caso.esperado,
                obtido=obtido,
                evidencia=ultimo_print,
                origem="Roteiro",
                caso_id=caso.id,
            )
        else:
            status = "APROVADO"
            obtido = "; ".join(verificacoes) if verificacoes else "Todos os passos executados sem erro"

        resultado = ResultadoCaso(
            id=caso.id, descricao=caso.descricao, funcionalidade=caso.funcionalidade,
            passos=[p.descricao for p in passos], esperado=caso.esperado,
            obtido=obtido, status=status, print=ultimo_print,
            duracao_s=round(time.time() - inicio, 1),
        )
        self.registro.casos.append(resultado)
        self.registro.log(f"  → {status}")
        return resultado

    def traduzir_erro(self, erro: Exception, passo: Passo) -> str:
        """Cada executor pode deixar a mensagem de erro mais amigável."""
        return str(erro).strip().splitlines()[0] if str(erro).strip() else type(erro).__name__

    def executar_todos(self):
        try:
            for caso in self.roteiro.casos:
                self.executar_caso(caso)
        finally:
            self.fechar_banco()
