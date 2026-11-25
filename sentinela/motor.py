"""
Motor principal: junta tudo (roteiro -> executor -> exploração -> IA -> relatório).
É usado tanto pela linha de comando (cli.py) quanto pela janela (janela.py).
"""

import os
import platform
import re
import sys
import unicodedata
from datetime import datetime

from dotenv import load_dotenv

from sentinela import ia, relatorio
from sentinela.registro import Registro, ResultadoCaso
from sentinela.roteiro import ErroRoteiro, carregar_roteiro, detectar_tipo


def carregar_env():
    """Lê o arquivo .env da pasta atual e da pasta do executável (se houver).
    As variáveis já definidas no sistema têm prioridade."""
    load_dotenv(os.path.join(os.getcwd(), ".env"))
    if getattr(sys, "frozen", False):
        load_dotenv(os.path.join(os.path.dirname(sys.executable), ".env"))


def _slug(texto: str) -> str:
    """'Calculadora do Windows' -> 'calculadora_do_windows' (sem acentos)."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", sem_acento).strip("_").lower()[:40] or "teste"


def executar(caminho_roteiro: str, alvo: str | None = None, explorar: bool = False,
             usar_ia: bool = True, visivel: bool = False, saida: str = "relatorios",
             embutir_prints: bool = False, log=print, finalidade: str = "",
             somente: list[str] | None = None, pular: list[str] | None = None) -> tuple[Registro, dict]:
    carregar_env()
    roteiro = carregar_roteiro(caminho_roteiro)
    # Filtros opcionais de casos (ex.: --pular CT09 no CI)
    if somente:
        roteiro.casos = [c for c in roteiro.casos if c.id in somente]
    if pular:
        roteiro.casos = [c for c in roteiro.casos if c.id not in pular]
    if not roteiro.casos and roteiro.tipo != "suite":
        raise ErroRoteiro("Nenhum caso sobrou depois dos filtros --casos/--pular.")
    alvo = alvo or roteiro.alvo
    tipo = detectar_tipo(alvo, roteiro.tipo)

    pasta = os.path.join(saida, f"{_slug(roteiro.sistema)}_{datetime.now():%Y%m%d_%H%M%S}")
    registro = Registro(pasta_saida=os.path.abspath(pasta), log=log)
    log(f"Sentinela QA — {roteiro.sistema} ({tipo})")
    log(f"Alvo: {alvo}")
    log(f"Roteiro: {roteiro.arquivo} — {len(roteiro.casos)} caso(s)")

    if tipo == "web" and (roteiro.motor or "").lower() == "selenium":
        from sentinela.executor_selenium import ExecutorSelenium as Executor
    elif tipo == "web":
        from sentinela.executor_web import ExecutorWeb as Executor
    elif tipo == "suite":
        from sentinela.executor_suite import ExecutorSuite as Executor
    elif tipo == "api":
        from sentinela.executor_api import ExecutorApi as Executor
    else:
        from sentinela.executor_desktop import ExecutorDesktop as Executor

    executor = Executor(roteiro, alvo, registro, {"visivel": visivel})
    explorou = False
    try:
        executor.iniciar()
    except Exception as e:
        # Não conseguiu nem abrir o navegador/programa: todos os casos reprovam
        msg = f"Não foi possível iniciar o alvo: {e}"
        registro.avisar(msg)
        for caso in roteiro.casos:
            registro.casos.append(ResultadoCaso(
                caso.id, caso.descricao, caso.funcionalidade, [p.descricao for p in caso.passos],
                caso.esperado, msg, "REPROVADO", None, 0))
        registro.novo_defeito(descricao=msg, severidade="Crítica", passos_reproducao=[f"Abrir {alvo}"],
                              esperado="O alvo abre normalmente", obtido=msg, evidencia=None,
                              origem="Roteiro")
    else:
        try:
            executor.executar_todos()
            if explorar:
                if tipo == "web" and roteiro.exploracao:
                    from sentinela.exploracao import Explorador
                    Explorador(executor).rodar()
                    explorou = True
                else:
                    registro.avisar("Exploração pedida, mas o roteiro não tem a seção 'exploracao' (ou o alvo é desktop).")
        finally:
            executor.finalizar()

    registro.fim = datetime.now()

    ia_usada = False
    if usar_ia:
        ia.analisar(registro, roteiro.sistema, roteiro.objetivo)
        ia_usada = bool(registro.sugestoes)
    else:
        registro.avisar("Análise por IA não solicitada (--sem-ia).")

    ambiente = roteiro.ambiente or ""
    detalhe_amb = f"{getattr(executor, 'navegador', tipo)} · Windows {platform.release()}"
    info = {
        "alvo": alvo,
        "ambiente": f"{ambiente} ({detalhe_amb})" if ambiente else detalhe_amb,
        "explorou": explorou,
        "finalidade": finalidade,
        "ia_usada": ia_usada,
    }
    caminhos = relatorio.gerar(registro, roteiro, info, embutir_prints=embutir_prints)
    log("")
    log(f"Resultado: {registro.aprovados} aprovado(s), {registro.reprovados} reprovado(s), "
        f"{len(registro.defeitos)} defeito(s)")
    log(f"Relatório HTML: {caminhos['html']}")
    return registro, caminhos
