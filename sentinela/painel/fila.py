"""
Fila de execuções do painel.

As execuções rodam UMA DE CADA VEZ numa thread separada (o navegador
automatizado e a janela desktop não podem ser disputados por dois testes).
Enquanto roda, o log fica em memória para a tela "ao vivo"; no fim, tudo
é gravado no banco (resultado, log e defeitos).
"""

import os
import queue
import threading
import time
import traceback

from sentinela.painel import banco

_fila: queue.Queue = queue.Queue()
_logs: dict[int, list[str]] = {}       # log ao vivo de cada execução
_thread: threading.Thread | None = None


def log_ao_vivo(execucao_id: int) -> list[str]:
    return _logs.get(execucao_id, [])


def enfileirar(execucao_id: int):
    _logs[execucao_id] = ["Na fila — aguardando a vez..."]
    _fila.put(execucao_id)
    _garantir_thread()


def _garantir_thread():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_trabalhar, daemon=True, name="fila-sentinela")
        _thread.start()


def _trabalhar():
    while True:
        execucao_id = _fila.get()
        try:
            _rodar(execucao_id)
        except Exception:
            _logs.setdefault(execucao_id, []).append(traceback.format_exc())
        finally:
            _fila.task_done()


def _rodar(execucao_id: int):
    from sentinela.motor import executar

    ex = banco.consulta("SELECT * FROM execucoes WHERE id=?", (execucao_id,), um=True)
    proj = banco.consulta("SELECT * FROM projetos WHERE id=?", (ex["projeto_id"],), um=True)
    rot = banco.consulta("SELECT * FROM roteiros WHERE id=?", (ex["roteiro_id"],), um=True)
    linhas = _logs.setdefault(execucao_id, [])
    linhas.clear()

    base = banco.pasta_base()

    def log(msg):
        # Mostra caminhos relativos à pasta do Sentinela (não expõe o nome do usuário do Windows)
        linhas.append(str(msg).replace(base + os.sep, "").replace(base, "."))

    inicio = time.time()
    banco.executar("UPDATE execucoes SET status='Executando', iniciado_em=? WHERE id=?",
                   (banco.agora(), execucao_id))
    saida = os.path.join(banco.pasta_dados(), "relatorios")
    try:
        reg, caminhos = executar(
            rot["arquivo"], alvo=proj["alvo"], explorar=bool(ex["explorar"]),
            usar_ia=bool(ex["usar_ia"]), visivel=bool(ex["visivel"]), saida=saida,
            embutir_prints=False, log=log, finalidade=ex["finalidade"],
        )
    except Exception as e:
        log(f"\n✘ Erro: {e}")
        banco.executar("UPDATE execucoes SET status='Erro', finalizado_em=?, duracao_s=?, log=? WHERE id=?",
                       (banco.agora(), round(time.time() - inicio, 1), "\n".join(linhas), execucao_id))
        banco.registrar_atividade("execucao", f"Execução #{execucao_id} de {proj['nome']} terminou com erro",
                                  f"/execucoes/{execucao_id}")
        return

    pasta_rel = os.path.relpath(os.path.dirname(caminhos["html"]), banco.pasta_dados())
    banco.executar(
        "UPDATE execucoes SET status='Concluída', finalizado_em=?, duracao_s=?, total=?, aprovados=?,"
        " reprovados=?, defeitos=?, observacoes_qtd=?, sugestoes=?, pasta_relatorio=?, log=? WHERE id=?",
        (banco.agora(), round(time.time() - inicio, 1), len(reg.casos), reg.aprovados, reg.reprovados,
         len(reg.defeitos), len(reg.observacoes), len(reg.sugestoes), pasta_rel, "\n".join(linhas),
         execucao_id),
    )
    banco.salvar_defeitos(execucao_id, proj["id"], reg)
    resumo = f"{reg.aprovados}/{len(reg.casos)} aprovados, {len(reg.defeitos)} defeito(s)"
    banco.registrar_atividade("execucao", f"{proj['nome']}: execução #{execucao_id} concluída — {resumo}",
                              f"/execucoes/{execucao_id}")
