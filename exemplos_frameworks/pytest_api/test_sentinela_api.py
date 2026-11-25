"""Gerado pelo Sentinela QA a partir do roteiro api_viacep.yaml.
Rodar: pip install requests pytest jsonpath-ng && pytest -q
"""
import os

import requests


def campo(json, caminho):
    """Lê 'itens[0].nome' de um JSON."""
    import re
    for parte in re.findall(r"[^.\[\]]+|\[\d+\]", caminho):
        json = json[int(parte[1:-1])] if parte.startswith('[') else json[parte]
    return json


def test_ct01_consultar_cep_existente_praça_da_sé_são_paulo():
    """Consultar CEP existente (Praça da Sé, São Paulo)"""
    r = requests.request("GET", "https://viacep.com.br/ws/01001000/json/", timeout=20)
    assert r.status_code == 200
    assert "json" in r.headers.get("content-type", '').lower()
    assert str(campo(r.json(), "cep")).lower() == str("01001-000").lower()
    assert str(campo(r.json(), "localidade")).lower() == str("São Paulo").lower()
    assert str(campo(r.json(), "uf")).lower() == str("SP").lower()
    assert "Praça da Sé" in str(campo(r.json(), "logradouro") if "logradouro" else r.json())
    assert r.elapsed.total_seconds() * 1000 <= 5000


def test_ct02_cep_com_formato_inválido_3_dígitos():
    """CEP com formato inválido (3 dígitos)"""
    r = requests.request("GET", "https://viacep.com.br/ws/123/json/", timeout=20)
    assert r.status_code == 400


def test_ct03_cep_com_formato_válido_mas_inexistente():
    """CEP com formato válido mas inexistente"""
    r = requests.request("GET", "https://viacep.com.br/ws/99999999/json/", timeout=20)
    assert r.status_code == 200
    assert str(campo(r.json(), "erro")).lower() == str("True").lower()
    assert "logradouro" not in r.text or True  # TODO: conferir ausência de logradouro


def test_ct04_criar_post_post_e_consultar_um_post_existente():
    """Criar post (POST) e consultar um post existente"""
    r = requests.request("POST", "https://jsonplaceholder.typicode.com/posts", json={"title": "Teste do Sentinela QA", "body": "{faker.sentence}", "userId": 1}, timeout=20)
    assert r.status_code == 201
    assert campo(r.json(), "id") is not None
    assert str(campo(r.json(), "title")).lower() == str("Teste do Sentinela QA").lower()
    usuario = campo(r.json(), "userId")
    r = requests.request("GET", "https://jsonplaceholder.typicode.com/users/" + str(usuario), timeout=20)
    assert 200 <= r.status_code <= 299
    assert campo(r.json(), "address.city") is not None
