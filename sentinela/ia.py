"""
Análise por IA (opcional): envia o log da execução e alguns prints para a
IA e pede sugestões de usabilidade, texto, acessibilidade e funcionalidades.

Configuração (variáveis de ambiente ou arquivo .env — NUNCA no código):
    GEMINI_API_KEY=...                 chave da API do Google Gemini
    SENTINELA_IA=gemini                  provedor (gemini | nenhuma)
    SENTINELA_MODELO_IA=                  modelo a usar (vazio = escolhe automaticamente
                                          o flash mais novo liberado para a sua chave)

As respostas da IA entram no relatório como SUGESTÕES: precisam ser
avaliadas por uma pessoa antes de virar requisito ou defeito.
"""

import io
import json
import os
import re
import threading

from sentinela.registro import Registro, Sugestao

MAX_PRINTS = 6

PROMPT = """Você é um analista de QA sênior revisando uma execução automatizada de testes.
Sistema: {sistema}
Objetivo dos testes: {objetivo}

Abaixo está o resumo da execução em JSON (casos, defeitos, observações e o caminho
percorrido) e alguns prints das telas visitadas.

{resumo}

Com base SOMENTE no que você vê nos prints e no log, sugira melhorias em português do Brasil:
- Usabilidade (fluxo, clareza, feedback ao usuário)
- Texto (mensagens de erro, rótulos, idioma, consistência)
- Acessibilidade (contraste, rótulos, foco, leitores de tela)
- Funcionalidade (ideias de recursos que fariam sentido)

Responda APENAS com JSON no formato:
{{"sugestoes": [{{"categoria": "Usabilidade|Texto|Acessibilidade|Funcionalidade",
  "titulo": "frase curta", "descricao": "o que mudar e por quê",
  "prioridade": "Alta|Média|Baixa", "evidencia": "nome do print ou passo que motivou"}}]}}
Dê entre 4 e 10 sugestões, sem repetir os defeitos já listados."""


def _escolher_prints(registro: Registro) -> list:
    """Prioriza prints de falhas e completa com prints espalhados pelo caminho."""
    com_print = [a for a in registro.acoes if a.print and a.print.endswith(".png")]
    falhas = [a for a in com_print if a.status == "falha"]
    resto = [a for a in com_print if a.status != "falha"]
    escolhidos = falhas[: MAX_PRINTS // 2]
    vagas = MAX_PRINTS - len(escolhidos)
    if resto and vagas > 0:
        passo = max(1, len(resto) // vagas)
        escolhidos += resto[::passo][:vagas]
    return escolhidos


def _resumo(registro: Registro) -> str:
    dados = {
        "casos": [{"id": c.id, "descricao": c.descricao, "status": c.status, "obtido": c.obtido} for c in registro.casos],
        "defeitos": [{"id": d.id, "descricao": d.descricao, "severidade": d.severidade} for d in registro.defeitos],
        "observacoes": [f"[{o.categoria}] {o.texto}" for o in registro.observacoes][:30],
        "caminho": [f"{a.ordem}. [{a.caso_id}] {a.descricao} -> {a.status}" for a in registro.acoes][:80],
    }
    return json.dumps(dados, ensure_ascii=False, indent=1)


# Erros em que vale a pena tentar outro modelo
_ERROS_TROCAR_MODELO = ("NOT_FOUND", "DEADLINE_EXCEEDED", "UNAVAILABLE", "503", "504",
                        "RESOURCE_EXHAUSTED", "timed out", "Timeout")


def _versao(nome: str) -> float:
    """'gemini-3.8-flash' -> 3.8 (para ordenar do mais novo ao mais antigo)."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", nome)
    return float(m.group(1)) if m else 0.0


def _modelos_disponiveis(cliente) -> list[str]:
    """Modelos liberados para a chave que fazem generateContent (sem os de imagem)."""
    try:
        return [m.name.split("/")[-1] for m in cliente.models.list()
                if "generateContent" in (m.supported_actions or [])]
    except Exception:
        return []


def _ordenar_flash(nomes: list[str]) -> list[str]:
    """Flash mais novo primeiro, depois flash-lite, depois os demais gemini."""
    flash = sorted([n for n in nomes if n.endswith("flash") and "image" not in n], key=_versao, reverse=True)
    lite = sorted([n for n in nomes if n.endswith("flash-lite")], key=_versao, reverse=True)
    outros = sorted([n for n in nomes if n.startswith("gemini") and "flash" not in n and "image" not in n],
                    key=_versao, reverse=True)
    return flash + lite + outros


def _resolver_modelo(cliente, desejado: str, registro) -> str:
    """Escolhe o modelo a usar: o configurado, se existir para a chave; senão o flash
    mais novo liberado. Evita começar por um modelo que não existe (que sempre falharia)."""
    nomes = _modelos_disponiveis(cliente)
    if not nomes:
        return desejado or "gemini-flash-latest"
    if desejado and desejado in nomes:
        return desejado
    escolhido = (_ordenar_flash(nomes) or nomes)[0]
    if desejado:
        registro.avisar(f"Modelo '{desejado}' indisponível para esta chave; usando '{escolhido}'. "
                        f"Para fixar, defina SENTINELA_MODELO_IA={escolhido} no .env.")
    return escolhido


def _candidatos(cliente, erro: str, ja_tentados: set) -> list[str]:
    """Modelos alternativos quando a chamada falha: 1º o que a própria mensagem de erro
    recomenda; depois os 'flash' liberados para a chave, do mais novo ao mais antigo."""
    lista = re.findall(r"use models/([\w.-]+)", erro) + _ordenar_flash(_modelos_disponiveis(cliente))
    vistos, saida = set(ja_tentados), []
    for n in lista:
        if n not in vistos:
            vistos.add(n)
            saida.append(n)
    return saida[:2]


def analisar(registro: Registro, sistema: str, objetivo: str) -> None:
    """Preenche registro.sugestoes. Se não houver chave, apenas avisa."""
    provedor = os.getenv("SENTINELA_IA", "gemini").strip().lower()
    if provedor in ("", "nenhuma", "nenhum", "off"):
        registro.avisar("Análise por IA desligada (SENTINELA_IA=nenhuma).")
        return
    if provedor != "gemini":
        registro.avisar(f"Provedor de IA '{provedor}' não suportado; use 'gemini'.")
        return
    chave = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not chave:
        registro.avisar("Sem chave de IA (GEMINI_API_KEY): o relatório foi gerado sem a seção de sugestões da IA.")
        return

    from google import genai
    from google.genai import types
    from PIL import Image

    modelo = os.getenv("SENTINELA_MODELO_IA", "").strip()   # vazio = escolher da lista liberada p/ a chave
    registro.log("\n🤖 Pedindo sugestões à IA...")
    conteudo = [PROMPT.format(sistema=sistema, objetivo=objetivo, resumo=_resumo(registro))]
    for acao in _escolher_prints(registro):
        caminho = os.path.join(registro.pasta_saida, acao.print)
        try:
            img = Image.open(caminho).convert("RGB")
            img.thumbnail((1280, 1280))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            conteudo.append(f"Print {acao.print} — passo {acao.ordem}: {acao.descricao}")
            conteudo.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
        except OSError:
            continue

    # A chamada roda numa thread separada com prazo total: se a IA demorar demais
    # (servidor sobrecarregado, várias tentativas), o relatório sai sem as sugestões.
    limite = int(os.getenv("SENTINELA_IA_TEMPO", "150"))
    resultado: dict = {}

    def chamar():
        try:
            resultado["bruto"] = _chamar_ia(genai, types, chave, modelo, conteudo, registro)
        except Exception as e:  # rede, chave inválida, cota, JSON malformado...
            resultado["erro"] = e

    t = threading.Thread(target=chamar, daemon=True)
    t.start()
    t.join(limite)
    if t.is_alive():
        registro.avisar(f"A IA não respondeu em {limite}s; o relatório foi gerado sem as sugestões. "
                        f"Tente de novo mais tarde ou troque o modelo em Configurações.")
        return
    if "erro" in resultado:
        registro.avisar(f"A análise por IA falhou e foi ignorada: {str(resultado['erro'])[:200]}")
        return
    bruto = resultado["bruto"]

    for s in bruto.get("sugestoes", []):
        registro.sugestoes.append(Sugestao(
            categoria=str(s.get("categoria", "Usabilidade")),
            titulo=str(s.get("titulo", "")),
            descricao=str(s.get("descricao", "")),
            prioridade=str(s.get("prioridade", "Média")),
            evidencia=str(s.get("evidencia", "")),
        ))
    registro.log(f"   {len(registro.sugestoes)} sugestão(ões) recebida(s).")


def _chamar_ia(genai, types, chave, modelo, conteudo, registro) -> dict:
    """Faz a chamada ao Gemini: resolve o modelo pela lista liberada para a chave
    (não começa por um que não existe) e, se falhar, tenta no máximo mais 2 alternativas."""
    # Limite de 45 s por requisição HTTP (o prazo total da IA é controlado por quem chama)
    cliente = genai.Client(api_key=chave, http_options=types.HttpOptions(timeout=45_000))
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4)
    modelo = _resolver_modelo(cliente, modelo, registro)
    registro.log(f"   modelo: {modelo}")
    try:
        resposta = cliente.models.generate_content(model=modelo, contents=conteudo, config=config)
    except Exception as e:
        if not any(s in str(e) for s in _ERROS_TROCAR_MODELO):
            raise  # ex.: chave inválida — trocar de modelo não resolve
        # Modelo indisponível, lento ou sobrecarregado: tenta outros "flash"
        resposta, ultimo_erro = None, e
        for alternativo in _candidatos(cliente, str(e), {modelo}):
            try:
                resposta = cliente.models.generate_content(model=alternativo, contents=conteudo, config=config)
                registro.avisar(f"Usado o modelo alternativo '{alternativo}'.")
                break
            except Exception as e2:
                ultimo_erro = e2
        if resposta is None:
            raise ultimo_erro
    return json.loads(resposta.text)
