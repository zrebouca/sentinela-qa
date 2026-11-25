"""Testes unitários das regras de preço (Pytest) — rodados pelo Sentinela com tipo: suite."""

from decimal import Decimal

import pytest

from precos import aplicar_desconto, arredondar, frete, parcelas, subtotal


@pytest.mark.parametrize("valor, esperado", [(10.005, "10.01"), (10.004, "10.00"), (0.1 + 0.2, "0.30")])
def test_arredondamento_comercial(valor, esperado):
    assert arredondar(valor) == Decimal(esperado)


def test_subtotal_soma_preco_vezes_quantidade():
    itens = [{"preco": 24.90, "quantidade": 2}, {"preco": 2.50, "quantidade": 4}]
    assert subtotal(itens) == Decimal("59.80")


@pytest.mark.parametrize("quantidade", [0, -1, 1.5, "2"])
def test_subtotal_recusa_quantidade_invalida(quantidade):
    with pytest.raises(ValueError):
        subtotal([{"preco": 10, "quantidade": quantidade}])


def test_desconto_de_10_por_cento():
    assert aplicar_desconto(200, 10) == Decimal("180.00")


def test_desconto_negativo_e_recusado():
    with pytest.raises(ValueError):
        aplicar_desconto(100, -5)


def test_desconto_acima_de_100_e_recusado():
    """Encontra o BUG PLANTADO: hoje um desconto de 150% deixa o preço negativo."""
    with pytest.raises(ValueError):
        aplicar_desconto(100, 150)


@pytest.mark.parametrize("valor, uf, esperado", [(199.90, "BA", "0.00"), (100, "SP", "15.00"), (100, "ba", "25.00")])
def test_frete(valor, uf, esperado):
    assert frete(valor, uf) == Decimal(esperado)


def test_parcelas_somam_o_total_e_sobra_vai_na_primeira():
    lista = parcelas(100, 3)
    assert sum(lista) == Decimal("100.00")
    assert lista == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]


@pytest.mark.parametrize("vezes", [0, 13])
def test_parcelas_fora_do_limite(vezes):
    with pytest.raises(ValueError):
        parcelas(100, vezes)
