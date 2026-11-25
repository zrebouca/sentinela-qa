"""Testes unitários rápidos (não abrem navegador). Rode com:  pytest -q"""

import os

import pytest

from sentinela import dados, ia
from sentinela.registro import Registro, Sugestao
from sentinela.relatorio import gerar
from sentinela.roteiro import ErroRoteiro, carregar_roteiro, detectar_tipo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROTEIROS = os.path.join(RAIZ, "roteiros")


def test_cpf_gerado_pelo_faker_e_valido():
    for _ in range(20):
        assert dados.cpf_valido(dados.fake.cpf())


def test_cpfs_invalidos_da_exploracao_sao_rejeitados():
    for codigo, _, valor, _ in dados.valores_invalidos("cpf"):
        if codigo.startswith("cpf_"):
            assert not dados.cpf_valido(valor)


def test_marcadores(monkeypatch):
    monkeypatch.setenv("SENHA_TESTE", "abc")
    assert dados.resolver("{env.SENHA_TESTE}") == "abc"
    assert dados.resolver("{env.NAO_EXISTE|padrao}") == "padrao"
    assert dados.resolver("Olá {dados.nome}", {"nome": "Ana"}) == "Olá Ana"
    assert "@" in dados.resolver("{faker.email}")
    with pytest.raises(ValueError):
        dados.resolver("{env.NAO_EXISTE}")


@pytest.mark.parametrize("arquivo", ["web_saucedemo.yaml", "web_the_internet.yaml", "desktop_calculadora.yaml"])
def test_roteiros_de_exemplo_sao_validos(arquivo):
    rot = carregar_roteiro(os.path.join(ROTEIROS, arquivo))
    assert rot.casos and all(c.passos for c in rot.casos)


def test_comando_desconhecido_da_erro_amigavel(tmp_path):
    arq = tmp_path / "r.yaml"
    arq.write_text("casos:\n  - id: CT01\n    passos:\n      - voar: alto\n", encoding="utf-8")
    with pytest.raises(ErroRoteiro, match="comando desconhecido 'voar'"):
        carregar_roteiro(str(arq))


def test_detectar_tipo():
    assert detectar_tipo("https://exemplo.com", None) == "web"
    assert detectar_tipo("C:/x/programa.exe", None) == "desktop"


def test_sem_chave_de_ia_apenas_avisa(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("SENTINELA_IA", "gemini")
    reg = Registro(pasta_saida=str(tmp_path), log=lambda m: None)
    ia.analisar(reg, "Sistema", "Objetivo")
    assert reg.sugestoes == [] and "GEMINI_API_KEY" in reg.avisos[0]


def test_relatorio_mostra_sugestoes(tmp_path):
    from datetime import datetime
    rot = carregar_roteiro(os.path.join(ROTEIROS, "web_saucedemo.yaml"))
    reg = Registro(pasta_saida=str(tmp_path), log=lambda m: None)
    reg.sugestoes.append(Sugestao("Texto", "Traduzir mensagens", "As mensagens estão em inglês.", "Alta"))
    reg.fim = datetime.now()
    caminhos = gerar(reg, rot, {"alvo": rot.alvo})
    html = open(caminhos["html"], encoding="utf-8").read()
    assert "Traduzir mensagens" in html and "Sugestão" in html
    assert os.path.isfile(caminhos["json"]) and os.path.isfile(caminhos["txt"])
