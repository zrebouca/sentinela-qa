"""Testes do auditor de banco, comandos de banco nos roteiros, qualidade extra e sistemas de treino."""

import json
import os
import socket
from datetime import datetime, timedelta

import pytest

from sentinela import banco_auditor as ba
from sentinela.motor import executar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mysql_no_ar() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", 3306)) == 0


# ------------------------------------------------------------------ auditor (sem banco real)
def test_previsao_de_crescimento():
    dados = {"tabelas": [{"nome": "vendas", "linhas": 1000, "dados": 1024 * 1024, "indices": 0,
                          "criada": datetime.now() - timedelta(days=100)}]}
    p = ba.prever(dados)[0]
    assert p["linhas_por_dia"] == 10.0 and p["linhas_em_1_ano"] == 1000 + 3650


def test_script_sql_comenta_o_que_precisa_de_revisao():
    aud = ba.Auditoria(host="x", banco="loja", versao="10", quando="hoje", achados=[
        {"id": "C001", "severidade": "Alta", "objeto": "produtos.preco", "problema": "FLOAT", "sql": "ALTER TABLE `produtos` MODIFY `preco` DECIMAL(12,2);", "aplicavel": True},
        {"id": "C002", "severidade": "Média", "objeto": "vendas.data", "problema": "texto", "sql": "ALTER TABLE `vendas` MODIFY `data` DATETIME;", "aplicavel": False},
    ])
    sql = ba.script_sql(aud)
    assert "\nALTER TABLE `produtos`" in sql and "-- ALTER TABLE `vendas`" in sql


def test_aplicar_recusa_correcao_manual():
    aud = ba.Auditoria(host="x", banco="loja", versao="10", quando="hoje",
                       achados=[{"id": "C002", "aplicavel": False, "sql": "x"}])
    with pytest.raises(ba.ErroBanco, match="revisão manual"):
        ba.aplicar(aud, ["C002"], "pasta")


def test_diagrama_mermaid():
    aud = ba.Auditoria(host="x", banco="loja", versao="10", quando="hoje",
                       tabelas=[{"nome": "produtos", "colunas": [{"nome": "id", "tipo": "int(11)", "chave": "PRI"}]}],
                       relacoes=[{"de": "vendas", "coluna": "produto_id", "para": "produtos"}])
    m = ba.diagrama_mermaid(aud)
    assert m.startswith("erDiagram") and "int id PK" in m and "produtos ||--o{ vendas" in m


# ------------------------------------------------------------------ auditor no MySQL do XAMPP (se estiver ligado)
@pytest.mark.integracao
@pytest.mark.skipif(not _mysql_no_ar(), reason="MySQL não está rodando")
def test_auditoria_encontra_problemas_plantados(tmp_path):
    from sentinela import xampp
    if not xampp.status().get("instalado"):
        pytest.skip("XAMPP não instalado")
    xampp.instalar_loja(log=lambda m: None)
    aud = ba.auditar("sentinela_loja", log=lambda m: None)
    textos = " | ".join(a["problema"] for a in aud.achados)
    for esperado in ("MyISAM", "FLOAT", "chave primária", "texto", "órfão", "MD5", "UNIQUE"):
        assert esperado in textos, esperado
    r = ba.gerar_relatorio(aud, str(tmp_path))
    assert os.path.isfile(r["html"]) and "erDiagram" in open(r["html"], encoding="utf-8").read()


# ------------------------------------------------------------------ comandos de banco no roteiro
def test_verificar_banco_so_aceita_leitura(tmp_path):
    from sentinela.erros import ErroPasso
    from sentinela.executor_banco import ComandosBanco
    c = ComandosBanco()
    with pytest.raises(ErroPasso, match="só aceita consultas de leitura"):
        c._consulta("DELETE FROM produtos")


# ------------------------------------------------------------------ qualidade: esquema e carga (servidor local)
def test_esquema_e_carga_em_api_local(tmp_path):
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    (tmp_path / "p.json").write_text(json.dumps({"id": 25, "name": "pikachu", "height": 4, "weight": 60,
                                                 "types": [{"slot": 1, "type": {"name": "electric"}}],
                                                 "abilities": []}), encoding="utf-8")
    os.makedirs(tmp_path / "esquemas")
    with open(os.path.join(RAIZ, "roteiros", "esquemas", "pokemon.json"), encoding="utf-8") as f:
        (tmp_path / "esquemas" / "pokemon.json").write_text(f.read(), encoding="utf-8")

    class Silencioso(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Silencioso, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    (tmp_path / "r.yaml").write_text(f"""
sistema: Qualidade API
tipo: api
alvo: {url}
casos:
  - id: CT01
    descricao: contrato e carga
    passos:
      - requisitar: GET /p.json
      - verificar_esquema: {{ arquivo: esquemas/pokemon.json }}
      - verificar_seguranca
      - teste_carga: {{ url: /p.json, requisicoes: 20, concorrencia: 4, p95_ms: 3000 }}
  - id: CT02
    descricao: esquema quebrado
    passos:
      - requisitar: GET /p.json
      - verificar_esquema: {{ esquema: {{ type: object, required: [nao_existe] }} }}
""", encoding="utf-8")
    try:
        reg, _ = executar(str(tmp_path / "r.yaml"), usar_ia=False, saida=str(tmp_path / "rel"), log=lambda m: None)
    finally:
        srv.shutdown()
    assert [c.status for c in reg.casos] == ["APROVADO", "REPROVADO"]
    assert "nao_existe" in reg.casos[1].obtido
    assert any(o.categoria == "Carga" for o in reg.observacoes)


# ------------------------------------------------------------------ sistemas de treino
def test_roteiros_novos_sao_validos():
    from sentinela.roteiro import carregar_roteiro
    for arq in ("web_loja_php.yaml", "desktop_estoque.yaml", "api_publicas.yaml"):
        rot = carregar_roteiro(os.path.join(RAIZ, "roteiros", arq))
        assert rot.casos, arq
    assert carregar_roteiro(os.path.join(RAIZ, "roteiros", "web_loja_php.yaml")).banco["nome"] == "sentinela_loja"


@pytest.mark.skipif(not os.path.isfile(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"), reason="sem csc.exe")
def test_compila_o_estoque_desktop(tmp_path):
    import shutil
    from sentinela.executor_desktop import resolver_exe
    fonte = os.path.join(RAIZ, "sistemas_treino", "estoque_desktop", "EstoqueDesktop.cs")
    shutil.copy(fonte, tmp_path / "EstoqueDesktop.cs")
    exe = resolver_exe(str(tmp_path / "EstoqueDesktop.exe"), str(tmp_path))
    assert os.path.isfile(exe) and os.path.getsize(exe) > 5000
