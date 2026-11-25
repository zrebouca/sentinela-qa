"""Testes do painel web (Flask) com banco temporário — não executam navegador."""

import os
import shutil

import pytest

from sentinela.painel import banco

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    # Banco e .env isolados numa pasta temporária; exemplos vêm da pasta real "roteiros"
    monkeypatch.setattr(banco, "pasta_base", lambda: str(tmp_path))
    shutil.copytree(os.path.join(RAIZ, "roteiros"), tmp_path / "roteiros")
    banco.iniciar()
    from sentinela.painel.app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_boas_vindas_sem_projetos(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Importar exemplos" in r.get_data(as_text=True)


def test_importar_exemplos_e_paginas(cliente):
    cliente.post("/exemplos/importar")
    assert banco.consulta("SELECT COUNT(*) n FROM projetos", um=True)["n"] == 9
    assert banco.consulta("SELECT COUNT(*) n FROM roteiros", um=True)["n"] == 14
    for url in ["/", "/projetos", "/projetos/1", "/roteiros", "/roteiros/1", "/executar",
                "/execucoes", "/defeitos", "/configuracoes", "/ajuda", "/roteiros/novo?projeto=1", "/banco", "/api-tester", "/tipos-de-teste"]:
        assert cliente.get(url).status_code == 200, url


def test_cadastrar_projeto_valida_alvo(cliente):
    r = cliente.post("/projetos/novo", data={"nome": "X", "alvo": "nao-sei"}, follow_redirects=True)
    assert "Não sei se o alvo" in r.get_data(as_text=True)
    cliente.post("/projetos/novo", data={"nome": "Portal", "alvo": "https://exemplo.com", "finalidade": "Regressão"})
    p = banco.consulta("SELECT * FROM projetos WHERE nome='Portal'", um=True)
    assert p["tipo"] == "web" and p["finalidade"] == "Regressão"


def test_api_validar_roteiro(cliente):
    ok = cliente.post("/api/roteiros/validar", json={"conteudo": "casos:\n  - id: CT01\n    passos:\n      - abrir: /\n"}).get_json()
    assert ok["ok"] and ok["casos"][0]["id"] == "CT01"
    erro = cliente.post("/api/roteiros/validar", json={"conteudo": "casos:\n  - id: CT01\n    passos:\n      - voar: alto\n"}).get_json()
    assert not erro["ok"] and "voar" in erro["erro"]


def test_roteiro_invalido_nao_e_salvo(cliente):
    cliente.post("/projetos/novo", data={"nome": "Portal", "alvo": "https://exemplo.com"})
    r = cliente.post("/roteiros/novo", data={"projeto_id": "1", "nome": "Ruim", "conteudo": "casos: []"}, follow_redirects=True)
    assert "não foi salvo" in r.get_data(as_text=True)
    assert banco.consulta("SELECT COUNT(*) n FROM roteiros", um=True)["n"] == 0


def test_chave_ia_vai_para_env(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cliente.post("/configuracoes", data={"provedor": "gemini", "chave": "chave-de-teste-1234", "modelo": "m"})
    assert "GEMINI_API_KEY=chave-de-teste-1234" in (tmp_path / ".env").read_text(encoding="utf-8")
    html = cliente.get("/configuracoes").get_data(as_text=True)
    assert "chave-de-teste-1234" not in html and "1234" in html   # só os 4 últimos aparecem
