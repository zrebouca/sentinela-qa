"""
Painel web do Sentinela QA.

Telas:
  /             Painel (indicadores, atividade recente, pendências, ações rápidas)
  /projetos     Cadastro dos sistemas em teste (nome, tipo, alvo, finalidade...)
  /roteiros     Roteiros de teste (editor YAML com validação)
  /executar     Assistente para disparar uma execução (finalidade, IA sim/não, exploração)
  /execucoes    Histórico + acompanhamento ao vivo + relatório
  /defeitos     Gestão dos bugs encontrados (status, comentário, evidência)
  /configuracoes  Chave e modelo da IA, preferências, exemplos
  /ajuda        Guia de comandos do roteiro

Roda só no próprio computador (127.0.0.1); nada fica exposto na rede.
"""

import json
import os
import re
import shutil
import sys
import threading
import unicodedata
import webbrowser
from datetime import datetime, timedelta

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from sentinela import __version__
from sentinela.painel import banco, fila
from sentinela.painel.icones import icone
from sentinela.roteiro import COMANDOS, MODELO_ROTEIRO, ErroRoteiro, carregar_roteiro, detectar_tipo, eh_gherkin

PORTA = 8765


def _recurso(*partes) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "sentinela", "painel", *partes)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *partes)


app = Flask(__name__, template_folder=_recurso("templates"), static_folder=_recurso("static"))
app.secret_key = os.urandom(16)
app.jinja_env.globals.update(icone=icone, versao=__version__, FINALIDADES=banco.FINALIDADES,
                             STATUS_DEFEITO=banco.STATUS_DEFEITO,
                             TIPOS={"web": "Web", "desktop": "Desktop", "api": "API", "suite": "Suíte"},
                             ICONE_TIPO={"web": "web", "desktop": "desktop", "api": "terminal", "suite": "camada"})


# ======================================================================= utilidades
def _slug(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:40] or "roteiro"


def _pasta_roteiros() -> str:
    p = os.path.join(banco.pasta_dados(), "roteiros")
    os.makedirs(p, exist_ok=True)
    return p


def _caminho_env() -> str:
    return os.path.join(banco.pasta_base(), ".env")


def _ler_env() -> dict:
    valores = {}
    if os.path.isfile(_caminho_env()):
        with open(_caminho_env(), encoding="utf-8-sig") as f:
            for linha in f:
                if "=" in linha and not linha.lstrip().startswith("#"):
                    k, _, v = linha.partition("=")
                    valores[k.strip()] = v.strip()
    return valores


def _gravar_env(novos: dict):
    """Atualiza só as chaves informadas no .env, preservando o resto do arquivo."""
    linhas = []
    if os.path.isfile(_caminho_env()):
        with open(_caminho_env(), encoding="utf-8-sig") as f:
            linhas = f.read().splitlines()
    pendentes = dict(novos)
    for i, linha in enumerate(linhas):
        k = linha.partition("=")[0].strip()
        if k in pendentes and not linha.lstrip().startswith("#"):
            linhas[i] = f"{k}={pendentes.pop(k)}"
    if not linhas:
        linhas.append("# Configuração local do Sentinela QA — NÃO enviar para o GitHub")
    linhas += [f"{k}={v}" for k, v in pendentes.items()]
    with open(_caminho_env(), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    for k, v in novos.items():   # vale na hora, sem reiniciar
        os.environ[k] = v


def _chave_ia() -> str:
    return os.getenv("GEMINI_API_KEY") or _ler_env().get("GEMINI_API_KEY", "")


def _ia_status() -> dict:
    chave = _chave_ia()
    provedor = os.getenv("SENTINELA_IA") or _ler_env().get("SENTINELA_IA", "gemini")
    return {
        "configurada": bool(chave) and provedor != "nenhuma",
        "mascara": ("•" * 8 + chave[-4:]) if chave else "",
        "provedor": provedor,
        "modelo": os.getenv("SENTINELA_MODELO_IA") or _ler_env().get("SENTINELA_MODELO_IA", "gemini-3.5-flash"),
    }


def _tem_exploracao(arquivo: str) -> bool:
    try:
        return bool(carregar_roteiro(arquivo).exploracao)
    except Exception:
        return False


def _tempo_relativo(quando: str) -> str:
    try:
        d = datetime.now() - datetime.strptime(quando, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ""
    s = int(d.total_seconds())
    if s < 60:
        return "agora mesmo"
    if s < 3600:
        return f"há {s // 60} min"
    if s < 86400:
        return f"há {s // 3600} h"
    return f"há {d.days} dia(s)"


app.jinja_env.filters["relativo"] = _tempo_relativo
app.jinja_env.filters["data_br"] = lambda q: (datetime.strptime(q, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M") if q else "-")


@app.context_processor
def _contexto_global():
    abertos = banco.consulta("SELECT COUNT(*) n FROM defeitos WHERE status IN ('Aberto','Em análise')", um=True)["n"]
    rodando = banco.consulta("SELECT COUNT(*) n FROM execucoes WHERE status IN ('Na fila','Executando')", um=True)["n"]
    return {"menu_defeitos": abertos, "menu_rodando": rodando, "ia": _ia_status(),
            "pagina": request.endpoint or ""}


# ======================================================================= painel
@app.route("/")
def painel():
    q = banco.consulta
    total_proj = q("SELECT COUNT(*) n FROM projetos", um=True)["n"]
    if total_proj == 0:
        return render_template("boas_vindas.html")

    soma = q("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(aprovados),0) a, COUNT(*) n FROM execucoes "
             "WHERE status='Concluída'", um=True)
    taxa = round(100 * soma["a"] / soma["t"]) if soma["t"] else 0
    sev = {r["severidade"]: r["n"] for r in q(
        "SELECT severidade, COUNT(*) n FROM defeitos WHERE status IN ('Aberto','Em análise') GROUP BY severidade")}
    hoje = datetime.now().strftime("%Y-%m-%d")
    indicadores = {
        "projetos": total_proj,
        "roteiros": q("SELECT COUNT(*) n FROM roteiros", um=True)["n"],
        "execucoes": soma["n"],
        "execucoes_hoje": q("SELECT COUNT(*) n FROM execucoes WHERE criado_em LIKE ?", (hoje + "%",), um=True)["n"],
        "casos": soma["t"],
        "taxa": taxa,
        "abertos": sum(sev.values()),
        "sev": sev,
        "corrigidos": q("SELECT COUNT(*) n FROM defeitos WHERE status IN ('Corrigido','Fechado')", um=True)["n"],
        "sugestoes": q("SELECT COALESCE(SUM(sugestoes),0) n FROM execucoes", um=True)["n"],
        "responsavel": banco.pref("responsavel", ""),
    }

    # Últimos 14 dias: casos aprovados x reprovados por dia
    dias = []
    for i in range(13, -1, -1):
        d = datetime.now() - timedelta(days=i)
        r = q("SELECT COALESCE(SUM(aprovados),0) a, COALESCE(SUM(reprovados),0) r FROM execucoes "
              "WHERE status='Concluída' AND criado_em LIKE ?", (d.strftime("%Y-%m-%d") + "%",), um=True)
        dias.append({"rotulo": d.strftime("%d/%m"), "a": r["a"], "r": r["r"]})
    maximo = max([d["a"] + d["r"] for d in dias] + [1])

    por_projeto = q(
        "SELECT p.id, p.nome, p.tipo, p.cor, COUNT(e.id) execs, COALESCE(SUM(e.aprovados),0) a, "
        "COALESCE(SUM(e.total),0) t, (SELECT COUNT(*) FROM defeitos d WHERE d.projeto_id=p.id "
        "AND d.status IN ('Aberto','Em análise')) abertos, MAX(e.criado_em) ultima "
        "FROM projetos p LEFT JOIN execucoes e ON e.projeto_id=p.id AND e.status='Concluída' "
        "GROUP BY p.id ORDER BY ultima DESC NULLS LAST, p.nome")
    pendencias = {
        "criticos": q("SELECT COUNT(*) n FROM defeitos WHERE status='Aberto' AND severidade IN ('Crítica','Alta')", um=True)["n"],
        "em_analise": q("SELECT COUNT(*) n FROM defeitos WHERE status='Em análise'", um=True)["n"],
        "sem_execucao": q("SELECT COUNT(*) n FROM roteiros r WHERE NOT EXISTS (SELECT 1 FROM execucoes e WHERE e.roteiro_id=r.id)", um=True)["n"],
    }
    return render_template(
        "painel.html", ind=indicadores, dias=dias, maximo=maximo, por_projeto=por_projeto,
        pendencias=pendencias,
        atividades=q("SELECT * FROM atividades ORDER BY id DESC LIMIT 6"),
        ultimas=q("SELECT e.*, p.nome projeto, p.cor, r.nome roteiro FROM execucoes e JOIN projetos p ON p.id=e.projeto_id "
                  "LEFT JOIN roteiros r ON r.id=e.roteiro_id ORDER BY e.id DESC LIMIT 6"),
        hoje=datetime.now(),
    )


# ======================================================================= projetos
CORES = ["#3157d5", "#0f9d74", "#e8710a", "#8b3fd9", "#d93f5c", "#1a8fb5"]


@app.route("/projetos")
def projetos():
    lista = banco.consulta(
        "SELECT p.*, (SELECT COUNT(*) FROM roteiros r WHERE r.projeto_id=p.id) roteiros, "
        "(SELECT COUNT(*) FROM execucoes e WHERE e.projeto_id=p.id) execucoes, "
        "(SELECT COUNT(*) FROM defeitos d WHERE d.projeto_id=p.id AND d.status IN ('Aberto','Em análise')) abertos, "
        "(SELECT COALESCE(SUM(aprovados),0)*100/MAX(COALESCE(SUM(total),0),1) FROM execucoes e "
        "  WHERE e.projeto_id=p.id AND e.status='Concluída') taxa, "
        "(SELECT MAX(criado_em) FROM execucoes e WHERE e.projeto_id=p.id) ultima "
        "FROM projetos p ORDER BY p.nome")
    return render_template("projetos.html", projetos=lista)


@app.route("/projetos/novo", methods=["GET", "POST"])
@app.route("/projetos/<int:pid>/editar", methods=["GET", "POST"])
def projeto_form(pid=None):
    proj = banco.consulta("SELECT * FROM projetos WHERE id=?", (pid,), um=True) if pid else None
    if pid and not proj:
        abort(404)
    if request.method == "POST":
        f = request.form
        dados = {k: f.get(k, "").strip() for k in
                 ("nome", "tipo", "alvo", "finalidade", "versao", "responsavel", "ambiente", "cor")}
        erros = []
        if not dados["nome"]:
            erros.append("Informe o nome do sistema.")
        if not dados["alvo"]:
            erros.append("Informe o alvo (URL do site ou caminho do .exe).")
        else:
            try:
                dados["tipo"] = detectar_tipo(dados["alvo"], dados["tipo"] or None)
            except ErroRoteiro as e:
                erros.append(str(e))
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("projeto_form.html", proj=dados | {"id": pid}, cores=CORES)
        dados["cor"] = dados["cor"] or CORES[0]
        if pid:
            banco.executar("UPDATE projetos SET nome=?, tipo=?, alvo=?, finalidade=?, versao=?, responsavel=?, "
                           "ambiente=?, cor=? WHERE id=?", (*dados.values(), pid))
            banco.registrar_atividade("projeto", f"Projeto “{dados['nome']}” atualizado", f"/projetos/{pid}")
        else:
            pid = banco.executar("INSERT INTO projetos (nome, tipo, alvo, finalidade, versao, responsavel, ambiente, "
                                 "cor, criado_em) VALUES (?,?,?,?,?,?,?,?,?)", (*dados.values(), banco.agora()))
            banco.registrar_atividade("projeto", f"Projeto “{dados['nome']}” cadastrado", f"/projetos/{pid}")
        flash("Projeto salvo.", "ok")
        return redirect(url_for("projeto_detalhe", pid=pid))
    padrao = {"responsavel": banco.pref("responsavel", ""), "ambiente": banco.pref("ambiente", ""),
              "cor": CORES[banco.consulta("SELECT COUNT(*) n FROM projetos", um=True)["n"] % len(CORES)]}
    return render_template("projeto_form.html", proj=proj or padrao, cores=CORES)


@app.route("/projetos/<int:pid>")
def projeto_detalhe(pid):
    proj = banco.consulta("SELECT * FROM projetos WHERE id=?", (pid,), um=True) or abort(404)
    roteiros = banco.consulta(
        "SELECT r.*, (SELECT COUNT(*) FROM execucoes e WHERE e.roteiro_id=r.id) execs, "
        "(SELECT status||'|'||aprovados||'|'||total FROM execucoes e WHERE e.roteiro_id=r.id ORDER BY id DESC LIMIT 1) ultima "
        "FROM roteiros r WHERE projeto_id=? ORDER BY nome", (pid,))
    execs = banco.consulta("SELECT e.*, r.nome roteiro, p.nome projeto, p.cor FROM execucoes e "
                           "JOIN projetos p ON p.id=e.projeto_id LEFT JOIN roteiros r ON r.id=e.roteiro_id "
                           "WHERE e.projeto_id=? ORDER BY e.id DESC LIMIT 15", (pid,))
    defeitos = banco.consulta("SELECT * FROM defeitos WHERE projeto_id=? ORDER BY "
                              "CASE status WHEN 'Aberto' THEN 0 WHEN 'Em análise' THEN 1 ELSE 2 END, id DESC LIMIT 20", (pid,))
    return render_template("projeto_detalhe.html", proj=proj, roteiros=roteiros, execs=execs, defeitos=defeitos)


@app.post("/projetos/<int:pid>/excluir")
def projeto_excluir(pid):
    proj = banco.consulta("SELECT * FROM projetos WHERE id=?", (pid,), um=True) or abort(404)
    banco.executar("DELETE FROM projetos WHERE id=?", (pid,))
    banco.registrar_atividade("projeto", f"Projeto “{proj['nome']}” excluído")
    flash(f"Projeto “{proj['nome']}” excluído (os arquivos de relatório continuam na pasta dados).", "ok")
    return redirect(url_for("projetos"))


# ======================================================================= roteiros
@app.route("/roteiros")
def roteiros():
    lista = banco.consulta(
        "SELECT r.*, p.nome projeto, p.cor, p.tipo, (SELECT COUNT(*) FROM execucoes e WHERE e.roteiro_id=r.id) execs "
        "FROM roteiros r JOIN projetos p ON p.id=r.projeto_id ORDER BY p.nome, r.nome")
    for r in lista:
        try:
            rot = carregar_roteiro(r["arquivo"])
            r["casos"], r["valido"], r["exploracao"] = len(rot.casos), True, bool(rot.exploracao)
        except Exception:
            r["casos"], r["valido"], r["exploracao"] = 0, False, False
    return render_template("roteiros.html", roteiros=lista)


def _modelo_para(proj: dict | None) -> str:
    texto = MODELO_ROTEIRO
    if proj:
        texto = (texto.replace("sistema: Meu Sistema", f"sistema: {proj['nome']}")
                 .replace('versao: "1.0"', f'versao: "{proj["versao"] or "1.0"}"')
                 .replace("responsavel: Seu Nome", f"responsavel: {proj['responsavel'] or 'Seu Nome'}")
                 .replace("alvo: https://www.saucedemo.com      # ou o caminho de um .exe",
                          f"alvo: {proj['alvo']}"))
    return texto


@app.route("/roteiros/novo", methods=["GET", "POST"])
@app.route("/roteiros/<int:rid>", methods=["GET", "POST"])
def roteiro_editor(rid=None):
    rot = banco.consulta("SELECT * FROM roteiros WHERE id=?", (rid,), um=True) if rid else None
    if rid and not rot:
        abort(404)
    projetos_ = banco.consulta("SELECT * FROM projetos ORDER BY nome")
    if not projetos_:
        flash("Cadastre um projeto antes de criar roteiros.", "erro")
        return redirect(url_for("projeto_form"))

    if request.method == "POST":
        f = request.form
        projeto_id = int(f.get("projeto_id"))
        nome = f.get("nome", "").strip() or "Roteiro sem nome"
        conteudo = f.get("conteudo", "")
        if "arquivo" in request.files and request.files["arquivo"].filename:
            conteudo = request.files["arquivo"].read().decode("utf-8-sig")
        extensao = ".feature" if eh_gherkin(conteudo) else ".yaml"
        caminho = rot["arquivo"] if rot else os.path.join(
            _pasta_roteiros(), f"{projeto_id}_{_slug(nome)}_{datetime.now():%H%M%S}{extensao}")
        # Valida antes de salvar (num arquivo temporário na mesma pasta, para caminhos relativos)
        tmp = caminho + ".validando"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(conteudo)
        try:
            carregar_roteiro(tmp)
        except ErroRoteiro as e:
            os.remove(tmp)
            flash(f"O roteiro não foi salvo: {e}", "erro")
            return render_template("roteiro_editor.html", rot={"id": rid, "nome": nome, "projeto_id": projeto_id,
                                   "descricao": f.get("descricao", "")}, conteudo=conteudo, projetos=projetos_)
        os.replace(tmp, caminho)
        if rot:
            banco.executar("UPDATE roteiros SET projeto_id=?, nome=?, descricao=?, atualizado_em=? WHERE id=?",
                           (projeto_id, nome, f.get("descricao", ""), banco.agora(), rid))
            banco.registrar_atividade("roteiro", f"Roteiro “{nome}” atualizado", f"/roteiros/{rid}")
        else:
            rid = banco.executar("INSERT INTO roteiros (projeto_id, nome, arquivo, descricao, criado_em, atualizado_em) "
                                 "VALUES (?,?,?,?,?,?)", (projeto_id, nome, caminho, f.get("descricao", ""),
                                                          banco.agora(), banco.agora()))
            banco.registrar_atividade("roteiro", f"Roteiro “{nome}” criado", f"/roteiros/{rid}")
        flash("Roteiro salvo e validado.", "ok")
        return redirect(url_for("roteiro_editor", rid=rid))

    if rot:
        with open(rot["arquivo"], encoding="utf-8-sig") as fh:
            conteudo = fh.read()
    else:
        pid = request.args.get("projeto", type=int) or projetos_[0]["id"]
        proj = next((p for p in projetos_ if p["id"] == pid), projetos_[0])
        rot = {"projeto_id": proj["id"], "nome": "", "descricao": ""}
        conteudo = _modelo_para(proj)
    return render_template("roteiro_editor.html", rot=rot, conteudo=conteudo, projetos=projetos_)


@app.post("/api/roteiros/validar")
def api_validar():
    conteudo = request.get_json(force=True).get("conteudo", "")
    tmp = os.path.join(_pasta_roteiros(), "_validacao.yaml")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(conteudo)
    try:
        rot = carregar_roteiro(tmp)
    except ErroRoteiro as e:
        return jsonify(ok=False, erro=str(e))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return jsonify(ok=True, casos=[{"id": c.id, "descricao": c.descricao, "passos": len(c.passos)} for c in rot.casos],
                   exploracao=bool(rot.exploracao), sistema=rot.sistema)


@app.post("/roteiros/<int:rid>/excluir")
def roteiro_excluir(rid):
    rot = banco.consulta("SELECT * FROM roteiros WHERE id=?", (rid,), um=True) or abort(404)
    banco.executar("DELETE FROM roteiros WHERE id=?", (rid,))
    banco.registrar_atividade("roteiro", f"Roteiro “{rot['nome']}” excluído")
    flash("Roteiro excluído.", "ok")
    return redirect(url_for("roteiros"))


# ======================================================================= executar
@app.route("/executar", methods=["GET", "POST"])
def executar():
    if request.method == "POST":
        f = request.form
        rid = f.get("roteiro_id", type=int)
        rot = banco.consulta("SELECT * FROM roteiros WHERE id=?", (rid,), um=True)
        if not rot:
            flash("Escolha um roteiro.", "erro")
            return redirect(url_for("executar"))
        finalidade = f.get("finalidade_outra", "").strip() or f.get("finalidade", "")
        eid = banco.executar(
            "INSERT INTO execucoes (projeto_id, roteiro_id, finalidade, observacoes, explorar, usar_ia, visivel, status,"
            " criado_em) VALUES (?,?,?,?,?,?,?,?,?)",
            (rot["projeto_id"], rid, finalidade, f.get("observacoes", ""), int(bool(f.get("explorar"))),
             int(bool(f.get("usar_ia"))), int(bool(f.get("visivel"))), "Na fila", banco.agora()))
        proj = banco.consulta("SELECT nome FROM projetos WHERE id=?", (rot["projeto_id"],), um=True)
        banco.registrar_atividade("execucao", f"Execução #{eid} iniciada: {proj['nome']} — {rot['nome']} ({finalidade or 'sem finalidade'})",
                                  f"/execucoes/{eid}")
        fila.enfileirar(eid)
        return redirect(url_for("execucao_detalhe", eid=eid))

    projetos_ = banco.consulta("SELECT * FROM projetos ORDER BY nome")
    roteiros_ = banco.consulta("SELECT r.id, r.nome, r.projeto_id, r.arquivo FROM roteiros r ORDER BY r.nome")
    for r in roteiros_:
        r["exploracao"] = _tem_exploracao(r["arquivo"])
        del r["arquivo"]
    return render_template("executar.html", projetos=projetos_, roteiros=roteiros_,
                           sel_projeto=request.args.get("projeto", type=int),
                           sel_roteiro=request.args.get("roteiro", type=int))


# ======================================================================= execuções
@app.route("/execucoes")
def execucoes():
    filtro_proj = request.args.get("projeto", type=int)
    sql = ("SELECT e.*, p.nome projeto, p.cor, p.tipo, r.nome roteiro FROM execucoes e JOIN projetos p ON p.id=e.projeto_id "
           "LEFT JOIN roteiros r ON r.id=e.roteiro_id ")
    params = ()
    if filtro_proj:
        sql += "WHERE e.projeto_id=? "
        params = (filtro_proj,)
    lista = banco.consulta(sql + "ORDER BY e.id DESC LIMIT 200", params)
    return render_template("execucoes.html", execucoes=lista, projetos=banco.consulta("SELECT id, nome FROM projetos ORDER BY nome"),
                           filtro_proj=filtro_proj)


def _execucao(eid):
    return banco.consulta("SELECT e.*, p.nome projeto, p.cor, p.tipo, p.alvo, r.nome roteiro, r.arquivo FROM execucoes e "
                          "JOIN projetos p ON p.id=e.projeto_id LEFT JOIN roteiros r ON r.id=e.roteiro_id WHERE e.id=?",
                          (eid,), um=True)


@app.route("/execucoes/<int:eid>")
def execucao_detalhe(eid):
    ex = _execucao(eid) or abort(404)
    defeitos = banco.consulta("SELECT * FROM defeitos WHERE execucao_id=? ORDER BY id", (eid,))
    sugestoes, observacoes = [], []
    if ex["pasta_relatorio"]:
        caminho = os.path.join(banco.pasta_dados(), ex["pasta_relatorio"], "relatorio.json")
        if os.path.isfile(caminho):
            with open(caminho, encoding="utf-8") as fh:
                dados = json.load(fh)
            sugestoes, observacoes = dados.get("sugestoes", []), dados.get("observacoes", [])
    arquivo = os.path.relpath(ex["arquivo"], banco.pasta_base()) if ex["arquivo"] else None
    partes = [f'sentinela rodar --roteiro "{arquivo}"' if arquivo else "sentinela rodar", f'--alvo "{ex["alvo"]}"']
    if ex["explorar"]:
        partes.append("--explorar")
    if not ex["usar_ia"]:
        partes.append("--sem-ia")
    if ex["visivel"]:
        partes.append("--visivel")
    return render_template("execucao.html", ex=ex, defeitos=defeitos, sugestoes=sugestoes,
                           observacoes=observacoes, comando=" ".join(partes))


@app.get("/api/execucoes/<int:eid>")
def api_execucao(eid):
    ex = banco.consulta("SELECT status, aprovados, reprovados, total, defeitos, log FROM execucoes WHERE id=?", (eid,), um=True) or abort(404)
    if ex["status"] in ("Na fila", "Executando"):
        # Enquanto roda, os números são contados a partir do log ao vivo
        linhas = list(fila.log_ao_vivo(eid))
        aprov = sum("→ APROVADO" in l for l in linhas)
        reprov = sum("→ REPROVADO" in l for l in linhas)
        bugs = reprov + sum("Sistema ACEITOU" in l for l in linhas)
        return jsonify(status=ex["status"], log=linhas[-400:], aprovados=aprov, reprovados=reprov,
                       total=aprov + reprov, defeitos=bugs)
    linhas = (ex["log"] or "").splitlines()
    return jsonify(status=ex["status"], log=linhas[-400:], aprovados=ex["aprovados"], reprovados=ex["reprovados"],
                   total=ex["total"], defeitos=ex["defeitos"])


@app.post("/execucoes/<int:eid>/repetir")
def execucao_repetir(eid):
    ex = banco.consulta("SELECT * FROM execucoes WHERE id=?", (eid,), um=True) or abort(404)
    novo = banco.executar(
        "INSERT INTO execucoes (projeto_id, roteiro_id, finalidade, observacoes, explorar, usar_ia, visivel, status, criado_em)"
        " VALUES (?,?,?,?,?,?,?,?,?)", (ex["projeto_id"], ex["roteiro_id"], ex["finalidade"], f"Repetição da execução #{eid}",
                                        ex["explorar"], ex["usar_ia"], ex["visivel"], "Na fila", banco.agora()))
    banco.registrar_atividade("execucao", f"Execução #{novo} iniciada (repetição da #{eid})", f"/execucoes/{novo}")
    fila.enfileirar(novo)
    return redirect(url_for("execucao_detalhe", eid=novo))


@app.post("/execucoes/<int:eid>/excluir")
def execucao_excluir(eid):
    ex = banco.consulta("SELECT * FROM execucoes WHERE id=?", (eid,), um=True) or abort(404)
    if ex["status"] in ("Na fila", "Executando"):
        flash("Não é possível excluir uma execução em andamento.", "erro")
        return redirect(url_for("execucao_detalhe", eid=eid))
    banco.executar("DELETE FROM execucoes WHERE id=?", (eid,))
    if ex["pasta_relatorio"]:
        shutil.rmtree(os.path.join(banco.pasta_dados(), ex["pasta_relatorio"]), ignore_errors=True)
    flash(f"Execução #{eid} excluída.", "ok")
    return redirect(url_for("execucoes"))


@app.route("/execucoes/<int:eid>/arquivos/<path:arquivo>")
def execucao_arquivo(eid, arquivo):
    ex = banco.consulta("SELECT pasta_relatorio FROM execucoes WHERE id=?", (eid,), um=True)
    if not ex or not ex["pasta_relatorio"]:
        abort(404)
    return send_from_directory(os.path.join(banco.pasta_dados(), ex["pasta_relatorio"]), arquivo)


# ======================================================================= defeitos
@app.route("/defeitos")
def defeitos():
    filtros, lista = _defeitos_filtrados()
    contagem = {r["status"]: r["n"] for r in banco.consulta("SELECT status, COUNT(*) n FROM defeitos GROUP BY status")}
    return render_template("defeitos.html", defeitos=lista, filtros=filtros, contagem=contagem,
                           projetos=banco.consulta("SELECT id, nome FROM projetos ORDER BY nome"))


@app.route("/defeitos/exportar.csv")
def defeitos_csv():
    """Exporta os defeitos (com os mesmos filtros da tela) em CSV — abre direto no Excel."""
    import csv
    import io
    _, lista = _defeitos_filtrados()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Código", "Projeto", "Execução", "Descrição", "Severidade", "Status", "Origem", "Caso",
                "Passos para reproduzir", "Esperado", "Obtido", "Comentário", "Registrado em"])
    for d in lista:
        passos = " | ".join(f"{i}. {p}" for i, p in enumerate(json.loads(d["passos"] or "[]"), 1))
        w.writerow([d["codigo"], d["projeto"], d["execucao_id"], d["descricao"], d["severidade"], d["status"],
                    d["origem"], d["caso_id"], passos, d["esperado"], d["obtido"], d["comentario"], d["criado_em"]])
    nome = f"defeitos_{datetime.now():%Y%m%d_%H%M}.csv"
    return app.response_class("﻿" + buf.getvalue(), mimetype="text/csv",
                              headers={"Content-Disposition": f"attachment; filename={nome}"})


SEVERIDADE_AZURE = {"Crítica": "1 - Critical", "Alta": "2 - High", "Média": "3 - Medium", "Baixa": "4 - Low"}


@app.route("/defeitos/exportar_azure.csv")
def defeitos_azure():
    """CSV para importar no Azure DevOps (Boards > Queries > Import Work Items), como itens do tipo Bug."""
    import csv
    import io
    from html import escape
    _, lista = _defeitos_filtrados()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Work Item Type", "Title", "Severity", "Repro Steps", "Tags"])
    for d in lista:
        passos = "".join(f"<li>{escape(p)}</li>" for p in json.loads(d["passos"] or "[]"))
        repro = (f"<ol>{passos}</ol><p><b>Esperado:</b> {escape(d['esperado'] or '-')}</p>"
                 f"<p><b>Obtido:</b> {escape(d['obtido'] or '-')}</p>")
        w.writerow(["Bug", f"{d['codigo']} - {d['descricao']}"[:255],
                    SEVERIDADE_AZURE.get(d["severidade"], "3 - Medium"), repro, f"Sentinela; {d['projeto']}"])
    nome = f"defeitos_azure_{datetime.now():%Y%m%d_%H%M}.csv"
    return app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv",
                              headers={"Content-Disposition": f"attachment; filename={nome}"})


def texto_jira(d: dict) -> str:
    """Defeito no formato de texto do Jira (wiki markup), pronto para colar."""
    passos = "\n".join(f"# {p}" for p in d["passos"])
    return (f"h3. {d['codigo']} — {d['descricao']}\n"
            f"*Projeto:* {d['projeto']}  |  *Severidade:* {d['severidade']}  |  *Origem:* {d['origem']}"
            f"{'  |  *Caso:* ' + d['caso_id'] if d['caso_id'] else ''}\n\n"
            f"*Passos para reproduzir*\n{passos}\n\n"
            f"*Resultado esperado*\n{d['esperado'] or '-'}\n\n"
            f"*Resultado obtido*\n{d['obtido'] or '-'}\n\n"
            f"*Evidência:* anexar o print {(d['evidencia'] or '').split('/')[-1] or '(sem print)'}\n"
            f"_Registrado pelo Sentinela QA (execução #{d['execucao_id']})_")


def _defeitos_filtrados():
    filtros = {k: request.args.get(k, "") for k in ("projeto", "status", "severidade", "origem")}
    sql = ("SELECT d.*, p.nome projeto, p.cor FROM defeitos d JOIN projetos p ON p.id=d.projeto_id WHERE 1=1 ")
    params = []
    if filtros["projeto"]:
        sql += "AND d.projeto_id=? "
        params.append(int(filtros["projeto"]))
    if filtros["status"] == "pendentes":
        sql += "AND d.status IN ('Aberto','Em análise') "
    elif filtros["status"]:
        sql += "AND d.status=? "
        params.append(filtros["status"])
    if filtros["severidade"]:
        sql += "AND d.severidade=? "
        params.append(filtros["severidade"])
    if filtros["origem"]:
        sql += "AND d.origem=? "
        params.append(filtros["origem"])
    sql += ("ORDER BY CASE d.status WHEN 'Aberto' THEN 0 WHEN 'Em análise' THEN 1 ELSE 2 END, "
            "CASE d.severidade WHEN 'Crítica' THEN 0 WHEN 'Alta' THEN 1 WHEN 'Média' THEN 2 ELSE 3 END, d.id DESC")
    return filtros, banco.consulta(sql, params)


@app.route("/defeitos/<int:did>", methods=["GET", "POST"])
def defeito_detalhe(did):
    d = banco.consulta("SELECT d.*, p.nome projeto, p.cor, e.finalidade FROM defeitos d JOIN projetos p ON p.id=d.projeto_id "
                       "JOIN execucoes e ON e.id=d.execucao_id WHERE d.id=?", (did,), um=True) or abort(404)
    if request.method == "POST":
        status = request.form.get("status")
        comentario = request.form.get("comentario", "").strip()
        if status in banco.STATUS_DEFEITO:
            banco.executar("UPDATE defeitos SET status=?, comentario=?, atualizado_em=? WHERE id=?",
                           (status, comentario, banco.agora(), did))
            if status != d["status"]:
                banco.registrar_atividade("defeito", f"{d['codigo']} ({d['projeto']}) mudou de “{d['status']}” para “{status}”",
                                          f"/defeitos/{did}")
            flash("Defeito atualizado.", "ok")
        return redirect(url_for("defeito_detalhe", did=did))
    d["passos"] = json.loads(d["passos"] or "[]")
    return render_template("defeito.html", d=d, jira=texto_jira(d))


# ======================================================================= configurações
@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        f = request.form
        novos = {"SENTINELA_IA": f.get("provedor", "gemini"), "SENTINELA_MODELO_IA": f.get("modelo", "").strip() or "gemini-3.5-flash"}
        if f.get("chave", "").strip():
            novos["GEMINI_API_KEY"] = f.get("chave").strip()
        if f.get("remover_chave"):
            novos["GEMINI_API_KEY"] = ""
        _gravar_env(novos)
        banco.salvar_pref("responsavel", f.get("responsavel", "").strip())
        banco.salvar_pref("ambiente", f.get("ambiente", "").strip())
        banco.registrar_atividade("config", "Configurações atualizadas")
        flash("Configurações salvas (a chave fica só no arquivo .env deste computador).", "ok")
        return redirect(url_for("configuracoes"))
    return render_template("configuracoes.html", responsavel=banco.pref("responsavel", ""),
                           ambiente=banco.pref("ambiente", ""), caminho_env=_caminho_env(),
                           pasta_dados=banco.pasta_dados())


@app.post("/api/ia/testar")
def api_testar_ia():
    chave = _chave_ia()
    if not chave:
        return jsonify(ok=False, msg="Nenhuma chave configurada.")
    try:
        from google import genai
        from google.genai import types
        cliente = genai.Client(api_key=chave, http_options=types.HttpOptions(timeout=20_000))
        nomes = [m.name.split("/")[-1] for m in cliente.models.list() if "generateContent" in (m.supported_actions or [])]
    except Exception as e:
        return jsonify(ok=False, msg=f"Falhou: {str(e)[:160]}")
    flash_ = sorted([n for n in nomes if "flash" in n and "image" not in n], reverse=True)
    return jsonify(ok=True, msg=f"Chave válida. {len(nomes)} modelos liberados.", modelos=flash_[:12])


# Projetos de exemplo (nome, tipo, alvo, finalidade, arquivo do roteiro, nome do roteiro, cor)
EXEMPLOS = [
    ("Sauce Demo", "web", "https://www.saucedemo.com", "Loja de demonstração: login, carrinho e checkout",
     "web_saucedemo.yaml", "Fluxo de compra + exploração", "#3157d5"),
    ("The Internet", "web", "https://the-internet.herokuapp.com", "Site de prática de automação: componentes de interface",
     "web_the_internet.yaml", "Interações web (com 1 falha proposital)", "#0f9d74"),
    ("Calculadora do Windows", "desktop", "calc.exe", "Programa desktop: operações e tratamento de erro",
     "desktop_calculadora.yaml", "Operações básicas", "#e8710a"),
    ("Loja Treino (local)", "web", "http://127.0.0.1:8000", "Site local do Sentinela: login, busca, cadastro com bug plantado",
     "web_site_treino.yaml", "Login, busca e cadastro + exploração", "#8b3fd9"),
    ("Loja Treino (local)", "web", "http://127.0.0.1:8000", "",
     "gherkin_site_treino.feature", "Cenários em Gherkin (BDD)", "#8b3fd9"),
    ("APIs ViaCEP e JSONPlaceholder", "api", "https://viacep.com.br", "Testes de API: status, contrato JSON e tempo de resposta",
     "api_viacep.yaml", "Consulta de CEP e POST", "#1a8fb5"),
    ("APIs públicas gratuitas", "api", "https://brasilapi.com.br",
     "BrasilAPI, Restful-Booker (CRUD com token), DummyJSON (JWT), PokeAPI, GraphQL e Open-Meteo — sem chaves",
     "api_publicas.yaml", "Autenticação, CRUD, GraphQL e contrato", "#0e7490"),
    ("Loja PHP (XAMPP)", "web", "http://localhost/sentinela-loja",
     "Sistema PHP + MySQL no XAMPP: tela, API REST e conferência no banco (instale em Banco de dados > XAMPP)",
     "web_loja_php.yaml", "Tela + API + banco + exploração", "#0f766e"),
    ("Estoque Desktop (WinForms)", "desktop", "sistemas_treino/estoque_desktop/EstoqueDesktop.exe",
     "Sistema desktop em C#/WinForms com login, cadastro, busca e um bug plantado",
     "desktop_estoque.yaml", "Login, cadastro e validações", "#b45309"),
    ("Loja Treino (local)", "web", "http://127.0.0.1:8000", "",
     "web_site_treino_selenium.yaml", "Mesmo roteiro rodando com Selenium WebDriver", "#8b3fd9"),
    ("Suítes de outros frameworks", "suite", "exemplos_frameworks",
     "Pytest, Jest, Newman (Postman) e Playwright TS rodados pelo Sentinela — resultados no mesmo relatório (JUnit XML)",
     "suite_pytest_unitario.yaml", "Pytest — testes unitários (regras de preço)", "#475569"),
    ("Suítes de outros frameworks", "suite", "exemplos_frameworks", "",
     "suite_jest_unitario.yaml", "Jest — testes unitários (carrinho)", "#475569"),
    ("Suítes de outros frameworks", "suite", "exemplos_frameworks", "",
     "suite_newman_postman.yaml", "Newman — coleção do Postman (API ViaCEP)", "#475569"),
    ("Suítes de outros frameworks", "suite", "exemplos_frameworks", "",
     "suite_playwright_ts.yaml", "Playwright TypeScript (Loja Treino)", "#475569"),
]


def sincronizar_exemplos() -> int:
    """Adiciona os projetos/roteiros de exemplo que ainda não existem (não duplica nem altera os seus).
    Devolve quantos roteiros novos entraram."""
    origem = os.path.join(banco.pasta_base(), "roteiros")
    if not os.path.isdir(origem):
        return -1
    destino = _pasta_roteiros()
    for sub in ("arquivos", "esquemas", "colecoes"):
        if os.path.isdir(os.path.join(origem, sub)):
            shutil.copytree(os.path.join(origem, sub), os.path.join(destino, sub), dirs_exist_ok=True)
    novos = 0
    for nome, tipo, alvo, finalidade, arq, nome_rot, cor in EXEMPLOS:
        if not os.path.isfile(os.path.join(origem, arq)):
            continue
        proj = banco.consulta("SELECT id FROM projetos WHERE nome=?", (nome,), um=True)
        if proj:
            pid = proj["id"]
            if banco.consulta("SELECT 1 FROM roteiros WHERE projeto_id=? AND nome=?", (pid, nome_rot), um=True):
                continue
        else:
            pid = banco.executar("INSERT INTO projetos (nome, tipo, alvo, finalidade, versao, responsavel, ambiente, cor, criado_em)"
                                 " VALUES (?,?,?,?,?,?,?,?,?)", (nome, tipo, alvo, finalidade, "demo",
                                                                 banco.pref("responsavel", "") or "Mateus", "Demonstração pública",
                                                                 cor, banco.agora()))
        caminho = os.path.join(destino, arq)
        shutil.copyfile(os.path.join(origem, arq), caminho)
        banco.executar("INSERT INTO roteiros (projeto_id, nome, arquivo, descricao, criado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
                       (pid, nome_rot, caminho, "Exemplo incluído no Sentinela QA", banco.agora(), banco.agora()))
        novos += 1
    return novos


@app.post("/exemplos/importar")
def importar_exemplos():
    """Cria os projetos de demonstração que faltarem (web, desktop, APIs, suítes de frameworks...)."""
    novos = sincronizar_exemplos()
    if novos < 0:
        flash("Pasta 'roteiros' de exemplo não encontrada ao lado do programa.", "erro")
        return redirect(url_for("painel"))
    if novos:
        banco.registrar_atividade("projeto", f"{novos} roteiro(s) de exemplo importado(s)", "/projetos")
    flash(f"{novos} roteiro(s) de exemplo novo(s) importado(s)." if novos else "Os exemplos já estavam todos importados.", "ok")
    return redirect(url_for("painel"))


# ======================================================================= testar API (estilo Postman)
VERIFICACOES_API = {
    "status": "Status HTTP é", "status_entre": "Status HTTP entre", "json_igual": "Campo JSON é igual a",
    "json_contem": "Campo JSON contém", "json_existe": "Campo JSON existe", "json_ausente": "Campo JSON NÃO existe",
    "json_tipo": "Campo JSON é do tipo", "tempo": "Responde em até (ms)", "cabecalho": "Cabeçalho contém",
    "esquema": "Corpo segue o JSON Schema", "guardar": "Guardar campo em variável",
}


def _passos_verificacao(verificacoes: list[dict]) -> list[dict]:
    """Converte as verificações da tela em passos de roteiro do Sentinela."""
    passos = []
    for v in verificacoes:
        tipo, campo, valor = v.get("tipo"), (v.get("campo") or "").strip(), v.get("valor")
        if tipo == "status":
            passos.append({"verificar_status": int(valor)})
        elif tipo == "status_entre":
            a, _, b = str(valor).partition("-")
            passos.append({"verificar_status": {"entre": [int(a), int(b or a)]}})
        elif tipo == "json_igual":
            passos.append({"verificar_json": {"campo": campo, "valor": valor}})
        elif tipo == "json_contem":
            passos.append({"verificar_json": {"campo": campo, "contem": valor}})
        elif tipo == "json_existe":
            passos.append({"verificar_json": {"campo": campo, "existe": True}})
        elif tipo == "json_ausente":
            passos.append({"verificar_json": {"campo": campo, "existe": False}})
        elif tipo == "json_tipo":
            passos.append({"verificar_json": {"campo": campo, "tipo": valor}})
        elif tipo == "tempo":
            passos.append({"verificar_tempo": {"maximo_ms": int(valor)}})
        elif tipo == "cabecalho":
            passos.append({"verificar_cabecalho": {"nome": campo, "contem": valor}})
        elif tipo == "esquema":
            passos.append({"verificar_esquema": {"esquema": json.loads(valor or "{}")}})
        elif tipo == "guardar":
            passos.append({"guardar": {"campo": campo, "como": valor}})
    return passos


def _montar_requisicao(d: dict) -> dict:
    cab = {h["k"]: h["v"] for h in d.get("cabecalhos", []) if h.get("k")}
    auth = d.get("auth") or {}
    if auth.get("tipo") == "bearer" and auth.get("token"):
        cab["Authorization"] = "Bearer " + auth["token"]
    elif auth.get("tipo") == "basic" and auth.get("usuario"):
        import base64
        cab["Authorization"] = "Basic " + base64.b64encode(f"{auth['usuario']}:{auth.get('senha', '')}".encode()).decode()
    elif auth.get("tipo") == "apikey" and auth.get("chave_nome"):
        cab[auth["chave_nome"]] = auth.get("chave_valor", "")
    req = {"metodo": d.get("metodo", "GET").upper(), "url": d.get("url", "").strip()}
    consulta = {p["k"]: p["v"] for p in d.get("consulta", []) if p.get("k")}
    if consulta:
        req["consulta"] = consulta
    if cab:
        req["cabecalhos"] = cab
    corpo = (d.get("corpo") or "").strip()
    if corpo and req["metodo"] not in ("GET", "HEAD"):
        try:
            req["corpo"] = json.loads(corpo)
        except json.JSONDecodeError:
            req["corpo_texto"] = corpo
    return req


class _AvaliadorApi:
    """Roda as verificações do Sentinela sobre uma resposta (sem criar uma execução completa)."""

    def __new__(cls, resposta):
        from types import SimpleNamespace
        from sentinela.executor_api import ComandosApi
        from sentinela.executor_qualidade import ComandosQualidade

        class Avaliador(ComandosQualidade, ComandosApi):
            pass
        a = Avaliador()
        a.resposta = resposta
        a.dados = {}
        a.page = None
        a.roteiro = SimpleNamespace(pasta=banco.pasta_dados(), tempo_limite=20)
        a.registro = SimpleNamespace(observar=lambda *x, **k: None)
        return a


@app.route("/api-tester")
def api_tester():
    projetos_ = banco.consulta("SELECT id, nome, tipo FROM projetos ORDER BY tipo='api' DESC, nome")
    roteiros_api = []
    for r in banco.consulta("SELECT r.id, r.nome, r.arquivo, p.nome projeto FROM roteiros r JOIN projetos p ON p.id=r.projeto_id "
                            "WHERE p.tipo='api' ORDER BY p.nome, r.nome"):
        roteiros_api.append(r)
    return render_template("api_tester.html", projetos=projetos_, verificacoes=VERIFICACOES_API, roteiros_api=roteiros_api)


@app.post("/api/tester/enviar")
def api_tester_enviar():
    from sentinela.erros import ErroPasso
    from sentinela.executor_api import fazer_requisicao
    d = request.get_json(force=True)
    req = _montar_requisicao(d)
    if not req["url"].startswith(("http://", "https://")):
        return jsonify(ok=False, erro="A URL precisa começar com http:// ou https://")
    try:
        resp = fazer_requisicao(req["metodo"], req["url"], req.get("cabecalhos"), req.get("corpo"), req.get("consulta"),
                                tempo_limite=30, corpo_texto=req.get("corpo_texto"))
    except ErroPasso as e:
        return jsonify(ok=False, erro=str(e))
    av = _AvaliadorApi(resp)
    resultados, variaveis = [], {}
    try:
        passos = _passos_verificacao(d.get("verificacoes", []))
    except (ValueError, json.JSONDecodeError) as e:
        return jsonify(ok=False, erro=f"Verificação mal preenchida: {e}")
    for passo in passos:
        comando, args = next(iter(passo.items()))
        try:
            msg = getattr(av, f"cmd_{comando}")(args)
            resultados.append({"ok": True, "msg": msg})
            if comando == "guardar":
                variaveis[args["como"]] = av.dados.get(args["como"])
        except Exception as e:
            resultados.append({"ok": False, "msg": str(e)})
    corpo = json.dumps(resp["json"], ensure_ascii=False, indent=2) if resp["json"] is not None else resp["texto"][:200000]
    return jsonify(ok=True, status=resp["status"], tempo_ms=resp["tempo_ms"], tamanho=resp["tamanho"],
                   cabecalhos=resp["cabecalhos"], corpo=corpo, eh_json=resp["json"] is not None,
                   resultados=resultados, variaveis=variaveis, url_final=resp["url"])


@app.post("/api/tester/salvar")
def api_tester_salvar():
    """Salva a requisição + verificações como um caso de teste num roteiro de API do projeto."""
    import yaml
    d = request.get_json(force=True)
    pid = int(d.get("projeto_id") or 0)
    proj = banco.consulta("SELECT * FROM projetos WHERE id=?", (pid,), um=True)
    if not proj:
        return jsonify(ok=False, erro="Escolha um projeto.")
    req = _montar_requisicao(d)
    for chave in ("cabecalhos", "corpo"):
        if chave in req:
            # Variáveis {{x}} do testador viram {dados.x} no roteiro
            req[chave] = json.loads(re.sub(r"\{\{\s*(\w+)\s*\}\}", r"{dados.\1}", json.dumps(req[chave], ensure_ascii=False)))
    req["url"] = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"{dados.\1}", req["url"])
    passos = [{"requisitar": req}] + _passos_verificacao(d.get("verificacoes", []))
    rot = banco.consulta("SELECT * FROM roteiros WHERE projeto_id=? AND nome='Testador de API'", (pid,), um=True)
    if rot and os.path.isfile(rot["arquivo"]):
        with open(rot["arquivo"], encoding="utf-8-sig") as f:
            dados_rot = yaml.safe_load(f) or {}
    else:
        dados_rot = {"sistema": proj["nome"], "versao": proj["versao"] or "-", "responsavel": proj["responsavel"] or "-",
                     "tipo": "api", "objetivo": "Casos de API criados no Testador de API do Sentinela.",
                     "alvo": proj["alvo"] if proj["alvo"].startswith("http") else "https://exemplo.test",
                     "tempo_limite": 20, "casos": []}
    casos = dados_rot.setdefault("casos", [])
    cid = f"CT{len(casos) + 1:02d}"
    casos.append({"id": cid, "descricao": d.get("nome") or f"{req['metodo']} {req['url']}",
                  "esperado": d.get("esperado") or "Todas as verificações passam", "passos": passos})
    texto = "# Roteiro mantido pelo Testador de API do Sentinela QA (pode editar à vontade).\n" + \
        yaml.safe_dump(dados_rot, allow_unicode=True, sort_keys=False, width=120)
    caminho = rot["arquivo"] if rot else os.path.join(_pasta_roteiros(), f"{pid}_testador_api.yaml")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    if rot:
        banco.executar("UPDATE roteiros SET atualizado_em=? WHERE id=?", (banco.agora(), rot["id"]))
        rid = rot["id"]
    else:
        rid = banco.executar("INSERT INTO roteiros (projeto_id, nome, arquivo, descricao, criado_em, atualizado_em) "
                             "VALUES (?,?,?,?,?,?)", (pid, "Testador de API", caminho,
                                                      "Casos salvos pela tela Testar API", banco.agora(), banco.agora()))
    banco.registrar_atividade("roteiro", f"Caso {cid} salvo pelo Testador de API em “{proj['nome']}”", f"/roteiros/{rid}")
    return jsonify(ok=True, msg=f"Caso {cid} salvo no roteiro “Testador de API” de {proj['nome']}.",
                   link=url_for("roteiro_editor", rid=rid))


@app.post("/postman/importar")
def postman_importar():
    from sentinela.postman import importar_colecao
    arquivo = request.files.get("colecao")
    if not arquivo or not arquivo.filename:
        flash("Escolha o arquivo .json da coleção do Postman.", "erro")
        return redirect(url_for("api_tester"))
    try:
        colecao = json.loads(arquivo.read().decode("utf-8-sig"))
        texto, est = importar_colecao(colecao)
    except Exception as e:
        flash(f"Não consegui ler a coleção: {e}", "erro")
        return redirect(url_for("api_tester"))
    nome = colecao.get("info", {}).get("name", "Coleção do Postman")
    proj = banco.consulta("SELECT id FROM projetos WHERE nome=?", (nome,), um=True)
    import yaml
    alvo = (yaml.safe_load(texto) or {}).get("alvo", "https://exemplo.test")
    pid = proj["id"] if proj else banco.executar(
        "INSERT INTO projetos (nome, tipo, alvo, finalidade, versao, responsavel, ambiente, cor, criado_em) VALUES (?,?,?,?,?,?,?,?,?)",
        (nome, "api", alvo, "Importado de uma coleção do Postman", "postman", banco.pref("responsavel", ""), "", "#ef6c00", banco.agora()))
    caminho = os.path.join(_pasta_roteiros(), f"{pid}_{_slug(nome)}_postman_{datetime.now():%H%M%S}.yaml")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    rid = banco.executar("INSERT INTO roteiros (projeto_id, nome, arquivo, descricao, criado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
                         (pid, f"Postman: {nome}", caminho, f"{est['casos']} requisição(ões) importada(s)", banco.agora(), banco.agora()))
    banco.registrar_atividade("roteiro", f"Coleção do Postman “{nome}” importada ({est['casos']} casos)", f"/roteiros/{rid}")
    flash(f"Coleção importada: {est['casos']} caso(s)" + (f"; {est['nao_convertidas']} linha(s) de teste precisam de revisão."
                                                           if est["nao_convertidas"] else "."), "ok")
    return redirect(url_for("roteiro_editor", rid=rid))


@app.route("/roteiros/<int:rid>/exportar/<formato>")
def roteiro_exportar(rid, formato):
    """Baixa o roteiro convertido para outro framework (zip)."""
    import io as _io
    import zipfile
    from sentinela.exportar import FORMATOS, exportar
    rot = banco.consulta("SELECT * FROM roteiros WHERE id=?", (rid,), um=True) or abort(404)
    if formato not in FORMATOS:
        abort(404)
    try:
        arquivos = exportar(carregar_roteiro(rot["arquivo"]), formato)
    except Exception as e:
        flash(f"Não foi possível exportar: {e}", "erro")
        return redirect(url_for("roteiro_editor", rid=rid))
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, conteudo in arquivos.items():
            z.writestr(rel, conteudo)
    banco.registrar_atividade("roteiro", f"Roteiro “{rot['nome']}” exportado para {FORMATOS[formato]}", f"/roteiros/{rid}")
    return app.response_class(buf.getvalue(), mimetype="application/zip", headers={
        "Content-Disposition": f"attachment; filename={_slug(rot['nome'])}_{formato}.zip"})


# ======================================================================= catálogo de tipos de teste
CATALOGO = [
    # (tipo, o que é, como o Sentinela faz, nível: nativo|integracao|exporta, ferramentas, link)
    ("Funcional / E2E web", "Fluxos completos no navegador, do jeito do usuário.", "Roteiros YAML/Gherkin com Playwright (padrão) ou Selenium WebDriver.", "nativo", ["Playwright", "Selenium"], "/roteiros"),
    ("Regressão e smoke", "Garantir que o que funcionava continua funcionando.", "Finalidade escolhida em Executar, filtros --casos/--pular, CI no GitHub Actions.", "nativo", ["Sentinela", "GitHub Actions"], "/executar"),
    ("API REST / GraphQL", "Status, contrato, autenticação e regras da API.", "Tela Testar API (estilo Postman) e roteiros tipo api: token, JWT, CRUD, GraphQL.", "nativo", ["urllib", "jsonschema"], "/api-tester"),
    ("Contrato de API", "A resposta segue o formato combinado.", "verificar_esquema com JSON Schema (Draft 2020-12).", "nativo", ["jsonschema"], "/ajuda"),
    ("Postman / Newman", "Coleções do Postman em linha de comando.", "Importa coleção → roteiro; exporta roteiro → coleção; roda o Newman como suíte.", "integracao", ["Postman", "Newman"], "/api-tester"),
    ("Desktop (Windows)", "Programas .exe com janela.", "pywinauto/UI Automation pelo AutomationId; PyAutoGUI só como último recurso.", "nativo", ["pywinauto", "UI Automation"], "/projetos"),
    ("Mobile web", "Site em tela de celular.", "dispositivo: \"iPhone 13\" (emulação do Playwright).", "nativo", ["Playwright devices"], "/ajuda"),
    ("Mobile nativo (Android/iOS)", "Apps instalados no celular.", "Exporta para Appium (Python) e Maestro (YAML); roda Maestro como suíte quando houver emulador.", "exporta", ["Appium", "Maestro"], "/tipos-de-teste#exportar"),
    ("Unitário", "Funções e classes isoladas (base da pirâmide).", "Roda Pytest, Jest, Vitest, JUnit 5 e TestNG e lê o JUnit XML.", "integracao", ["Pytest", "Jest", "Vitest", "JUnit 5", "TestNG"], "/projetos"),
    ("Componentes / E2E JavaScript", "Testes do time de front-end.", "Exporta e roda Cypress e Playwright TypeScript como suíte.", "integracao", ["Cypress", "Playwright TS"], "/tipos-de-teste#exportar"),
    ("BDD", "Cenários Dado/Quando/Então.", "Arquivos .feature em português viram roteiros; YAML vira Gherkin.", "nativo", ["Gherkin"], "/ajuda"),
    ("Exploratório / validação", "Procurar falhas com dados inválidos.", "Exploração com Faker pt_BR: vazio, CPF/e-mail inválido, especiais, limites.", "nativo", ["Faker"], "/executar"),
    ("Banco de dados", "Dados gravados certo e estrutura saudável.", "verificar_banco nos roteiros e Auditor de estrutura MySQL/MariaDB.", "nativo", ["PyMySQL", "mysqldump"], "/banco"),
    ("Acessibilidade", "Uso por pessoas com deficiência (WCAG).", "verificar_acessibilidade com axe-core + checagem básica em toda página.", "nativo", ["axe-core"], "/ajuda"),
    ("Desempenho", "Velocidade de carregamento.", "verificar_desempenho: carregamento, TTFB, LCP, peso.", "nativo", ["Navigation Timing"], "/ajuda"),
    ("Carga", "Comportamento com muitos acessos.", "teste_carga: vazão, média, p95 e erros com requisições simultâneas.", "nativo", ["threads"], "/ajuda"),
    ("Segurança (OWASP)", "As 14 falhas que um atacante tentaria num app feito às pressas.", "varredura_seguranca: painel admin sem login, .env/.git expostos, segredo no front-end, SQL injection, XSS, login que vaza o papel, força bruta, upload de .php, IDOR e preço vindo do cliente. Mais verificar_seguranca (cabeçalhos/cookies). Só em sistemas seus.", "nativo", ["Sentinela"], "/ajuda"),
    ("Regressão visual", "A tela mudou sem querer?", "comparar_visual com linha de base e destaque das diferenças.", "nativo", ["Pillow"], "/ajuda"),
    ("Links quebrados", "Links que levam a erro 404/500.", "verificar_links.", "nativo", ["Sentinela"], "/ajuda"),
    ("Usabilidade (assistida por IA)", "Sugestões de melhoria de texto e fluxo.", "Gemini analisa os prints e o log (opcional, por execução).", "nativo", ["Gemini"], "/configuracoes"),
    ("Auditoria de UI/UX", "O design da página está bom? O que e como melhorar?", "auditoria_ux: mede na página o contraste (WCAG AA), o tamanho das fontes, as famílias e cores usadas, os alvos de toque e o responsivo — e entrega o código pronto de cada correção. Determinístico, não depende de IA.", "nativo", ["Sentinela"], "/ajuda"),
]


def _ferramentas_instaladas() -> dict:
    import shutil
    import subprocess
    out = {}
    for nome, cmd in (("Node.js", "node"), ("npm/npx", "npx"), ("Java", "java"), ("Maven", "mvn"), ("Maestro", "maestro"),
                      ("Android (adb)", "adb"), ("Appium", "appium"), ("Google Chrome", None), ("MySQL (XAMPP)", None)):
        if cmd:
            out[nome] = bool(shutil.which(cmd))
    out["Google Chrome"] = any(os.path.isfile(p) for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                                            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"))
    from sentinela.xampp import porta_aberta
    out["MySQL (XAMPP)"] = porta_aberta(3306)
    try:
        import selenium  # noqa: F401
        out["Selenium"] = True
    except ImportError:
        out["Selenium"] = False
    return out


@app.route("/tipos-de-teste")
def tipos_teste():
    from sentinela.exportar import FORMATOS
    return render_template("tipos_teste.html", catalogo=CATALOGO, instaladas=_ferramentas_instaladas(), formatos=FORMATOS,
                           roteiros=banco.consulta("SELECT r.id, r.nome, p.nome projeto, p.tipo FROM roteiros r "
                                                   "JOIN projetos p ON p.id=r.projeto_id WHERE p.tipo IN ('web','api') ORDER BY p.nome, r.nome"))


# ======================================================================= banco de dados (auditor)
# Credenciais da conexão ficam só na memória do programa (ou no .env, se o usuário pedir para lembrar)
_conexoes: dict[int, dict] = {}


def _cred_form(f) -> dict:
    from sentinela.banco_auditor import config_padrao
    padrao = config_padrao()
    return {"host": f.get("host", "").strip() or padrao["host"], "porta": int(f.get("porta") or padrao["porta"]),
            "usuario": f.get("usuario", "").strip() or padrao["usuario"],
            "senha": f.get("senha") if f.get("senha") else padrao["senha"]}


@app.route("/banco", methods=["GET", "POST"])
def banco_dados():
    from sentinela import banco_auditor as ba
    cred = _cred_form(request.form if request.method == "POST" else {})
    bancos, erro = [], None
    if request.method == "POST" and request.form.get("acao") == "auditar":
        nome = request.form.get("banco", "")
        try:
            aud = ba.auditar(nome, cred["host"], cred["porta"], cred["usuario"], cred["senha"],
                             usar_ia=bool(request.form.get("usar_ia")), log=lambda m: None)
        except ba.ErroBanco as e:
            flash(str(e), "erro")
            return redirect(url_for("banco_dados"))
        pasta = os.path.join(banco.pasta_dados(), "auditorias", f"{_slug(nome)}_{datetime.now():%Y%m%d_%H%M%S}")
        ba.gerar_relatorio(aud, pasta)
        aid = banco.executar("INSERT INTO auditorias (host, banco, nota, achados, criticos, pasta, usou_ia, criado_em) "
                             "VALUES (?,?,?,?,?,?,?,?)",
                             (aud.host, nome, aud.resumo["nota"], aud.resumo["achados"],
                              aud.resumo["por_severidade"].get("Crítica", 0) + aud.resumo["por_severidade"].get("Alta", 0),
                              os.path.relpath(pasta, banco.pasta_dados()), int(bool(aud.sugestoes_ia)), banco.agora()))
        _conexoes[aid] = cred
        if request.form.get("lembrar"):
            _gravar_env({"SENTINELA_DB_HOST": cred["host"], "SENTINELA_DB_PORTA": str(cred["porta"]),
                         "SENTINELA_DB_USUARIO": cred["usuario"], "SENTINELA_DB_SENHA": cred["senha"]})
        banco.registrar_atividade("banco", f"Auditoria do banco “{nome}”: nota {aud.resumo['nota']}/100, "
                                  f"{aud.resumo['achados']} achado(s)", f"/banco/{aid}")
        return redirect(url_for("banco_auditoria", aid=aid))
    # Conectar (ou abrir a tela) e listar os bancos disponíveis
    try:
        con = ba.conectar(cred["host"], cred["porta"], cred["usuario"], cred["senha"])
        bancos = ba.listar_bancos(con)
        con.close()
    except ba.ErroBanco as e:
        erro = str(e)
    except ImportError:
        erro = "Biblioteca PyMySQL não instalada (pip install pymysql)."
    historico = banco.consulta("SELECT * FROM auditorias ORDER BY id DESC LIMIT 30")
    from sentinela import xampp
    return render_template("banco.html", cred=cred, bancos=bancos, erro=erro, historico=historico, xampp=xampp.status())


@app.route("/banco/<int:aid>")
def banco_auditoria(aid):
    from sentinela import banco_auditor as ba
    reg = banco.consulta("SELECT * FROM auditorias WHERE id=?", (aid,), um=True) or abort(404)
    pasta = os.path.join(banco.pasta_dados(), reg["pasta"])
    with open(os.path.join(pasta, "auditoria.json"), encoding="utf-8") as f:
        aud = json.load(f)
    aplicaveis = [a for a in aud["achados"] if a["aplicavel"]]
    backups_dir = os.path.join(banco.pasta_dados(), "backups")
    backups = sorted([b for b in os.listdir(backups_dir) if b.startswith(reg["banco"] + "_")], reverse=True) \
        if os.path.isdir(backups_dir) else []
    return render_template("auditoria.html", reg=reg, aud=aud, aplicaveis=aplicaveis,
                           aplicacoes=json.loads(reg["aplicacoes"] or "[]"), backups=backups,
                           tem_conexao=aid in _conexoes, mysqldump=bool(ba.achar_mysqldump()))


@app.post("/banco/<int:aid>/aplicar")
def banco_aplicar(aid):
    from sentinela import banco_auditor as ba
    reg = banco.consulta("SELECT * FROM auditorias WHERE id=?", (aid,), um=True) or abort(404)
    ids = request.form.getlist("correcao")
    if request.form.get("confirmacao", "").strip() != reg["banco"]:
        flash(f"Para aplicar, digite exatamente o nome do banco ({reg['banco']}) na confirmação.", "erro")
        return redirect(url_for("banco_auditoria", aid=aid))
    cred = _conexoes.get(aid) or _cred_form(request.form)
    pasta = os.path.join(banco.pasta_dados(), reg["pasta"])
    with open(os.path.join(pasta, "auditoria.json"), encoding="utf-8") as f:
        dados = json.load(f)
    aud = ba.Auditoria(**{k: dados[k] for k in ba.Auditoria.__dataclass_fields__})
    try:
        r = ba.aplicar(aud, ids, os.path.join(banco.pasta_dados(), "backups"), cred["host"], cred["porta"],
                       cred["usuario"], cred["senha"], log=lambda m: None)
    except ba.ErroBanco as e:
        flash(str(e), "erro")
        return redirect(url_for("banco_auditoria", aid=aid))
    historico = json.loads(reg["aplicacoes"] or "[]")
    historico.append({"quando": banco.agora(), "backup": os.path.basename(r["backup"]), "resultados": r["resultados"]})
    banco.executar("UPDATE auditorias SET aplicacoes=? WHERE id=?", (json.dumps(historico, ensure_ascii=False), aid))
    ok = sum(x["ok"] for x in r["resultados"])
    banco.registrar_atividade("banco", f"{ok} correção(ões) aplicada(s) no banco “{reg['banco']}” (backup feito antes)",
                              f"/banco/{aid}")
    flash(f"{ok} de {len(r['resultados'])} correção(ões) aplicada(s). Backup: {os.path.basename(r['backup'])}. "
          f"Rode a auditoria de novo para ver a nota nova.", "ok" if ok == len(r["resultados"]) else "erro")
    return redirect(url_for("banco_auditoria", aid=aid))


@app.post("/banco/<int:aid>/restaurar")
def banco_restaurar(aid):
    from sentinela import banco_auditor as ba
    reg = banco.consulta("SELECT * FROM auditorias WHERE id=?", (aid,), um=True) or abort(404)
    nome = os.path.basename(request.form.get("backup", ""))
    caminho = os.path.join(banco.pasta_dados(), "backups", nome)
    if not nome.startswith(reg["banco"] + "_") or not os.path.isfile(caminho):
        abort(400)
    if request.form.get("confirmacao", "").strip() != reg["banco"]:
        flash(f"Para restaurar, digite o nome do banco ({reg['banco']}).", "erro")
        return redirect(url_for("banco_auditoria", aid=aid))
    cred = _conexoes.get(aid) or _cred_form(request.form)
    try:
        ba.restaurar(caminho, reg["banco"], cred["host"], cred["porta"], cred["usuario"], cred["senha"])
    except ba.ErroBanco as e:
        flash(str(e), "erro")
        return redirect(url_for("banco_auditoria", aid=aid))
    banco.registrar_atividade("banco", f"Backup {nome} restaurado no banco “{reg['banco']}”", f"/banco/{aid}")
    flash(f"Backup {nome} restaurado.", "ok")
    return redirect(url_for("banco_auditoria", aid=aid))


@app.route("/banco/<int:aid>/arquivos/<path:arquivo>")
def banco_arquivo(aid, arquivo):
    reg = banco.consulta("SELECT pasta FROM auditorias WHERE id=?", (aid,), um=True) or abort(404)
    return send_from_directory(os.path.join(banco.pasta_dados(), reg["pasta"]), arquivo)


@app.post("/xampp/<acao>")
def xampp_acao(acao):
    from sentinela import xampp
    from sentinela.banco_auditor import config_padrao
    try:
        if acao == "iniciar":
            xampp.iniciar(log=lambda m: None)
            flash("XAMPP ligado (MySQL e Apache).", "ok")
        elif acao == "instalar":
            xampp.iniciar(log=lambda m: None)
            c = config_padrao()
            url = xampp.instalar_loja(c["usuario"], c["senha"], log=lambda m: None)
            banco.registrar_atividade("banco", "Loja PHP de treino instalada no XAMPP (banco sentinela_loja recriado)", url)
            flash(f"Loja PHP instalada em {url} (banco sentinela_loja recriado do zero).", "ok")
        else:
            abort(404)
    except xampp.ErroXampp as e:
        flash(str(e), "erro")
    return redirect(url_for("banco_dados"))


# ======================================================================= ajuda
@app.route("/ajuda")
def ajuda():
    return render_template("ajuda.html", comandos=sorted(COMANDOS), modelo=MODELO_ROTEIRO)


@app.errorhandler(404)
def nao_encontrado(_):
    return render_template("erro.html", msg="Página não encontrada."), 404


# ======================================================================= iniciar
def iniciar_painel(abrir_navegador: bool = True, porta: int = PORTA):
    from sentinela.motor import carregar_env
    carregar_env()
    if os.path.isfile(_caminho_env()):
        from dotenv import load_dotenv
        load_dotenv(_caminho_env())
    banco.iniciar()
    if banco.consulta("SELECT COUNT(*) n FROM projetos", um=True)["n"]:
        novos = sincronizar_exemplos()
        if novos > 0:
            banco.registrar_atividade("projeto", f"Sentinela atualizado: {novos} roteiro(s) de exemplo novo(s) adicionado(s)",
                                      "/projetos")
            print(f"{novos} exemplo(s) novo(s) adicionado(s) ao painel.")
    # Execuções que estavam rodando quando o programa foi fechado
    banco.executar("UPDATE execucoes SET status='Erro', log=COALESCE(log,'')||'\nInterrompida: o programa foi fechado.' "
                   "WHERE status IN ('Na fila','Executando')")
    # Sobe junto o site de treino local (http://127.0.0.1:8000), usado pelo projeto "Loja Treino"
    try:
        from sentinela.cli import servir_site_treino
        servir_site_treino(8000, bloquear=False)
        print("Site de treino em http://127.0.0.1:8000")
    except (OSError, SystemExit):
        pass  # porta ocupada ou pasta ausente: segue sem ele
    url = f"http://127.0.0.1:{porta}"
    print(f"Sentinela QA {__version__} — painel em {url}  (feche esta janela para encerrar)")
    if abrir_navegador:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=porta, debug=False, threaded=True)
