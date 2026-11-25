"""
Suporte a Gherkin em português (arquivos .feature, estilo BDD/Cucumber).

O Sentinela entende frases prontas e converte cada uma num comando do roteiro.
Exemplo de arquivo:

    # language: pt
    # alvo: http://127.0.0.1:8000
    # sistema: Loja Treino
    Funcionalidade: Login

      @CT01 @critica
      Cenário: Login com usuário válido
        Dado que eu acesso "/index.html"
        Quando eu preencho "rotulo=Usuário" com "qa"
        E eu clico em "papel=button:Entrar"
        Então a URL deve conter "painel.html"
        E devo ver "Bem-vindo, qa!"

Também converte um roteiro YAML em .feature:   sentinela gherkin --roteiro roteiros/x.yaml
"""

import re

PALAVRAS = r"^(dado|dada|dados|quando|então|entao|e|mas)\s+(que\s+)?"

# (expressão regular da frase, função que monta o passo {comando: args})
_A = r'"([^"]*)"'
FRASES = [
    (rf"(eu )?(acesso|abro|estou na página|estou em) {_A}$", lambda m: {"abrir": m[3]}),
    (rf"(eu )?faço login com {_A} e {_A}$", lambda m: {"logar": {"usuario": m[2], "senha": m[3]}}),
    (rf"(eu )?preencho {_A} com {_A}$", lambda m: {"preencher": {"campo": m[2], "valor": m[3]}}),
    (rf"(eu )?digito {_A} em {_A}$", lambda m: {"digitar": {"texto": m[2], "campo": m[3]}}),
    (rf"(eu )?clico (em|no|na) {_A}$", lambda m: {"clicar": m[3]}),
    (rf"(eu )?dou duplo clique (em|no|na) {_A}$", lambda m: {"clicar_duplo": m[3]}),
    (rf"(eu )?passo o mouse (em|sobre|no|na) {_A}$", lambda m: {"passar_mouse": m[3]}),
    (rf"(eu )?aperto (a tecla )?{_A}$", lambda m: {"apertar_tecla": m[3]}),
    (rf"(eu )?seleciono {_A} em {_A}$", lambda m: {"selecionar": {"opcao": m[2], "campo": m[3]}}),
    (rf"(eu )?marco {_A}$", lambda m: {"marcar": m[2]}),
    (rf"(eu )?desmarco {_A}$", lambda m: {"desmarcar": m[2]}),
    (rf"(eu )?busco (por )?{_A}$", lambda m: {"buscar": {"termo": m[3]}}),
    (rf"(eu )?envio o arquivo {_A} em {_A}$", lambda m: {"enviar_arquivo": {"arquivo": m[2], "campo": m[3]}}),
    (rf"(eu )?espero (o texto )?{_A} aparecer$", lambda m: {"esperar": {"texto": m[3]}}),
    (rf"(eu )?espero {_A} sumir$", lambda m: {"esperar": {"sumir": m[2]}}),
    (rf"(eu )?rolo (a página )?até {_A}$", lambda m: {"rolar": {"ate": m[3]}}),
    (rf"(eu )?envio (uma requisição )?(GET|POST|PUT|PATCH|DELETE) (para )?{_A}$",
     lambda m: {"requisitar": f"{m[3].upper()} {m[5]}"}),
    (rf"devo ver a mensagem de (erro|sucesso) {_A}$", lambda m: {"verificar_mensagem": {"tipo": m[1], "texto": m[2]}}),
    (rf"não devo ver {_A}$", lambda m: {"verificar_sem_texto": m[1]}),
    (rf"devo ver {_A} em {_A}$", lambda m: {"verificar_texto": {"texto": m[1], "elemento": m[2]}}),
    (rf"devo ver {_A}$", lambda m: {"verificar_texto": m[1]}),
    (rf"a url deve conter {_A}$", lambda m: {"verificar_url": m[1]}),
    (rf"o título deve conter {_A}$", lambda m: {"verificar_titulo": m[1]}),
    (rf"o elemento {_A} deve (existir|aparecer)$", lambda m: {"verificar_elemento": m[1]}),
    (rf"o campo {_A} deve ter o valor {_A}$", lambda m: {"verificar_valor": {"campo": m[1], "valor": m[2]}}),
    (r"o status (da resposta )?deve ser (\d{3})$", lambda m: {"verificar_status": int(m[2])}),
    (rf"o campo json {_A} deve ser {_A}$", lambda m: {"verificar_json": {"campo": m[1], "valor": m[2]}}),
    (rf"o campo json {_A} deve conter {_A}$", lambda m: {"verificar_json": {"campo": m[1], "contem": m[2]}}),
]

SEVERIDADE_TAG = {"critica": "Crítica", "crítica": "Crítica", "alta": "Alta", "media": "Média", "média": "Média", "baixa": "Baixa"}
CABECALHO = ("alvo", "sistema", "versao", "responsavel", "ambiente", "tipo", "tempo_limite", "atributo_testid", "janela")


class ErroGherkin(Exception):
    pass


def frase_para_passo(frase: str, linha: int) -> dict:
    texto = re.sub(PALAVRAS, "", frase.strip(), flags=re.I)
    for padrao, montar in FRASES:
        m = re.match(padrao, texto, flags=re.I)
        if m:
            passo = montar(m)
            passo["descricao"] = frase.strip()   # no relatório aparece a frase original
            return passo
    raise ErroGherkin(f"Linha {linha}: frase não reconhecida: “{frase.strip()}”. Veja as frases aceitas no Guia de comandos.")


def feature_para_dict(texto: str) -> dict:
    """Converte o texto de um .feature no mesmo dicionário que um roteiro YAML gera."""
    bruto = {"casos": [], "funcionalidades": [], "antes_de_cada": []}
    func = None
    caso = None
    tags: list[str] = []
    no_contexto = False
    for n, linha in enumerate(texto.splitlines(), start=1):
        s = linha.strip()
        if not s:
            continue
        if s.startswith("#"):
            chave, _, valor = s[1:].partition(":")
            if chave.strip().lower() in CABECALHO and valor.strip():
                bruto[chave.strip().lower()] = valor.strip()
            continue
        if s.startswith("@"):
            tags += [t[1:] for t in s.split()]
            continue
        rotulo, _, resto = s.partition(":")
        rotulo_l = rotulo.strip().lower()
        if rotulo_l in ("funcionalidade", "característica", "caracteristica"):
            func = {"id": f"F{len(bruto['funcionalidades']) + 1:02d}", "nome": resto.strip(), "criterios": []}
            bruto["funcionalidades"].append(func)
            bruto.setdefault("sistema", resto.strip())
            continue
        if rotulo_l in ("contexto", "cenário de fundo", "cenario de fundo"):
            no_contexto, caso = True, None
            continue
        if rotulo_l in ("cenário", "cenario", "exemplo"):
            no_contexto = False
            cid = next((t for t in tags if re.match(r"^CT\d+", t, re.I)), None) or f"CT{len(bruto['casos']) + 1:02d}"
            sev = next((SEVERIDADE_TAG[t.lower()] for t in tags if t.lower() in SEVERIDADE_TAG), "Média")
            caso = {"id": cid.upper(), "descricao": resto.strip(), "passos": [], "severidade": sev,
                    "funcionalidade": func["id"] if func else "", "esperado": ""}
            bruto["casos"].append(caso)
            if func:
                func["criterios"].append(resto.strip())
            tags = []
            continue
        if re.match(PALAVRAS, s, flags=re.I):
            passo = frase_para_passo(s, n)
            if no_contexto:
                bruto["antes_de_cada"].append(passo)
            elif caso is not None:
                caso["passos"].append(passo)
                if re.match(r"^(então|entao)\b", s, re.I) or (caso["esperado"] and re.match(r"^e\b", s, re.I)):
                    caso["esperado"] = (caso["esperado"] + "; " if caso["esperado"] else "") + re.sub(PALAVRAS, "", s, flags=re.I)
            else:
                raise ErroGherkin(f"Linha {n}: passo fora de um Cenário.")
            continue
        # Demais linhas (descrição da funcionalidade, "Como... quero... para...") viram objetivo
        if func and not bruto["casos"]:
            bruto["objetivo"] = (bruto.get("objetivo", "") + " " + s).strip()
    return bruto


# ------------------------------------------------------------------ YAML -> Gherkin
def _q(v) -> str:
    return '"' + str(v).replace('"', "'") + '"'


def passo_para_frases(comando: str, args) -> list[tuple[str, str]] | None:
    """Comandos compostos viram várias frases: [(tipo, frase)], tipo = 'acao' ou 'verificacao'."""
    a = args if isinstance(args, dict) else {}
    if comando == "logar" and (a.get("campo_usuario") or a.get("campo_senha")):
        return [("acao", f"eu preencho {_q(a.get('campo_usuario', 'input[type=email]'))} com {_q(a.get('usuario'))}"),
                ("acao", f"eu preencho {_q(a.get('campo_senha', 'input[type=password]'))} com {_q(a.get('senha'))}"),
                ("acao", f"eu clico em {_q(a.get('botao', 'button[type=submit]'))}")]
    if comando == "cadastrar" and isinstance(a.get("campos"), dict):
        frases = [("acao", f"eu preencho {_q(c)} com {_q(v)}") for c, v in a["campos"].items()]
        if a.get("enviar"):
            frases.append(("acao", f"eu clico em {_q(a['enviar'])}"))
        return frases
    if comando == "apertar_tecla" and a.get("campo"):
        return [("acao", f"eu aperto a tecla {_q(a.get('tecla'))}")]
    frase = passo_para_frase(comando, args)
    if frase is None:
        return None
    return [("verificacao" if comando.startswith("verificar") else "acao", frase)]


def passo_para_frase(comando: str, args) -> str | None:
    a = args if isinstance(args, dict) else {}
    s = args if not isinstance(args, dict) else None
    mapa = {
        "abrir": lambda: f"eu acesso {_q(s or a.get('url', '/'))}",
        "logar": lambda: f"eu faço login com {_q(a.get('usuario'))} e {_q(a.get('senha'))}",
        "preencher": lambda: f"eu preencho {_q(a.get('campo'))} com {_q(a.get('valor'))}",
        "digitar": lambda: f"eu digito {_q(a.get('texto'))} em {_q(a.get('campo'))}" if a.get("campo") else None,
        "clicar": lambda: f"eu clico em {_q(s or a.get('alvo'))}",
        "passar_mouse": lambda: f"eu passo o mouse sobre {_q(s or a.get('alvo'))}",
        "apertar_tecla": lambda: f"eu aperto a tecla {_q(s or a.get('tecla'))}" if not a.get("campo") else None,
        "selecionar": lambda: f"eu seleciono {_q(a.get('opcao'))} em {_q(a.get('campo'))}",
        "marcar": lambda: f"eu marco {_q(s or a.get('alvo'))}",
        "buscar": lambda: f"eu busco por {_q(a.get('termo', s))}" if not a.get("campo") else None,
        "verificar_texto": lambda: (f"devo ver {_q(a['texto'])} em {_q(a['elemento'])}" if a.get("elemento")
                                    else f"devo ver {_q(s or a.get('texto'))}"),
        "verificar_sem_texto": lambda: f"não devo ver {_q(s or a.get('texto'))}",
        "verificar_url": lambda: f"a URL deve conter {_q(s or a.get('contem'))}" if s or "contem" in a else None,
        "verificar_titulo": lambda: f"o título deve conter {_q(s or a.get('contem'))}",
        "verificar_elemento": lambda: f"o elemento {_q(s or a.get('alvo'))} deve existir" if len(a) <= 1 else None,
        "verificar_valor": lambda: f"o campo {_q(a.get('campo'))} deve ter o valor {_q(a.get('valor'))}",
        "verificar_mensagem": lambda: (f"devo ver a mensagem de {a.get('tipo', 'erro')} {_q(a['texto'])}" if a.get("texto") else None),
        "requisitar": lambda: f"eu envio {s}" if s and s.split()[0].upper() in ("GET", "POST", "PUT", "PATCH", "DELETE") else None,
        "verificar_status": lambda: f"o status deve ser {s}" if s is not None and not isinstance(s, dict) else None,
        "verificar_json": lambda: (f"o campo JSON {_q(a['campo'])} deve ser {_q(a['valor'])}" if "valor" in a
                                   else f"o campo JSON {_q(a['campo'])} deve conter {_q(a['contem'])}" if "contem" in a else None),
    }
    try:
        return mapa[comando]() if comando in mapa else None
    except Exception:
        return None


def roteiro_para_feature(roteiro) -> str:
    """Gera um .feature a partir de um Roteiro carregado (YAML)."""
    linhas = ["# language: pt", f"# sistema: {roteiro.sistema}"]
    if roteiro.alvo:
        linhas.append(f"# alvo: {roteiro.alvo}")
    if roteiro.tipo:
        linhas.append(f"# tipo: {roteiro.tipo}")
    nome = roteiro.funcionalidades[0]["nome"] if roteiro.funcionalidades else roteiro.sistema
    linhas += [f"Funcionalidade: {nome}", f"  {roteiro.objetivo}".rstrip(), ""]

    def bloco(passos, recuo="    "):
        saida, fase = [], None
        for p in passos:
            frases = passo_para_frases(p.comando, p.args)
            if frases is None:
                saida.append(f"{recuo}# (sem frase Gherkin para o comando '{p.comando}' — mantenha no YAML)")
                continue
            for tipo, frase in frases:
                nova = "Então" if tipo == "verificacao" else ("Dado" if fase is None else "Quando")
                palavra = "E" if nova == fase or (fase == "Quando" and nova == "Dado") else nova
                if palavra != "E":
                    fase = nova
                if palavra == "Dado":
                    frase = "que " + frase
                # Gherkin não tem seção "dados:": troca {dados.x} pelo valor definido no YAML
                frase = re.sub(r"\{dados\.(\w+)\}", lambda m: str(roteiro.dados.get(m[1], m[0])), frase)
                saida.append(f"{recuo}{palavra} {frase}")
        return saida

    if roteiro.antes_de_cada:
        linhas += ["  Contexto:"] + bloco(roteiro.antes_de_cada) + [""]
    sev_tag = {"Crítica": "@critica", "Alta": "@alta", "Média": "@media", "Baixa": "@baixa"}
    for c in roteiro.casos:
        linhas.append(f"  @{c.id} {sev_tag.get(c.severidade, '')}".rstrip())
        linhas.append(f"  Cenário: {c.descricao}")
        linhas += bloco(c.passos)
        linhas.append("")
    return "\n".join(linhas)
