"""Testes de API, Gherkin, exportação de defeitos e integração com o site de treino local."""

import functools
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentinela.gherkin import feature_para_dict, roteiro_para_feature
from sentinela.motor import executar
from sentinela.roteiro import carregar_roteiro

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _servidor(pasta):
    class Silencioso(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Silencioso, directory=str(pasta)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ------------------------------------------------------------------ API
def test_executor_api_com_servidor_local(tmp_path):
    (tmp_path / "cep.json").write_text(json.dumps({"cep": "01001-000", "localidade": "São Paulo",
                                                    "bairros": [{"nome": "Sé"}]}), encoding="utf-8")
    srv, url = _servidor(tmp_path)
    roteiro = tmp_path / "api.yaml"
    roteiro.write_text(f"""
sistema: API local
tipo: api
alvo: {url}
casos:
  - id: CT01
    descricao: Consulta ok
    passos:
      - requisitar: GET /cep.json
      - verificar_status: 200
      - verificar_json: {{ campo: localidade, valor: São Paulo }}
      - verificar_json: {{ campo: "bairros[0].nome", valor: Sé }}
      - guardar: {{ campo: cep, como: cep }}
      - verificar_tempo: {{ maximo_ms: 5000 }}
  - id: CT02
    descricao: Recurso inexistente
    passos:
      - requisitar: GET /nao-existe.json
      - verificar_status: 200
""", encoding="utf-8")
    try:
        reg, _ = executar(str(roteiro), usar_ia=False, saida=str(tmp_path / "rel"), log=lambda m: None)
    finally:
        srv.shutdown()
    assert [c.status for c in reg.casos] == ["APROVADO", "REPROVADO"]
    assert "404" in reg.casos[1].obtido
    assert reg.casos[0].print.endswith(".json")          # evidência da API é a resposta salva


# ------------------------------------------------------------------ Gherkin
def test_gherkin_vira_roteiro():
    texto = """# language: pt
# alvo: http://exemplo.test
Funcionalidade: Login
  @CT07 @alta
  Cenário: Entrar
    Dado que eu acesso "/login"
    Quando eu preencho "#usuario" com "ana"
    E eu clico em "Entrar"
    Então devo ver a mensagem de sucesso "Bem-vinda"
    E a URL deve conter "/painel"
"""
    d = feature_para_dict(texto)
    caso = d["casos"][0]
    assert d["alvo"] == "http://exemplo.test" and caso["id"] == "CT07" and caso["severidade"] == "Alta"
    comandos = [next(k for k in p if k != "descricao") for p in caso["passos"]]
    assert comandos == ["abrir", "preencher", "clicar", "verificar_mensagem", "verificar_url"]


def test_yaml_para_gherkin_e_volta(tmp_path):
    rot = carregar_roteiro(os.path.join(RAIZ, "roteiros", "web_site_treino.yaml"))
    arq = tmp_path / "conv.feature"
    arq.write_text(roteiro_para_feature(rot), encoding="utf-8")
    convertido = carregar_roteiro(str(arq))
    assert [c.id for c in convertido.casos] == [c.id for c in rot.casos]


# ------------------------------------------------------------------ exportação de defeitos
def test_exportar_csv_e_texto_jira(tmp_path, monkeypatch):
    import shutil
    from sentinela.painel import banco
    monkeypatch.setattr(banco, "pasta_base", lambda: str(tmp_path))
    shutil.copytree(os.path.join(RAIZ, "roteiros"), tmp_path / "roteiros")
    banco.iniciar()
    from sentinela.painel.app import app, texto_jira
    cli = app.test_client()
    cli.post("/exemplos/importar")
    eid = banco.executar("INSERT INTO execucoes (projeto_id, roteiro_id, status, criado_em) VALUES (1,1,'Concluída',?)", (banco.agora(),))
    banco.executar("INSERT INTO defeitos (execucao_id, projeto_id, codigo, descricao, severidade, status, origem, passos,"
                   " esperado, obtido, criado_em, atualizado_em) VALUES (?,1,'BUG-001','CEP aceita letras','Baixa','Aberto',"
                   "'Exploração','[\"Abrir /checkout\", \"Preencher CEP\"]','Bloquear','Aceitou',?,?)",
                   (eid, banco.agora(), banco.agora()))
    csv = cli.get("/defeitos/exportar.csv").get_data(as_text=True)
    assert "BUG-001;" in csv and "1. Abrir /checkout | 2. Preencher CEP" in csv
    azure = cli.get("/defeitos/exportar_azure.csv").get_data(as_text=True)
    assert "Bug,BUG-001 - CEP aceita letras,4 - Low," in azure and "<li>Abrir /checkout</li>" in azure
    html = cli.get("/defeitos/1").get_data(as_text=True)
    assert "h3. BUG-001" in html and "# Abrir /checkout" in html


# ------------------------------------------------------------------ integração (abre o Chrome de verdade)
@pytest.mark.integracao
def test_site_treino_de_ponta_a_ponta(tmp_path):
    srv, url = _servidor(os.path.join(RAIZ, "site_treino"))
    try:
        reg, caminhos = executar(os.path.join(RAIZ, "roteiros", "web_site_treino.yaml"), alvo=url,
                                 explorar=True, usar_ia=False, saida=str(tmp_path), log=lambda m: None)
    finally:
        srv.shutdown()
    assert reg.reprovados == 0 and reg.aprovados == 6
    # A exploração deve achar exatamente o bug plantado: telefone sem validação
    assert len(reg.defeitos) == 1 and "#telefone" in reg.defeitos[0].descricao
    assert os.path.isfile(caminhos["html"])


# ------------------------------------------------------------------ segurança (varredura OWASP)
def test_varredura_seguranca_acha_vulnerabilidades():
    """Sobe um servidor PROPOSITALMENTE vulnerável e confere que a varredura acha os pontos
    certos e dá observação positiva nas rotas seguras."""
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlsplit, parse_qs

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _s(self, code, body, ctype="text/html; charset=utf-8"):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            p = urlsplit(self.path)
            termo = (parse_qs(p.query).get("busca") or [""])[0]
            if p.path == "/":
                return self._s(200, "<html><head><script src='/app.js'></script></head><body>loja</body></html>")
            if p.path == "/app.js":
                return self._s(200, "const K='sk_live_abcdef0123456789xyz';", "application/javascript")
            if p.path == "/.env":
                return self._s(200, "DB_PASSWORD=segredo\nAPP_KEY=x\n", "text/plain")
            if p.path == "/admin":
                return self._s(200, "<h1>Painel administrativo</h1>" + "x" * 300)
            if p.path == "/produtos.php":
                if "'" in termo or '"' in termo:
                    return self._s(200, "Warning: mysqli_query(): You have an error in your SQL syntax near " + termo)
                return self._s(200, f"<div>busca: {termo}</div>")
            if p.path == "/seguro.php":
                t = termo.replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
                return self._s(200, f"<div>busca: {t}</div>")
            return self._s(404, "nao")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            if urlsplit(self.path).path == "/login.php":
                return self._s(200, _json.dumps({"ok": False, "perfil": "cliente"}), "application/json")
            if urlsplit(self.path).path == "/perfil.php":
                return self._s(200, "ok")
            return self._s(404, "nao")

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    from sentinela.seguranca import ComandosSeguranca

    class Reg:
        def __init__(s):
            s.defeitos, s.obs = [], []

        def log(s, *a):
            pass

        def observar(s, cat, txt, *a):
            s.obs.append(txt)

        def novo_defeito(s, **k):
            s.defeitos.append(k)

    class Ex(ComandosSeguranca):
        page = None

        def __init__(s):
            s.registro, s.caso_atual, s.alvo = Reg(), "SEG", base

    ex = Ex()
    try:
        ex.cmd_varredura_seguranca({
            "base": base,
            "injecao": [{"url": "/produtos.php", "parametro": "busca"},
                        {"url": "/seguro.php", "parametro": "busca"}],
            "login": {"url": "/login.php", "campos": {"email": "a", "senha": "b"}, "campo_senha": "senha"},
            "upload": {"url": "/perfil.php", "campo": "foto"},
        })
    finally:
        srv.shutdown()

    pontos = {int(d["descricao"].split("#")[1].split("]")[0]) for d in ex.registro.defeitos}
    assert {1, 3, 8, 9, 11, 12, 13, 14} <= pontos, f"pontos achados: {sorted(pontos)}"
    # rota segura não vira defeito
    assert any("/seguro.php" in o and "sem sinais de SQL" in o for o in ex.registro.obs)
    assert any("/seguro.php" in o and "escapada" in o for o in ex.registro.obs)


# ------------------------------------------------------------------ verificar_links (bug dos falsos positivos)
def test_classificar_link_separa_quebrado_de_bloqueio():
    from sentinela.executor_qualidade import _classificar_link
    # redirecionamentos e 200 = ok (links reais que o robô marcava como quebrados)
    for s in (200, 301, 302, 307):
        assert _classificar_link(s, None) == "ok", s
    # bloqueio a robôs / método não aceito = NÃO é link quebrado
    for s in (400, 401, 403, 405, 429):
        assert _classificar_link(s, None) == "bloqueio", s
    # quebrado de verdade (inclui 526 de SSL do Cloudflare e 404)
    for s in (404, 410, 500, 503, 526):
        assert _classificar_link(s, None) == "quebrado", s
    # erros de rede: DNS/SSL = quebrado; timeout/outros = não verificável
    assert _classificar_link(None, "getaddrinfo ENOTFOUND foo.invalido") == "quebrado"
    assert _classificar_link(None, "net::ERR_CERT_DATE_INVALID") == "quebrado"
    assert _classificar_link(None, "Timeout 12000ms exceeded") == "bloqueio"


# ------------------------------------------------------------------ IA (escolha de modelo e resiliência)
def test_resolver_modelo_escolhe_da_lista_liberada():
    from sentinela import ia

    class _Modelo:
        def __init__(self, nome):
            self.name, self.supported_actions = "models/" + nome, ["generateContent"]

    class _Cliente:
        class models:
            @staticmethod
            def list():
                return [_Modelo("gemini-2.5-flash"), _Modelo("gemini-3.8-flash"),
                        _Modelo("gemini-3.8-flash-lite"), _Modelo("gemini-pro")]

    class _Reg:
        def __init__(self):
            self.avisos = []

        def avisar(self, t):
            self.avisos.append(t)

    reg = _Reg()
    # modelo configurado que não existe -> cai para o flash mais novo e avisa
    assert ia._resolver_modelo(_Cliente(), "gemini-3.5-flash", reg) == "gemini-3.8-flash"
    assert reg.avisos and "indisponível" in reg.avisos[0]
    # modelo configurado que existe -> respeita
    assert ia._resolver_modelo(_Cliente(), "gemini-2.5-flash", _Reg()) == "gemini-2.5-flash"
    # sem configurar -> flash mais novo da lista
    assert ia._resolver_modelo(_Cliente(), "", _Reg()) == "gemini-3.8-flash"


def test_relatorio_sai_mesmo_quando_ia_falha(tmp_path, monkeypatch):
    """A falha (ou travamento) da IA nunca pode impedir o relatório de ser salvo."""
    (tmp_path / "cep.json").write_text(json.dumps({"localidade": "São Paulo"}), encoding="utf-8")
    srv, url = _servidor(tmp_path)
    roteiro = tmp_path / "api.yaml"
    roteiro.write_text(f"""
sistema: API local
tipo: api
alvo: {url}
objetivo: teste de resiliência
casos:
  - id: CT01
    descricao: Consulta ok
    passos:
      - requisitar: GET /cep.json
      - verificar_status: 200
""", encoding="utf-8")

    def explode(*a, **k):
        raise RuntimeError("IA caiu de propósito no teste")

    monkeypatch.setattr("sentinela.ia.analisar", explode)
    try:
        reg, caminhos = executar(str(roteiro), usar_ia=True, saida=str(tmp_path / "rel"), log=lambda m: None)
    finally:
        srv.shutdown()
    assert os.path.isfile(caminhos["html"])                 # relatório salvo apesar da IA falhar
    assert [c.status for c in reg.casos] == ["APROVADO"]
    assert any("IA falhou" in a for a in reg.avisos)
