"""
Leitura e validação do roteiro de teste (arquivo .yaml, .yml ou .json).

Um roteiro tem um cabeçalho (sistema, versão, responsável...), a lista de
funcionalidades com critérios de aceitação e a lista de casos de teste.
Cada caso tem passos. Cada passo é UM comando, por exemplo:

    - clicar: "#login-button"
    - preencher: { campo: "#user-name", valor: "standard_user" }
    - verificar_texto: "Products"
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

# Nomes alternativos aceitos -> nome oficial do comando.
# Assim o QA pode escrever do jeito que achar mais natural.
APELIDOS = {
    "acessar": "abrir", "navegar": "abrir", "ir_para": "abrir",
    "login": "logar", "entrar": "logar",
    "procurar": "buscar", "pesquisar": "buscar",
    "preencher_formulario": "cadastrar", "formulario": "cadastrar",
    "escrever": "digitar",
    "tecla": "apertar_tecla", "pressionar": "apertar_tecla",
    "hover": "passar_mouse", "mouse_sobre": "passar_mouse",
    "arrastar_e_soltar": "arrastar",
    "aguardar": "esperar",
    "escolher": "selecionar",
    "upload": "enviar_arquivo",
    "clique": "clicar", "duplo_clique": "clicar_duplo",
    "print": "capturar_tela", "screenshot": "capturar_tela",
    "verificar": "verificar_texto", "ver_texto": "verificar_texto",
    "verificar_existe": "verificar_elemento",
    "verificar_ausente": "verificar_sem_texto",
    "requisicao": "requisitar", "chamar_api": "requisitar", "api": "requisitar",
    "status": "verificar_status", "verificar_resposta": "verificar_json",
    "ux": "auditoria_ux", "auditar_ux": "auditoria_ux", "auditoria_design": "auditoria_ux",
    "verificar_ux": "auditoria_ux", "design": "auditoria_ux",
}

COMANDOS = {
    # navegação e ações
    "abrir", "clicar", "clicar_duplo", "passar_mouse", "preencher", "digitar",
    "apertar_tecla", "esperar", "selecionar", "marcar", "desmarcar",
    "enviar_arquivo", "arrastar", "rolar", "logar", "cadastrar", "buscar",
    "recarregar", "voltar", "capturar_tela", "fechar",
    # verificações (asserções)
    "verificar_texto", "verificar_sem_texto", "verificar_elemento",
    "verificar_url", "verificar_titulo", "verificar_valor", "verificar_mensagem",
    # API (REST/JSON)
    "requisitar", "verificar_status", "verificar_json", "verificar_tempo", "verificar_cabecalho", "guardar",
    # banco de dados
    "verificar_banco", "consultar_banco", "preparar_banco",
    # qualidade extra (bibliotecas gratuitas)
    "verificar_acessibilidade", "verificar_esquema", "comparar_visual", "verificar_desempenho",
    "teste_carga", "verificar_seguranca", "verificar_links",
    # segurança de aplicação (OWASP) — só contra sistemas seus
    "varredura_seguranca", "verificar_injecao",
    # auditoria de UI/UX (mede o design real e sugere a correção)
    "auditoria_ux",
}

SEVERIDADES = ["Crítica", "Alta", "Média", "Baixa"]


class ErroRoteiro(Exception):
    """Erro de escrita do roteiro, com mensagem amigável em português."""


@dataclass
class Passo:
    comando: str
    args: Any
    descricao: str


@dataclass
class Caso:
    id: str
    descricao: str
    passos: list[Passo]
    esperado: str = ""
    funcionalidade: str = ""
    severidade: str = "Média"


@dataclass
class Roteiro:
    arquivo: str
    pasta: str                      # pasta do roteiro (para caminhos relativos)
    sistema: str
    versao: str
    responsavel: str
    ambiente: str
    objetivo: str
    alvo: str | None
    tipo: str | None                # "web" ou "desktop" (detectado se vazio)
    janela: str | None              # desktop: título da janela (regex)
    tempo_limite: float             # segundos por passo
    atributo_testid: str
    dados: dict
    funcionalidades: list[dict]
    antes_de_cada: list[Passo]
    casos: list[Caso]
    exploracao: dict | None = field(default=None)
    banco: dict | None = field(default=None)
    dispositivo: str | None = field(default=None)
    navegador: str | None = field(default=None)
    motor: str | None = field(default=None)       # web: playwright (padrão) ou selenium
    suite: dict | None = field(default=None)      # tipo suite: ferramenta, pasta, comando, junit, preparar


def descrever(comando: str, args: Any) -> str:
    """Gera uma descrição legível do passo, para o relatório."""
    def txt(chave, padrao=""):
        return args.get(chave, padrao) if isinstance(args, dict) else args

    modelos = {
        "abrir": lambda: f"Abrir {txt('url') or 'o alvo'}",
        "clicar": lambda: f"Clicar em '{txt('alvo')}'",
        "clicar_duplo": lambda: f"Dar duplo clique em '{txt('alvo')}'",
        "passar_mouse": lambda: f"Passar o mouse sobre '{txt('alvo')}'",
        "preencher": lambda: f"Preencher '{txt('campo')}' com '{txt('valor')}'",
        "digitar": lambda: f"Digitar '{txt('texto')}'" + (f" em '{args['campo']}'" if isinstance(args, dict) and args.get("campo") else ""),
        "apertar_tecla": lambda: f"Apertar a tecla {txt('tecla')}",
        "esperar": lambda: (f"Esperar {args}s" if isinstance(args, (int, float))
                            else f"Esperar '{args['sumir']}' sumir" if isinstance(args, dict) and "sumir" in args
                            else f"Esperar o texto '{args['texto']}' aparecer" if isinstance(args, dict) and "texto" in args
                            else f"Esperar '{txt('elemento') if isinstance(args, dict) and 'elemento' in args else txt('alvo')}' aparecer"),
        "selecionar": lambda: f"Selecionar '{txt('opcao')}' em '{txt('campo')}'",
        "marcar": lambda: f"Marcar '{txt('alvo')}'",
        "desmarcar": lambda: f"Desmarcar '{txt('alvo')}'",
        "enviar_arquivo": lambda: f"Enviar o arquivo '{txt('arquivo')}' em '{txt('campo')}'",
        "arrastar": lambda: f"Arrastar '{txt('de')}' para '{txt('para')}'",
        "rolar": lambda: (f"Rolar até '{args['ate']}'" if isinstance(args, dict) and "ate" in args
                          else f"Rolar a página para {args}"),
        "logar": lambda: f"Fazer login com o usuário '{txt('usuario')}'",
        "cadastrar": lambda: "Preencher o formulário de cadastro" + (f" e enviar em '{args['enviar']}'" if isinstance(args, dict) and args.get("enviar") else ""),
        "buscar": lambda: f"Buscar por '{txt('termo')}'",
        "recarregar": lambda: "Recarregar a página",
        "voltar": lambda: "Voltar para a página anterior",
        "capturar_tela": lambda: "Capturar a tela",
        "fechar": lambda: "Fechar o programa",
        "verificar_texto": lambda: f"Verificar se o texto '{txt('texto')}' aparece" + (
            f" em '{args['elemento']}'" if isinstance(args, dict) and args.get("elemento") else ""),
        "verificar_sem_texto": lambda: f"Verificar se o texto '{txt('texto')}' NÃO aparece",
        "verificar_elemento": lambda: f"Verificar se o elemento '{txt('alvo')}' existe",
        "verificar_url": lambda: (f"Verificar se a URL é '{args['igual']}'" if isinstance(args, dict) and "igual" in args
                                  else f"Verificar se a URL contém '{txt('contem')}'"),
        "verificar_titulo": lambda: f"Verificar se o título contém '{txt('contem')}'",
        "verificar_valor": lambda: f"Verificar se '{txt('campo')}' tem o valor '{txt('valor')}'",
        "verificar_mensagem": lambda: f"Verificar mensagem de {txt('tipo', 'sucesso/erro')}" + (f" '{args['texto']}'" if isinstance(args, dict) and args.get("texto") else ""),
        "requisitar": lambda: (f"Requisição {args}" if isinstance(args, str)
                               else f"Requisição {str(args.get('metodo', 'GET')).upper()} {args.get('url', '/')}"),
        "verificar_status": lambda: f"Verificar se o status HTTP é {args.get('igual', args.get('entre')) if isinstance(args, dict) else args}",
        "verificar_json": lambda: f"Verificar o campo JSON '{txt('campo')}'" + (f" = '{args['valor']}'" if isinstance(args, dict) and "valor" in args else ""),
        "verificar_tempo": lambda: f"Verificar se respondeu em até {txt('maximo_ms')} ms",
        "verificar_cabecalho": lambda: f"Verificar o cabeçalho '{txt('nome')}'",
        "guardar": lambda: f"Guardar '{txt('campo')}' como {{dados.{txt('como')}}}",
        "verificar_banco": lambda: f"Conferir no banco: {txt('sql')}",
        "consultar_banco": lambda: f"Consultar o banco: {txt('sql')}",
        "preparar_banco": lambda: f"Preparar o banco: {txt('sql')}",
        "verificar_acessibilidade": lambda: "Verificar acessibilidade (axe-core / WCAG)",
        "verificar_esquema": lambda: "Validar o JSON contra o esquema (JSON Schema)",
        "comparar_visual": lambda: f"Comparar a tela com a linha de base '{txt('nome')}'",
        "verificar_desempenho": lambda: "Verificar desempenho de carregamento da página",
        "teste_carga": lambda: f"Teste de carga: {txt('requisicoes', '?')} requisições em {txt('url', 'alvo')}",
        "verificar_seguranca": lambda: "Verificar cabeçalhos e cookies de segurança",
        "verificar_links": lambda: "Verificar links quebrados da página",
        "varredura_seguranca": lambda: "Varredura de segurança (14 pontos OWASP) — só em sistemas seus",
        "verificar_injecao": lambda: f"Testar SQL injection e XSS em '{txt('parametro', 'parâmetro')}'",
        "auditoria_ux": lambda: "Auditoria de UI/UX (contraste, tipografia, cores, alvos de toque) com código da correção",
    }
    try:
        return modelos[comando]()
    except Exception:
        return f"{comando}: {args}"


def _ler_passo(item: Any, onde: str) -> Passo:
    """Converte um item da lista de passos em Passo, validando o comando."""
    descricao = None
    if isinstance(item, str):           # ex.: "- recarregar"
        comando, args = item.strip(), None
    elif isinstance(item, dict):
        item = dict(item)
        descricao = item.pop("descricao", None)
        if len(item) != 1:
            raise ErroRoteiro(
                f"{onde}: cada passo deve ter exatamente UM comando "
                f"(encontrado: {list(item.keys()) or 'nenhum'})"
            )
        comando, args = next(iter(item.items()))
    else:
        raise ErroRoteiro(f"{onde}: passo inválido: {item!r}")

    comando = APELIDOS.get(str(comando).strip().lower(), str(comando).strip().lower())
    if comando not in COMANDOS:
        raise ErroRoteiro(
            f"{onde}: comando desconhecido '{comando}'. "
            f"Comandos aceitos: {', '.join(sorted(COMANDOS))}"
        )
    return Passo(comando, args, descricao or descrever(comando, args))


def _ler_passos(lista: Any, onde: str) -> list[Passo]:
    if lista is None:
        return []
    if not isinstance(lista, list):
        raise ErroRoteiro(f"{onde}: 'passos' deve ser uma lista (use '- ' antes de cada passo)")
    return [_ler_passo(p, f"{onde}, passo {i}") for i, p in enumerate(lista, start=1)]


def eh_gherkin(texto: str) -> bool:
    """Reconhece um texto Gherkin (.feature) pelo cabeçalho ou pelas palavras-chave."""
    import re
    # Palavras com inicial maiúscula: no YAML os campos são minúsculos (ex.: "funcionalidade: F01")
    return bool(re.search(r"^\s*#\s*language:\s*pt", texto, re.M | re.I)
                or re.search(r"^\s*(Funcionalidade|Cenário|Cenario):", texto, re.M))


def carregar_roteiro(caminho: str) -> Roteiro:
    """Lê o arquivo do roteiro e devolve um objeto Roteiro validado."""
    if not os.path.isfile(caminho):
        raise ErroRoteiro(f"Arquivo de roteiro não encontrado: {caminho}")

    with open(caminho, encoding="utf-8-sig") as f:
        texto = f.read()
    try:
        if caminho.lower().endswith(".json"):
            bruto = json.loads(texto)
        elif caminho.lower().endswith(".feature") or eh_gherkin(texto):
            from sentinela.gherkin import ErroGherkin, feature_para_dict
            try:
                bruto = feature_para_dict(texto)
            except ErroGherkin as e:
                raise ErroRoteiro(str(e)) from e
        else:
            bruto = yaml.safe_load(texto)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ErroRoteiro(f"O roteiro tem erro de formatação: {e}") from e

    if not isinstance(bruto, dict):
        raise ErroRoteiro("O roteiro deve começar com chaves como 'sistema:', 'casos:' ...")

    casos_brutos = bruto.get("casos") or []
    if not casos_brutos and bruto.get("tipo") != "suite":
        raise ErroRoteiro("O roteiro não tem nenhum caso de teste na seção 'casos'.")

    casos, ids = [], set()
    for i, c in enumerate(casos_brutos, start=1):
        if not isinstance(c, dict):
            raise ErroRoteiro(f"Caso {i}: formato inválido")
        cid = str(c.get("id") or f"CT{i:02d}")
        if cid in ids:
            raise ErroRoteiro(f"ID de caso repetido: {cid}")
        ids.add(cid)
        sev = str(c.get("severidade", "Média")).capitalize().replace("Media", "Média").replace("Critica", "Crítica")
        if sev not in SEVERIDADES:
            raise ErroRoteiro(f"Caso {cid}: severidade deve ser uma de {SEVERIDADES}")
        casos.append(Caso(
            id=cid,
            descricao=str(c.get("descricao", "")),
            passos=_ler_passos(c.get("passos"), f"Caso {cid}"),
            esperado=str(c.get("esperado", "")),
            funcionalidade=str(c.get("funcionalidade", "")),
            severidade=sev,
        ))

    pasta = os.path.dirname(os.path.abspath(caminho))
    return Roteiro(
        arquivo=os.path.abspath(caminho),
        pasta=pasta,
        sistema=str(bruto.get("sistema", "Sistema sem nome")),
        versao=str(bruto.get("versao", "-")),
        responsavel=str(bruto.get("responsavel", "-")),
        ambiente=str(bruto.get("ambiente", "")),
        objetivo=str(bruto.get("objetivo", "")),
        alvo=bruto.get("alvo"),
        tipo=bruto.get("tipo"),
        janela=bruto.get("janela"),
        tempo_limite=float(bruto.get("tempo_limite", 10)),
        atributo_testid=str(bruto.get("atributo_testid", "data-testid")),
        dados=bruto.get("dados") or {},
        funcionalidades=bruto.get("funcionalidades") or [],
        antes_de_cada=_ler_passos(bruto.get("antes_de_cada"), "antes_de_cada"),
        casos=casos,
        exploracao=bruto.get("exploracao"),
        banco=bruto.get("banco"),
        dispositivo=bruto.get("dispositivo"),
        navegador=bruto.get("navegador"),
        motor=bruto.get("motor"),
        suite={k: bruto.get(k) for k in ("ferramenta", "pasta", "comando", "junit", "preparar", "env")}
        if bruto.get("tipo") == "suite" else None,
    )


def detectar_tipo(alvo: str | None, tipo_roteiro: str | None) -> str:
    """Decide se o teste é 'web' ou 'desktop' a partir do alvo."""
    if tipo_roteiro in ("web", "desktop", "api", "suite"):
        return tipo_roteiro
    if not alvo:
        raise ErroRoteiro("Informe o alvo (URL ou .exe) no roteiro ou com --alvo")
    a = alvo.lower()
    if a.startswith(("http://", "https://")):
        return "web"
    if a.endswith(".exe") or os.path.isfile(alvo):
        return "desktop"
    raise ErroRoteiro(f"Não sei se o alvo '{alvo}' é site ou programa. Use http(s)://... ou um .exe")


MODELO_ROTEIRO = """\
# Roteiro de teste do Sentinela QA — edite à vontade.
# Linhas que começam com # são comentários.

sistema: Meu Sistema
versao: "1.0"
responsavel: Seu Nome
ambiente: Homologação - Chrome - Windows 11
objetivo: Validar o login e o cadastro do sistema.
alvo: https://www.saucedemo.com      # ou o caminho de um .exe
tempo_limite: 10                      # segundos máximos de espera por passo

funcionalidades:
  - id: F01
    nome: Login
    criterios:
      - Usuário com credenciais válidas acessa a área logada
      - Usuário com senha errada vê mensagem de erro

casos:
  - id: CT01
    funcionalidade: F01
    descricao: Login com usuário válido
    esperado: A página de produtos é exibida
    severidade: Alta
    passos:
      - abrir: /
      - preencher: { campo: "#user-name", valor: standard_user }
      - preencher: { campo: "#password", valor: "{env.SAUCE_SENHA|secret_sauce}" }
      - clicar: "#login-button"
      - verificar_url: inventory
      - verificar_texto: Products
"""
