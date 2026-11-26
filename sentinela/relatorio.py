"""
Geração dos relatórios: HTML (para ler), JSON (para outras ferramentas/CI)
e TXT (para colar em e-mail, Jira, etc.).

Formato seguido: cabeçalho (sistema, versão, data, responsável, ambiente),
objetivo, funcionalidades com critérios de aceitação, casos de teste
(ID, descrição, passos, esperado, obtido, status) e defeitos
(ID, descrição, severidade, status).
"""

import base64
import io
import json
import os
import sys
from dataclasses import asdict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sentinela import __version__


def pasta_templates() -> str:
    # Dentro do .exe (PyInstaller) os arquivos ficam em sys._MEIPASS
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(base, "sentinela", "templates")
    return os.path.join(base, "templates")


def montar_contexto(registro, roteiro, info: dict) -> dict:
    duracao = (registro.fim - registro.inicio).total_seconds() if registro.fim else 0
    total = len(registro.casos)
    contagem_sev = {}
    for d in registro.defeitos:
        contagem_sev[d.severidade] = contagem_sev.get(d.severidade, 0) + 1
    return {
        "versao_robo": __version__,
        "cabecalho": {
            "Sistema": roteiro.sistema,
            "Versão": roteiro.versao,
            "Data": registro.inicio.strftime("%d/%m/%Y %H:%M"),
            "Responsável": roteiro.responsavel,
            "Ambiente": info.get("ambiente", roteiro.ambiente),
            "Alvo": info.get("alvo", ""),
            "Roteiro": os.path.basename(roteiro.arquivo),
            "Finalidade": info.get("finalidade") or "-",
            "Duração": f"{duracao:.0f}s",
        },
        "sistema": roteiro.sistema,
        "objetivo": roteiro.objetivo,
        "funcionalidades": roteiro.funcionalidades,
        "resumo": {
            "total": total,
            "aprovados": registro.aprovados,
            "reprovados": registro.reprovados,
            "taxa": round(100 * registro.aprovados / total) if total else 0,
            "defeitos": len(registro.defeitos),
            "defeitos_por_severidade": contagem_sev,
            "observacoes": len(registro.observacoes),
            "sugestoes": len(registro.sugestoes),
            "melhorias_ux": len(registro.melhorias_ux),
            "acoes": len(registro.acoes),
            "exploracao": info.get("explorou", False),
            "ia": info.get("ia_usada", False),
        },
        "casos": [asdict(c) for c in registro.casos],
        "defeitos": [asdict(d) for d in registro.defeitos],
        "observacoes": [asdict(o) for o in registro.observacoes],
        "sugestoes": [asdict(s) for s in registro.sugestoes],
        "melhorias_ux": [asdict(m) for m in registro.melhorias_ux],
        "acoes": [asdict(a) for a in registro.acoes],
        "avisos": list(registro.avisos),
    }


def _embutir(pasta: str, rel: str | None) -> str | None:
    """Converte um print em data URI (JPEG reduzido) para o HTML ficar num arquivo só."""
    if not rel:
        return None
    if not rel.endswith(".png"):   # evidência de API (resposta .json)
        try:
            with open(os.path.join(pasta, rel), "rb") as f:
                return "data:application/json;base64," + base64.b64encode(f.read()).decode()
        except OSError:
            return None
    from PIL import Image
    try:
        img = Image.open(os.path.join(pasta, rel)).convert("RGB")
    except OSError:
        return None
    img.thumbnail((1100, 1100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=68)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def gerar(registro, roteiro, info: dict, embutir_prints: bool = False) -> dict:
    """Gera relatorio.html, relatorio.json e relatorio.txt. Devolve os caminhos."""
    ctx = montar_contexto(registro, roteiro, info)
    pasta = registro.pasta_saida

    # ---------------- JSON
    caminho_json = os.path.join(pasta, "relatorio.json")
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)

    # ---------------- HTML
    cache = {}

    def img(rel):
        if not embutir_prints:
            return rel
        if rel not in cache:
            cache[rel] = _embutir(pasta, rel)
        return cache[rel]

    env = Environment(loader=FileSystemLoader(pasta_templates()),
                      autoescape=select_autoescape(["html", "j2"]))
    env.globals["img"] = img
    html = env.get_template("relatorio.html.j2").render(**ctx)
    caminho_html = os.path.join(pasta, "relatorio.html")
    with open(caminho_html, "w", encoding="utf-8") as f:
        f.write(html)

    # ---------------- TXT
    caminho_txt = os.path.join(pasta, "relatorio.txt")
    with open(caminho_txt, "w", encoding="utf-8") as f:
        f.write(gerar_txt(ctx))

    return {"html": caminho_html, "json": caminho_json, "txt": caminho_txt}


def gerar_txt(ctx: dict) -> str:
    linhas = []
    add = linhas.append
    linha = "=" * 72
    add(linha)
    add(f"RELATÓRIO DE TESTES — {ctx['sistema']}")
    add(linha)
    for k, v in ctx["cabecalho"].items():
        add(f"{k + ':':<14}{v}")
    r = ctx["resumo"]
    add("")
    add("RESUMO")
    add(f"  Casos: {r['total']} | Aprovados: {r['aprovados']} | Reprovados: {r['reprovados']} | Taxa: {r['taxa']}%")
    add(f"  Defeitos: {r['defeitos']} | Observações: {r['observacoes']} | Sugestões da IA: {r['sugestoes']}")
    for a in ctx["avisos"]:
        add(f"  AVISO: {a}")
    add("")
    add("OBJETIVO")
    add(f"  {ctx['objetivo'] or '-'}")
    add("")
    add("FUNCIONALIDADES E CRITÉRIOS DE ACEITAÇÃO")
    for fn in ctx["funcionalidades"]:
        add(f"  {fn.get('id', '')} - {fn.get('nome', '')}")
        for c in fn.get("criterios", []):
            add(f"     • {c}")
    add("")
    add("CASOS DE TESTE")
    for c in ctx["casos"]:
        add(f"  [{c['status']}] {c['id']} — {c['descricao']}")
        add("     Passos:")
        for i, p in enumerate(c["passos"], 1):
            add(f"       {i}. {p}")
        add(f"     Esperado: {c['esperado'] or '-'}")
        add(f"     Obtido:   {c['obtido']}")
        add(f"     Evidência: {c['print'] or '-'}")
        add("")
    add("DEFEITOS")
    if not ctx["defeitos"]:
        add("  Nenhum defeito encontrado.")
    for d in ctx["defeitos"]:
        add(f"  {d['id']} | {d['severidade']} | {d['status']} | origem: {d['origem']}")
        add(f"     {d['descricao']}")
        add("     Passos para reproduzir:")
        for i, p in enumerate(d["passos_reproducao"], 1):
            add(f"       {i}. {p}")
        add(f"     Esperado: {d['esperado'] or '-'}")
        add(f"     Obtido:   {d['obtido']}")
        add(f"     Evidência: {d['evidencia'] or '-'}")
        add("")
    add("O QUE FOI ENCONTRADO (OBSERVAÇÕES)")
    if not ctx["observacoes"]:
        add("  Nenhuma observação.")
    for o in ctx["observacoes"]:
        add(f"  [{o['categoria']}] {o['texto']}")
    add("")
    add("MELHORIAS E IDEIAS (SUGESTÕES DA IA — avaliar antes de aplicar)")
    if not ctx["sugestoes"]:
        add("  Nenhuma sugestão (IA não utilizada).")
    for s in ctx["sugestoes"]:
        add(f"  [{s['categoria']} | prioridade {s['prioridade']}] {s['titulo']}")
        add(f"     {s['descricao']}")
    add("")
    add("AUDITORIA DE UI/UX (medido na página — cada item traz o código da correção)")
    if not ctx["melhorias_ux"]:
        add("  Auditoria de UI/UX não executada (use o comando 'auditoria_ux' no roteiro).")
    for m in ctx["melhorias_ux"]:
        add(f"  [{m['categoria']} | prioridade {m['prioridade']}] {m['titulo']}")
        add(f"     {m['descricao']}")
        if m["evidencia"]:
            add(f"     Onde: {m['evidencia']}")
        if m["codigo"]:
            add(f"     Correção ({m['linguagem']}):")
            for linha in m["codigo"].splitlines():
                add(f"       {linha}")
        add("")
    add("")
    add("CAMINHO PERCORRIDO")
    for a in ctx["acoes"]:
        add(f"  {a['ordem']:>3}. {a['horario']} [{a['caso_id']}] {a['descricao']} -> "
            f"{'OK' if a['status'] == 'ok' else 'FALHA'} ({a['duracao_ms']} ms) {a['print'] or ''}")
    add("")
    add(f"Gerado por Sentinela QA v{ctx['versao_robo']}")
    return "\n".join(linhas)
