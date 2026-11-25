"""
Testes de API (REST/JSON) — sem navegador, usando só a biblioteca padrão do Python.

Comandos (também funcionam dentro de roteiros web):
    - requisitar: GET /ws/01001000/json/
    - requisitar: { metodo: POST, url: /posts, corpo: { title: "Teste" }, cabecalhos: { X-Teste: "1" } }
    - verificar_status: 200                      (ou { entre: [200, 299] })
    - verificar_json: { campo: localidade, valor: São Paulo }
    - verificar_json: { campo: "itens[0].nome", existe: true }
    - verificar_json: { campo: titulo, contem: "Teste" }
    - verificar_json: { campo: itens, tipo: lista }
    - verificar_tempo: { maximo_ms: 2000 }
    - verificar_cabecalho: { nome: content-type, contem: json }
    - guardar: { campo: id, como: novo_id }       -> usar depois como {dados.novo_id}

A resposta de cada requisição é salva como evidência (arquivo .json na pasta prints/).
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from sentinela.executor_base import ErroPasso, ExecutorBase
from sentinela.executor_qualidade import ComandosQualidade
from sentinela.seguranca import ComandosSeguranca

_TIPOS = {"lista": list, "texto": str, "numero": (int, float), "objeto": dict, "booleano": bool}


def fazer_requisicao(metodo: str, url: str, cabecalhos: dict | None = None, corpo=None, consulta: dict | None = None,
                     tempo_limite: float = 15, corpo_texto: str | None = None) -> dict:
    """Faz uma requisição HTTP e devolve um dicionário com status, tempo, cabeçalhos e corpo.
    Usada pelos roteiros (comando requisitar) e pela tela "Testar API" do painel."""
    metodo = metodo.upper()
    if consulta:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(consulta)
    heads = {"Accept": "application/json", "User-Agent": "SentinelaQA/1.0 (testes automatizados)"}
    heads.update({str(k): str(v) for k, v in (cabecalhos or {}).items()})
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        heads.setdefault("Content-Type", "application/json; charset=utf-8")
    elif corpo_texto:
        dados = corpo_texto.encode("utf-8")
    req = urllib.request.Request(url, data=dados, method=metodo, headers=heads)
    inicio = time.time()
    try:
        with urllib.request.urlopen(req, timeout=tempo_limite) as r:
            status, resp_heads, bruto = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:      # 4xx/5xx também são respostas válidas para testar
        status, resp_heads, bruto = e.code, dict(e.headers), e.read()
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ErroPasso(f"Não foi possível conectar em {url}: {getattr(e, 'reason', e)}")
    ms = int((time.time() - inicio) * 1000)
    texto = bruto.decode("utf-8", errors="replace")
    try:
        dados_json = json.loads(texto) if texto.strip() else None
    except json.JSONDecodeError:
        dados_json = None
    return {"metodo": metodo, "url": url, "status": status, "tempo_ms": ms, "tamanho": len(bruto),
            "cabecalhos": {k.lower(): v for k, v in resp_heads.items()}, "json": dados_json, "texto": texto,
            "requisicao_cabecalhos": heads}


class ComandosApi:
    """Mistura (mixin) com os comandos de API. Precisa de self.alvo, self.registro,
    self.caso_atual, self.dados e self.roteiro (vêm do ExecutorBase)."""

    resposta: dict | None = None

    # ------------------------------------------------------------ requisição
    def cmd_requisitar(self, args):
        if isinstance(args, str):
            partes = args.split(None, 1)
            metodo, url = (partes[0].upper(), partes[1]) if len(partes) == 2 else ("GET", partes[0])
            args = {}
        else:
            metodo = str(args.get("metodo", "GET")).upper()
            url = str(args.get("url", "/"))
        if not url.startswith(("http://", "https://")):
            base = getattr(self, "alvo_api", None) or self.alvo or ""
            url = base.rstrip("/") + "/" + url.lstrip("/")
        self.resposta = fazer_requisicao(metodo, url, args.get("cabecalhos"), args.get("corpo"),
                                         args.get("consulta"), self.roteiro.tempo_limite,
                                         corpo_texto=args.get("corpo_texto"))
        self._salvar_evidencia()
        r = self.resposta
        return f"{r['metodo']} {r['url']} → HTTP {r['status']} em {r['tempo_ms']} ms"

    def _salvar_evidencia(self):
        """Grava a resposta num arquivo .json (evidência do relatório)."""
        caminho, rel = self.registro.novo_print(self.caso_atual, "resposta")
        caminho, rel = caminho[:-4] + ".json", rel[:-4] + ".json"
        r = self.resposta
        conteudo = {"requisicao": f"{r['metodo']} {r['url']}", "status": r["status"], "tempo_ms": r["tempo_ms"],
                    "cabecalhos": r["cabecalhos"], "corpo": r["json"] if r["json"] is not None else r["texto"][:5000]}
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(conteudo, f, ensure_ascii=False, indent=2)
        self.resposta["evidencia"] = rel

    def _exigir_resposta(self):
        if not self.resposta:
            raise ErroPasso("Nenhuma requisição foi feita antes desta verificação (use 'requisitar').")
        return self.resposta

    @staticmethod
    def _pegar(dados, caminho: str):
        """Lê 'itens[0].nome' de um JSON. Devolve (achou, valor)."""
        atual = dados
        for parte in re.findall(r"[^.\[\]]+|\[\d+\]", caminho):
            if parte.startswith("["):
                i = int(parte[1:-1])
                if not isinstance(atual, list) or i >= len(atual):
                    return False, None
                atual = atual[i]
            else:
                if not isinstance(atual, dict) or parte not in atual:
                    return False, None
                atual = atual[parte]
        return True, atual

    # ------------------------------------------------------------ verificações
    def cmd_verificar_status(self, args):
        r = self._exigir_resposta()
        if isinstance(args, dict) and "entre" in args:
            a, b = args["entre"]
            if not (int(a) <= r["status"] <= int(b)):
                raise ErroPasso(f"Status HTTP {r['status']}, esperado entre {a} e {b}")
            return f"Status {r['status']} dentro de {a}–{b}"
        esperado = int(args["igual"] if isinstance(args, dict) else args)
        if r["status"] != esperado:
            raise ErroPasso(f"Status HTTP {r['status']}, esperado {esperado}")
        return f"Status HTTP {esperado}"

    def cmd_verificar_json(self, args):
        r = self._exigir_resposta()
        if r["json"] is None:
            raise ErroPasso(f"A resposta não é JSON (início: {r['texto'][:80]!r})")
        campo = str(args.get("campo", ""))
        achou, valor = self._pegar(r["json"], campo) if campo else (True, r["json"])
        if args.get("existe") is False:
            if achou:
                raise ErroPasso(f"O campo '{campo}' existe, mas não deveria")
            return f"Campo '{campo}' ausente (correto)"
        if not achou:
            raise ErroPasso(f"O campo '{campo}' não existe na resposta")
        if "valor" in args:
            if str(valor).strip().lower() != str(args["valor"]).strip().lower():
                raise ErroPasso(f"'{campo}' = {valor!r}, esperado {args['valor']!r}")
            return f"'{campo}' = {valor!r}"
        if "contem" in args:
            if str(args["contem"]).lower() not in json.dumps(valor, ensure_ascii=False).lower():
                raise ErroPasso(f"'{campo}' não contém {args['contem']!r} (valor: {str(valor)[:80]})")
            return f"'{campo}' contém {args['contem']!r}"
        if "tipo" in args:
            tipo = _TIPOS.get(str(args["tipo"]).lower())
            if tipo is None or not isinstance(valor, tipo):
                raise ErroPasso(f"'{campo}' é {type(valor).__name__}, esperado {args['tipo']}")
            if "quantidade" in args and len(valor) != int(args["quantidade"]):
                raise ErroPasso(f"'{campo}' tem {len(valor)} itens, esperado {args['quantidade']}")
            return f"'{campo}' é do tipo {args['tipo']}"
        return f"Campo '{campo}' existe"

    def cmd_verificar_tempo(self, args):
        r = self._exigir_resposta()
        maximo = int(args.get("maximo_ms") if isinstance(args, dict) else args)
        if r["tempo_ms"] > maximo:
            raise ErroPasso(f"Resposta levou {r['tempo_ms']} ms (máximo {maximo} ms)")
        return f"Respondeu em {r['tempo_ms']} ms (≤ {maximo})"

    def cmd_verificar_cabecalho(self, args):
        r = self._exigir_resposta()
        nome = str(args["nome"]).lower()
        valor = r["cabecalhos"].get(nome)
        if valor is None:
            raise ErroPasso(f"Cabeçalho '{nome}' ausente")
        if "contem" in args and str(args["contem"]).lower() not in valor.lower():
            raise ErroPasso(f"Cabeçalho '{nome}' = {valor!r}, esperado conter {args['contem']!r}")
        return f"Cabeçalho '{nome}': {valor}"

    def cmd_guardar(self, args):
        r = self._exigir_resposta()
        achou, valor = self._pegar(r["json"], str(args["campo"]))
        if not achou:
            raise ErroPasso(f"Não dá para guardar: campo '{args['campo']}' não existe")
        self.dados[str(args["como"])] = valor
        return f"Guardado {{dados.{args['como']}}} = {valor!r}"


class ExecutorApi(ComandosQualidade, ComandosSeguranca, ComandosApi, ExecutorBase):
    tipo = "api"

    def iniciar(self):
        self.navegador = "HTTP (urllib)"
        self.registro.log("Modo API: requisições HTTP diretas, sem navegador")

    def preparar_caso(self, caso=None):
        self.resposta = None

    def capturar(self, comando: str) -> str | None:
        # A evidência de API é o arquivo .json da última resposta
        return self.resposta.get("evidencia") if self.resposta else None
