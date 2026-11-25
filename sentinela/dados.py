"""
Massa de dados de teste.

- Substitui marcadores nos valores do roteiro:
    {faker.email}          -> e-mail falso gerado pelo Faker (pt_BR)
    {faker.cpf}            -> CPF válido falso
    {env.MINHA_SENHA}      -> valor da variável de ambiente (ou do arquivo .env)
    {env.MINHA_SENHA|abc}  -> idem, usando "abc" se a variável não existir
    {dados.nome}           -> valor definido na seção "dados:" do roteiro
- Gera valores INVÁLIDOS para a exploração (campos vazios, CPF inválido etc.).
"""

import os
import re

from faker import Faker

fake = Faker("pt_BR")

# Encontra {grupo.nome} ou {grupo.nome|padrao}
_MARCADOR = re.compile(r"\{(faker|env|dados)\.([A-Za-z0-9_]+)(?:\|([^}]*))?\}")


def gerar_faker(metodo: str) -> str:
    """Chama um gerador do Faker pelo nome (ex.: 'email', 'cpf', 'name')."""
    gerador = getattr(fake, metodo, None)
    if gerador is None or not callable(gerador):
        raise ValueError(f"Gerador Faker desconhecido: '{metodo}'")
    return str(gerador())


def resolver(valor, dados: dict | None = None):
    """Troca os marcadores {faker.x}, {env.x} e {dados.x} pelo valor real.

    Funciona com textos, listas e dicionários (recursivo). Outros tipos
    (números, booleanos) são devolvidos sem alteração.
    """
    dados = dados or {}
    if isinstance(valor, dict):
        return {k: resolver(v, dados) for k, v in valor.items()}
    if isinstance(valor, list):
        return [resolver(v, dados) for v in valor]
    if not isinstance(valor, str):
        return valor

    def trocar(m: re.Match) -> str:
        grupo, nome, padrao = m.group(1), m.group(2), m.group(3)
        if grupo == "faker":
            return gerar_faker(nome)
        if grupo == "env":
            achado = os.getenv(nome)
            if achado is None:
                if padrao is None:
                    raise ValueError(
                        f"Variável de ambiente '{nome}' não definida (configure no .env)"
                    )
                return padrao
            return achado
        # grupo == "dados"
        if nome not in dados:
            raise ValueError(f"'{nome}' não existe na seção 'dados' do roteiro")
        return str(dados[nome])

    return _MARCADOR.sub(trocar, valor)


# ---------------------------------------------------------------------------
# Valores válidos e inválidos por tipo de campo (usados na exploração)
# ---------------------------------------------------------------------------

def valor_valido(tipo: str) -> str:
    """Um valor CORRETO para o tipo de campo — usado para preencher os
    outros campos enquanto um campo específico recebe o valor inválido."""
    geradores = {
        "nome": fake.first_name,
        "sobrenome": fake.last_name,
        "email": fake.email,
        "cpf": fake.cpf,
        "cep": lambda: fake.postcode().replace("-", ""),
        "telefone": fake.cellphone_number,
        "numero": lambda: str(fake.random_int(1, 999)),
        "senha": lambda: fake.password(length=12),
        "data": lambda: fake.date(pattern="%d/%m/%Y"),
        "texto": lambda: fake.word(),
    }
    return str(geradores.get(tipo, geradores["texto"])())


# Cada tentativa: (código, descrição legível, valor, severidade se for aceito)
_COMUNS = [
    ("vazio", "campo vazio", "", "Alta"),
    ("espacos", "apenas espaços", "     ", "Média"),
    ("especiais", "caracteres especiais/HTML", "<script>alert(1)</script>'\"%;", "Média"),
    ("longo", "texto muito longo (300 caracteres)", "A" * 300, "Baixa"),
]

_POR_TIPO = {
    "email": [
        ("email_sem_arroba", "e-mail sem @", "usuario.exemplo.com", "Média"),
        ("email_incompleto", "e-mail incompleto", "usuario@", "Média"),
    ],
    "cpf": [
        ("cpf_repetido", "CPF com dígitos repetidos", "111.111.111-11", "Alta"),
        ("cpf_digito", "CPF com dígito verificador errado", "123.456.789-00", "Alta"),
        ("cpf_letras", "CPF com letras", "abc.def.ghi-jk", "Média"),
    ],
    "cep": [
        ("cep_letras", "CEP com letras", "ABCDE-FGH", "Baixa"),
        ("cep_curto", "CEP curto demais", "123", "Baixa"),
    ],
    "nome": [
        ("nome_numeros", "nome só com números", "12345", "Baixa"),
    ],
    "numero": [
        ("num_negativo", "número negativo", "-1", "Média"),
        ("num_zero", "zero", "0", "Baixa"),
        ("num_gigante", "número gigante", "99999999999999999999", "Média"),
        ("num_letras", "letras em campo numérico", "abc", "Média"),
    ],
    "telefone": [
        ("tel_letras", "telefone com letras", "(11) abcde-fghi", "Baixa"),
        ("tel_curto", "telefone curto demais", "123", "Baixa"),
    ],
    "senha": [
        ("senha_curta", "senha de 1 caractere", "a", "Média"),
    ],
}


def valores_invalidos(tipo: str, somente: list[str] | None = None) -> list[tuple]:
    """Lista de tentativas inválidas para um tipo de campo.

    'somente' permite escolher no roteiro quais tentativas rodar
    (ex.: ["vazio", "cep_letras"]) para a exploração não demorar.
    """
    tentativas = _COMUNS + _POR_TIPO.get(tipo, [])
    if somente:
        tentativas = [t for t in tentativas if t[0] in somente]
    return tentativas


def cpf_valido(cpf: str) -> bool:
    """Valida CPF pelo cálculo dos dígitos verificadores (útil em testes)."""
    numeros = [int(c) for c in cpf if c.isdigit()]
    if len(numeros) != 11 or len(set(numeros)) == 1:
        return False
    for posicao in (9, 10):
        soma = sum(n * (posicao + 1 - i) for i, n in enumerate(numeros[:posicao]))
        digito = (soma * 10) % 11 % 10
        if digito != numeros[posicao]:
            return False
    return True
