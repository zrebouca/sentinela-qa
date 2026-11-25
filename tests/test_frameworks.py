"""Testes da integração com outros frameworks: Postman, exportadores, suítes (JUnit XML) e Testar API."""

import functools
import json
import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentinela.exportar import FORMATOS, exportar
from sentinela.motor import executar
from sentinela.postman import exportar_colecao, importar_colecao
from sentinela.roteiro import carregar_roteiro

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _servidor(pasta):
    class Silencioso(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Silencioso, directory=str(pasta)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ------------------------------------------------------------------ Postman
def test_importa_colecao_do_postman_com_testes():
    colecao = {
        "info": {"name": "Minha API"},
        "variable": [{"key": "baseUrl", "value": "https://api.exemplo.test"}],
        "item": [{"name": "Pasta", "item": [{
            "name": "Login",
            "request": {"method": "POST", "url": {"raw": "{{baseUrl}}/login"},
                        "body": {"mode": "raw", "raw": "{\"usuario\": \"ana\"}"}},
            "event": [{"listen": "test", "script": {"exec": [
                "pm.test('ok', function () { pm.response.to.have.status(200); });",
                "pm.expect(pm.response.responseTime).to.be.below(500);",
                "var jsonData = pm.response.json();",
                "pm.expect(jsonData.usuario.nome).to.eql(\"Ana\");",
                "pm.collectionVariables.set(\"token\", jsonData.token);"]}}]}]}]}
    texto, est = importar_colecao(colecao)
    assert est["casos"] == 1 and est["nao_convertidas"] == 0
    for esperado in ("verificar_status: 200", "maximo_ms: 500", "campo: usuario.nome", "como: token", "{dados.baseUrl}/login"):
        assert esperado in texto, esperado


def test_exporta_roteiro_para_postman():
    rot = carregar_roteiro(os.path.join(RAIZ, "roteiros", "api_viacep.yaml"))
    col = exportar_colecao(rot)
    assert col["info"]["schema"].endswith("v2.1.0/collection.json")
    testes = " ".join(" ".join(i["event"][0]["script"]["exec"]) for i in col["item"])
    assert "pm.response.to.have.status(200)" in testes and "pm.collectionVariables.set" in testes
    assert col["item"][0]["request"]["url"].startswith("{{baseUrl}}")


# ------------------------------------------------------------------ exportadores
@pytest.mark.parametrize("formato", sorted(FORMATOS))
def test_todos_os_formatos_geram_arquivos(formato):
    rot = carregar_roteiro(os.path.join(RAIZ, "roteiros", "web_site_treino.yaml" if formato not in ("pytest-api", "restassured", "postman")
                                        else "api_viacep.yaml"))
    arquivos = exportar(rot, formato)
    assert arquivos and all(conteudo.strip() for conteudo in arquivos.values())


def test_playwright_ts_tem_testes_e_config():
    arquivos = exportar(carregar_roteiro(os.path.join(RAIZ, "roteiros", "web_site_treino.yaml")), "playwright-ts")
    spec = arquivos["tests/sentinela.spec.ts"]
    assert spec.count("test('CT") == 6 and "channel: 'chrome'" in arquivos["playwright.config.ts"]
    assert "process.env.TREINO_SENHA" in spec            # segredo vira variável de ambiente, não texto fixo


# ------------------------------------------------------------------ suíte de outro framework (Pytest → JUnit XML)
def test_suite_pytest_entra_no_relatorio(tmp_path):
    pasta = tmp_path / "suite"
    shutil.copytree(os.path.join(RAIZ, "exemplos_frameworks", "pytest_unitario"), pasta,
                    ignore=shutil.ignore_patterns("resultados", "__pycache__", ".pytest_cache"))
    (tmp_path / "r.yaml").write_text("sistema: Suíte\ntipo: suite\nferramenta: pytest\npasta: suite\n", encoding="utf-8")
    reg, _ = executar(str(tmp_path / "r.yaml"), usar_ia=False, saida=str(tmp_path / "rel"), log=lambda m: None)
    assert reg.aprovados == 16 and reg.reprovados == 1
    assert "desconto_acima_de_100" in reg.defeitos[0].descricao


# ------------------------------------------------------------------ tela Testar API
def test_testar_api_com_verificacoes(tmp_path, monkeypatch):
    from sentinela.painel import banco
    monkeypatch.setattr(banco, "pasta_base", lambda: str(tmp_path))
    banco.iniciar()
    from sentinela.painel.app import app
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "u.json").write_text(json.dumps({"id": 7, "nome": "Ana", "token": "abc"}), encoding="utf-8")
    srv, url = _servidor(tmp_path / "api")
    try:
        r = app.test_client().post("/api/tester/enviar", json={
            "metodo": "GET", "url": url + "/u.json", "verificacoes": [
                {"tipo": "status", "valor": "200"}, {"tipo": "json_igual", "campo": "nome", "valor": "Ana"},
                {"tipo": "json_igual", "campo": "id", "valor": "8"}, {"tipo": "guardar", "campo": "token", "valor": "tk"},
                {"tipo": "esquema", "valor": "{\"type\": \"object\", \"required\": [\"id\"]}"}]}).get_json()
    finally:
        srv.shutdown()
    assert r["status"] == 200 and [x["ok"] for x in r["resultados"]] == [True, True, False, True, True]
    assert r["variaveis"] == {"tk": "abc"}
