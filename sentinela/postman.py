"""
Integração com o Postman (coleções v2.1) e o Newman (Postman na linha de comando).

  importar_colecao(json)   -> texto YAML de um roteiro do Sentinela
       Cada requisição vira um caso; os scripts de teste mais comuns do Postman
       (pm.response.to.have.status, responseTime, pm.expect(json.x).to.eql, headers,
       pm.collectionVariables.set) viram verificações do Sentinela.
  exportar_colecao(roteiro) -> coleção do Postman (dict), com os testes em pm.test(...)
       Abra no Postman ou rode com:  npx newman run colecao.json
"""

import json
import re
import uuid

import yaml

_VAR_POSTMAN = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")
_VAR_SENTINELA = re.compile(r"\{(?:dados|env)\.(\w+)(?:\|([^}]*))?\}")


# ====================================================================== importar
def _var_para_sentinela(texto: str) -> str:
    return _VAR_POSTMAN.sub(lambda m: "{dados." + re.sub(r"\W", "_", m[1]) + "}", str(texto))


def _url_texto(url) -> str:
    if isinstance(url, str):
        return url
    if isinstance(url, dict):
        if url.get("raw"):
            return url["raw"]
        host = ".".join(url.get("host", []))
        caminho = "/".join(url.get("path", []))
        return f"{url.get('protocol', 'https')}://{host}/{caminho}"
    return "/"


def _valor_js(v: str):
    v = v.strip().rstrip(";").strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v)
    except ValueError:
        return v


def _caminho_js(expr: str) -> str:
    """jsonData.data[0].name  /  pm.response.json().data.name  ->  data[0].name"""
    expr = re.sub(r"^(pm\.response\.json\(\)|jsonData|json|res|body|data(?=\.))\.?", "", expr.strip())
    expr = re.sub(r"\[['\"](\w+)['\"]\]", r".\1", expr)
    return expr.strip(".")


def _testes_para_passos(script: list[str]) -> tuple[list, int]:
    passos, nao = [], 0
    for linha in "\n".join(script).splitlines():
        s = linha.strip()
        if not s or s.startswith(("//", "pm.test(", "});", "})", "var ", "let ", "const ", "}")) and not any(
                k in s for k in ("pm.expect", "pm.response.to", ".set(")):
            continue
        m = (re.search(r"pm\.response\.to\.have\.status\((\d{3})\)", s)
             or re.search(r"pm\.expect\(pm\.response\.(?:code|status)\)\.to\.(?:eql|equal|be\.equal|eq)\((\d{3})\)", s))
        if m:
            passos.append({"verificar_status": int(m[1])})
            continue
        m = re.search(r"pm\.expect\(pm\.response\.responseTime\)\.to\.be\.(?:below|lessThan|lt)\((\d+)\)", s)
        if m:
            passos.append({"verificar_tempo": {"maximo_ms": int(m[1])}})
            continue
        m = re.search(r"pm\.response\.to\.have\.header\(['\"]([^'\"]+)['\"]\)", s)
        if m:
            passos.append({"verificar_cabecalho": {"nome": m[1]}})
            continue
        m = re.search(r"pm\.expect\(pm\.response\.headers\.get\(['\"]([^'\"]+)['\"]\)\)\.to\.(?:include|contain)\((.+)\)", s)
        if m:
            passos.append({"verificar_cabecalho": {"nome": m[1], "contem": _valor_js(m[2].rstrip(");"))}})
            continue
        m = re.search(r"pm\.expect\((.+?)\)\.to\.(?:eql|equal|eq|be\.equal)\((.+)\)\s*;?\s*$", s)
        if m and ("json" in m[1].lower() or "data" in m[1] or "body" in m[1]):
            passos.append({"verificar_json": {"campo": _caminho_js(m[1]), "valor": _valor_js(m[2].rsplit(")", 1)[0])}})
            continue
        m = re.search(r"pm\.expect\((.+?)\)\.to\.(?:include|contain)\((.+)\)", s)
        if m and ("json" in m[1].lower() or "data" in m[1]):
            passos.append({"verificar_json": {"campo": _caminho_js(m[1]), "contem": _valor_js(m[2].rsplit(")", 1)[0])}})
            continue
        m = re.search(r"pm\.expect\((.+?)\)\.to\.(?:exist|not\.be\.undefined|be\.ok)", s)
        if m:
            passos.append({"verificar_json": {"campo": _caminho_js(m[1]), "existe": True}})
            continue
        m = re.search(r"pm\.(?:collectionVariables|environment|globals|variables)\.set\(['\"](\w+)['\"],\s*(.+?)\)\s*;?$", s)
        if m:
            passos.append({"guardar": {"campo": _caminho_js(m[2]), "como": m[1]}})
            continue
        if "pm." in s:
            nao += 1
    return passos, nao


def _itens(lista, prefixo=""):
    for item in lista or []:
        if "item" in item:                       # pasta
            yield from _itens(item["item"], f"{prefixo}{item.get('name', '')} / ")
        elif "request" in item:
            yield prefixo + item.get("name", "Requisição"), item


def importar_colecao(colecao: dict) -> tuple[str, dict]:
    """Converte uma coleção do Postman em YAML de roteiro. Devolve (yaml, estatísticas)."""
    info = colecao.get("info", {})
    variaveis = {re.sub(r"\W", "_", v.get("key", "")): v.get("value", "") for v in colecao.get("variable", []) if v.get("key")}
    alvo = next((str(v) for k, v in variaveis.items() if k.lower() in ("baseurl", "base_url", "url", "host")
                 and str(v).startswith("http")), None)
    auth_colecao = colecao.get("auth")
    casos, nao_convertidas = [], 0
    for n, (nome, item) in enumerate(_itens(colecao.get("item")), start=1):
        req = item["request"] if isinstance(item["request"], dict) else {"url": item["request"], "method": "GET"}
        metodo = req.get("method", "GET").upper()
        url = _var_para_sentinela(_url_texto(req.get("url")))
        passo = {"metodo": metodo, "url": url}
        cab = {h["key"]: _var_para_sentinela(h.get("value", "")) for h in req.get("header", []) if not h.get("disabled")}
        auth = req.get("auth") or auth_colecao
        if auth and auth.get("type") == "bearer":
            token = next((x.get("value") for x in auth.get("bearer", []) if x.get("key") == "token"), "")
            cab["Authorization"] = "Bearer " + _var_para_sentinela(token)
        if cab:
            passo["cabecalhos"] = cab
        corpo = (req.get("body") or {})
        if corpo.get("mode") == "raw" and corpo.get("raw"):
            bruto = _var_para_sentinela(corpo["raw"])
            try:
                passo["corpo"] = json.loads(bruto)
            except json.JSONDecodeError:
                passo["corpo_texto"] = bruto
        script = []
        for ev in item.get("event", []):
            if ev.get("listen") == "test":
                script += ev.get("script", {}).get("exec", [])
        verificacoes, nao = _testes_para_passos(script)
        nao_convertidas += nao
        casos.append({"id": f"CT{n:02d}", "descricao": nome, "esperado": "Respostas conforme os testes da coleção",
                      "passos": [{"requisitar": passo}] + verificacoes})
    roteiro = {"sistema": info.get("name", "Coleção do Postman"), "versao": "importado do Postman", "tipo": "api",
               "objetivo": (info.get("description") or "Testes importados de uma coleção do Postman.")[:300],
               "alvo": alvo or "https://exemplo.test", "tempo_limite": 20}
    if variaveis:
        roteiro["dados"] = {k: v for k, v in variaveis.items()}
    roteiro["casos"] = casos
    texto = ("# Roteiro gerado a partir de uma coleção do Postman (Sentinela QA).\n"
             "# Variáveis {{x}} viraram {dados.x}; ajuste a seção 'dados' se precisar (senhas: use {env.NOME}).\n"
             + yaml.safe_dump(roteiro, allow_unicode=True, sort_keys=False, width=120))
    return texto, {"casos": len(casos), "nao_convertidas": nao_convertidas}


# ====================================================================== exportar
def _para_postman(texto) -> str:
    return _VAR_SENTINELA.sub(lambda m: "{{" + m[1] + "}}", str(texto))


def _js(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _expr_json(campo: str) -> str:
    if not campo:
        return "json"
    partes = re.findall(r"[^.\[\]]+|\[\d+\]", campo)
    return "json" + "".join(p if p.startswith("[") else (f".{p}" if re.fullmatch(r"[A-Za-z_]\w*", p) else f"[{_js(p)}]") for p in partes)


def _teste_postman(comando: str, a) -> str | None:
    a = a if isinstance(a, dict) else {"_": a}
    if comando == "verificar_status":
        if "entre" in a:
            return f'pm.test("Status entre {a["entre"][0]} e {a["entre"][1]}", () => pm.expect(pm.response.code).to.be.within({a["entre"][0]}, {a["entre"][1]}));'
        v = a.get("igual", a.get("_"))
        return f'pm.test("Status {v}", () => pm.response.to.have.status({int(v)}));'
    if comando == "verificar_tempo":
        v = a.get("maximo_ms", a.get("_"))
        return f'pm.test("Responde em até {v} ms", () => pm.expect(pm.response.responseTime).to.be.below({int(v) + 1}));'
    if comando == "verificar_cabecalho":
        if "contem" in a:
            return (f'pm.test("Cabeçalho {a["nome"]}", () => pm.expect(pm.response.headers.get({_js(a["nome"])})'
                    f'.toLowerCase()).to.include({_js(str(a["contem"]).lower())}));')
        return f'pm.test("Cabeçalho {a["nome"]}", () => pm.response.to.have.header({_js(a["nome"])}));'
    if comando == "verificar_json":
        e = _expr_json(str(a.get("campo", "")))
        nome = a.get("campo") or "corpo"
        if a.get("existe") is False:
            return f'pm.test("{nome} ausente", () => {{ const json = pm.response.json(); pm.expect({e}).to.be.undefined; }});'
        if "valor" in a:
            return (f'pm.test("{nome} = {a["valor"]}", () => {{ const json = pm.response.json(); '
                    f'pm.expect(String({e}).toLowerCase()).to.eql({_js(_para_postman(str(a["valor"])).lower())}); }});')
        if "contem" in a:
            return (f'pm.test("{nome} contém {a["contem"]}", () => {{ const json = pm.response.json(); '
                    f'pm.expect(JSON.stringify({e})).to.include({_js(str(a["contem"]))}); }});')
        return f'pm.test("{nome} existe", () => {{ const json = pm.response.json(); pm.expect({e}).to.not.be.undefined; }});'
    if comando == "guardar":
        return f'{{ const json = pm.response.json(); pm.collectionVariables.set({_js(a["como"])}, {_expr_json(str(a["campo"]))}); }}'
    return None


def exportar_colecao(roteiro) -> dict:
    """Gera uma coleção do Postman v2.1 a partir de um roteiro (passos de API)."""
    variaveis = {"baseUrl": roteiro.alvo or ""}
    for k, v in (roteiro.dados or {}).items():
        variaveis[k] = "" if "{faker." in str(v) else _VAR_SENTINELA.sub(lambda m: m[2] or "", str(v))
    itens = []
    for caso in roteiro.casos:
        atual = None
        for passo in caso.passos:
            if passo.comando == "requisitar":
                a = passo.args
                if isinstance(a, str):
                    partes = a.split(None, 1)
                    a = {"metodo": partes[0] if len(partes) == 2 else "GET", "url": partes[-1]}
                url = _para_postman(a.get("url", "/"))
                if not url.startswith("http"):
                    url = "{{baseUrl}}/" + url.lstrip("/")
                for m in _VAR_SENTINELA.finditer(str(a)):
                    variaveis.setdefault(m[1], m[2] or "")
                req = {"method": str(a.get("metodo", "GET")).upper(), "url": url,
                       "header": [{"key": k, "value": _para_postman(v)} for k, v in (a.get("cabecalhos") or {}).items()]}
                if a.get("corpo") is not None:
                    req["body"] = {"mode": "raw", "raw": _para_postman(json.dumps(a["corpo"], ensure_ascii=False, indent=2)),
                                   "options": {"raw": {"language": "json"}}}
                    req["header"].append({"key": "Content-Type", "value": "application/json"})
                atual = {"name": f"{caso.id} — {caso.descricao}", "request": req,
                         "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": []}}]}
                itens.append(atual)
            elif atual is not None:
                teste = _teste_postman(passo.comando, passo.args)
                atual["event"][0]["script"]["exec"].append(teste or f"// (sem equivalente no Postman: {passo.comando})")
    return {"info": {"_postman_id": str(uuid.uuid4()), "name": roteiro.sistema,
                     "description": f"Exportado do Sentinela QA. {roteiro.objetivo}",
                     "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": itens,
            "variable": [{"key": k, "value": str(v)} for k, v in variaveis.items()]}
