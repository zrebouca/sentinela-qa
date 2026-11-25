"""Regras de preço de uma loja — código de exemplo para TESTES UNITÁRIOS com Pytest.

BUG PLANTADO: aplicar_desconto aceita desconto acima de 100% (o preço fica negativo).
O teste test_desconto_acima_de_100_e_recusado encontra esse bug.
"""

from decimal import ROUND_HALF_UP, Decimal


def arredondar(valor) -> Decimal:
    """Arredonda para centavos do jeito do comércio (0,005 sobe)."""
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def subtotal(itens: list[dict]) -> Decimal:
    """Soma preço x quantidade. Quantidade precisa ser inteira e positiva."""
    total = Decimal("0")
    for item in itens:
        if not isinstance(item["quantidade"], int) or item["quantidade"] <= 0:
            raise ValueError("Quantidade deve ser um inteiro maior que zero")
        total += Decimal(str(item["preco"])) * item["quantidade"]
    return arredondar(total)


def aplicar_desconto(valor, percentual) -> Decimal:
    """Aplica um desconto percentual. Deveria recusar percentual < 0 ou > 100."""
    if percentual < 0:
        raise ValueError("Desconto não pode ser negativo")
    # (falta: if percentual > 100: raise ValueError(...))  <- bug plantado
    return arredondar(Decimal(str(valor)) * (1 - Decimal(str(percentual)) / 100))


def frete(subtotal_compra, uf: str) -> Decimal:
    """Frete grátis acima de R$ 199,90; senão R$ 15 no Sudeste e R$ 25 nas outras regiões."""
    if Decimal(str(subtotal_compra)) >= Decimal("199.90"):
        return Decimal("0.00")
    return Decimal("15.00") if uf.upper() in {"SP", "RJ", "MG", "ES"} else Decimal("25.00")


def parcelas(valor, vezes: int) -> list[Decimal]:
    """Divide em parcelas iguais; a diferença de centavos vai para a primeira parcela."""
    if not 1 <= vezes <= 12:
        raise ValueError("Parcelamento de 1 a 12 vezes")
    valor = arredondar(valor)
    base = (valor / vezes).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
    lista = [base] * vezes
    lista[0] += valor - base * vezes
    return lista
