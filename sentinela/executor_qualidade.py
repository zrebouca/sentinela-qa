"""
Comandos extras de qualidade, usando bibliotecas gratuitas:

  verificar_acessibilidade  axe-core (Deque, open source) — regras WCAG 2.x na página aberta
  verificar_esquema         jsonschema — valida o contrato do JSON da última resposta de API
  comparar_visual           Pillow — compara o print com uma "linha de base" (regressão visual)
  verificar_desempenho      Navigation Timing / LCP do próprio navegador
  teste_carga               várias requisições simultâneas (mini teste de carga) — use só em sistemas seus
  verificar_seguranca       cabeçalhos HTTP de segurança e flags dos cookies
  verificar_links           procura links quebrados (404/500) na página

Exemplos no roteiro:
  - verificar_acessibilidade: { impacto_minimo: serious, max_violacoes: 0 }
  - verificar_esquema: { arquivo: esquemas/cep.json }
  - comparar_visual: { nome: tela_login, tolerancia: 2 }          # % de pixels diferentes aceitos
  - verificar_desempenho: { carregamento_ms: 3000, lcp_ms: 2500 }
  - teste_carga: { url: /api/produtos.php, requisicoes: 50, concorrencia: 10, p95_ms: 800, erros_max: 0 }
  - verificar_seguranca: { exigir: [x-content-type-options, x-frame-options] }
  - verificar_links: { limite: 40 }
"""

import json
import os
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from sentinela.erros import ErroPasso

IMPACTOS = ["minor", "moderate", "serious", "critical"]
IMPACTO_PT = {"minor": "baixo", "moderate": "moderado", "serious": "sério", "critical": "crítico"}
CABECALHOS_SEGURANCA = {
    "content-security-policy": "Content-Security-Policy (protege contra XSS e injeção de scripts)",
    "x-content-type-options": "X-Content-Type-Options: nosniff (impede o navegador de 'adivinhar' o tipo do arquivo)",
    "x-frame-options": "X-Frame-Options ou CSP frame-ancestors (protege contra clickjacking)",
    "referrer-policy": "Referrer-Policy (evita vazar URLs internas para outros sites)",
    "strict-transport-security": "Strict-Transport-Security (força HTTPS) — só em sites HTTPS",
}


def _arquivo_axe() -> str:
    import axe_playwright_python
    return os.path.join(os.path.dirname(axe_playwright_python.__file__), "axe.min.js")


class ComandosQualidade:
    # ------------------------------------------------------------ acessibilidade (axe-core)
    def cmd_verificar_acessibilidade(self, args):
        page = self._pagina_obrigatoria()
        args = args if isinstance(args, dict) else {}
        minimo = IMPACTOS.index(str(args.get("impacto_minimo", "serious")))
        maximo = int(args.get("max_violacoes", 0))
        tags = args.get("regras", ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        try:
            page.add_script_tag(path=_arquivo_axe())
        except Exception as e:
            raise ErroPasso(f"Não foi possível carregar o axe-core: {e}")
        resultado = page.evaluate("t => axe.run(document, { runOnly: { type: 'tag', values: t } })", tags)
        relevantes = [v for v in resultado["violations"] if IMPACTOS.index(v.get("impact") or "minor") >= minimo]
        for v in resultado["violations"]:
            self.registro.observar("Acessibilidade (axe)",
                                   f"{page.url.split('?')[0]}: [{IMPACTO_PT.get(v.get('impact'), v.get('impact'))}] "
                                   f"{v['help']} — {len(v['nodes'])} elemento(s). Regra: {v['id']}")
        if len(relevantes) > maximo:
            nomes = "; ".join(f"{v['id']} ({len(v['nodes'])})" for v in relevantes[:5])
            raise ErroPasso(f"{len(relevantes)} violação(ões) de acessibilidade de impacto ≥ "
                            f"{IMPACTO_PT[IMPACTOS[minimo]]}: {nomes}")
        return (f"Acessibilidade OK: {len(resultado['passes'])} regras aprovadas, "
                f"{len(resultado['violations'])} aviso(s) abaixo do limite")

    # ------------------------------------------------------------ contrato JSON (jsonschema)
    def cmd_verificar_esquema(self, args):
        import jsonschema
        resp = getattr(self, "resposta", None)
        if not resp or resp.get("json") is None:
            raise ErroPasso("Faça uma requisição de API com resposta JSON antes de validar o esquema.")
        if isinstance(args, dict) and "arquivo" in args:
            caminho = args["arquivo"] if os.path.isabs(args["arquivo"]) else os.path.join(self.roteiro.pasta, args["arquivo"])
            with open(caminho, encoding="utf-8") as f:
                esquema = json.load(f)
        else:
            esquema = args.get("esquema") if isinstance(args, dict) else None
        if not esquema:
            raise ErroPasso("Informe 'arquivo' (JSON Schema) ou 'esquema' no passo.")
        erros = sorted(jsonschema.Draft202012Validator(esquema).iter_errors(resp["json"]), key=lambda e: list(e.path))
        if erros:
            detalhes = "; ".join(f"{'/'.join(str(p) for p in e.path) or '(raiz)'}: {e.message[:90]}" for e in erros[:4])
            raise ErroPasso(f"JSON fora do contrato ({len(erros)} erro(s)): {detalhes}")
        return "JSON dentro do contrato (JSON Schema)"

    # ------------------------------------------------------------ regressão visual (Pillow)
    def cmd_comparar_visual(self, args):
        from PIL import Image, ImageChops
        page = self._pagina_obrigatoria()
        nome = str(args.get("nome") if isinstance(args, dict) else args)
        tolerancia = float(args.get("tolerancia", 1.0)) if isinstance(args, dict) else 1.0
        pasta = os.path.join(self.roteiro.pasta, "linha_base")
        os.makedirs(pasta, exist_ok=True)
        base = os.path.join(pasta, f"{nome}.png")
        alvo = self.localizar(args["elemento"]) if isinstance(args, dict) and args.get("elemento") else None
        atual_caminho, _ = self.registro.novo_print(self.caso_atual, f"visual_{nome}")
        (alvo or page).screenshot(path=atual_caminho, **({} if alvo else {"full_page": False}))
        if not os.path.isfile(base):
            Image.open(atual_caminho).save(base)
            return f"Linha de base '{nome}' criada (as próximas execuções comparam com ela)"
        a, b = Image.open(base).convert("RGB"), Image.open(atual_caminho).convert("RGB")
        if a.size != b.size:
            raise ErroPasso(f"Tamanho da tela mudou: base {a.size}, agora {b.size}")
        diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
        pct = 100 * sum(diff.histogram()[255:]) / (a.size[0] * a.size[1])
        if pct > tolerancia:
            destaque = Image.blend(b, Image.new("RGB", b.size, (230, 30, 60)), 0.0)
            destaque.paste((230, 30, 60), mask=diff)
            caminho_diff, rel = self.registro.novo_print(self.caso_atual, f"visual_{nome}_diferenca")
            destaque.save(caminho_diff)
            raise ErroPasso(f"A tela mudou {pct:.2f}% (tolerância {tolerancia}%). Diferenças em vermelho: {rel}")
        return f"Tela igual à linha de base ({pct:.2f}% de diferença)"

    # ------------------------------------------------------------ desempenho
    def cmd_verificar_desempenho(self, args):
        page = self._pagina_obrigatoria()
        args = args if isinstance(args, dict) else {}
        m = page.evaluate("""() => new Promise(ok => {
            const nav = performance.getEntriesByType('navigation')[0] || {};
            let lcp = 0;
            try { new PerformanceObserver(l => { for (const e of l.getEntries()) lcp = e.startTime; })
                  .observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
            setTimeout(() => ok({ carregamento: nav.loadEventEnd || 0, dom: nav.domContentLoadedEventEnd || 0,
                                  ttfb: nav.responseStart || 0, lcp, recursos: performance.getEntriesByType('resource').length,
                                  bytes: performance.getEntriesByType('resource').reduce((s, r) => s + (r.transferSize || 0), 0) }), 300);
        })""")
        resumo = (f"carregamento {m['carregamento']:.0f} ms · DOM {m['dom']:.0f} ms · TTFB {m['ttfb']:.0f} ms · "
                  f"LCP {m['lcp']:.0f} ms · {m['recursos']} recursos · {m['bytes'] / 1024:.0f} KB")
        self.registro.observar("Desempenho", f"{page.url.split('?')[0]}: {resumo}")
        limites = [("carregamento", "carregamento_ms"), ("lcp", "lcp_ms"), ("ttfb", "ttfb_ms")]
        estouros = [f"{n} {m[n]:.0f} ms > {args[k]} ms" for n, k in limites if k in args and m[n] > float(args[k])]
        if estouros:
            raise ErroPasso("Página lenta: " + "; ".join(estouros))
        return f"Desempenho: {resumo}"

    # ------------------------------------------------------------ teste de carga
    def cmd_teste_carga(self, args):
        if not isinstance(args, dict):
            args = {"url": args}
        url = str(args.get("url", "/"))
        if not url.startswith(("http://", "https://")):
            base = getattr(self, "alvo_api", None) or self.alvo or ""
            url = base.rstrip("/") + "/" + url.lstrip("/")
        n = min(int(args.get("requisicoes", 30)), 500)          # limite de segurança
        conc = min(int(args.get("concorrencia", 5)), 50)

        def uma(_):
            ini = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SentinelaQA/1.0 (teste de carga)"})
                with urllib.request.urlopen(req, timeout=self.roteiro.tempo_limite) as r:
                    r.read()
                    return (time.time() - ini) * 1000, r.status < 400
            except urllib.error.HTTPError as e:
                return (time.time() - ini) * 1000, e.code < 400
            except Exception:
                return (time.time() - ini) * 1000, False

        inicio = time.time()
        with ThreadPoolExecutor(max_workers=conc) as ex:
            res = list(ex.map(uma, range(n)))
        total_s = time.time() - inicio
        tempos = sorted(t for t, _ in res)
        erros = sum(1 for _, ok in res if not ok)
        p95 = tempos[max(0, int(len(tempos) * 0.95) - 1)]
        resumo = (f"{n} req · {conc} simultâneas · {n / total_s:.1f} req/s · média {statistics.mean(tempos):.0f} ms · "
                  f"p95 {p95:.0f} ms · máx {tempos[-1]:.0f} ms · erros {erros}")
        self.registro.observar("Carga", f"{url}: {resumo}")
        if "p95_ms" in args and p95 > float(args["p95_ms"]):
            raise ErroPasso(f"p95 de {p95:.0f} ms acima do limite de {args['p95_ms']} ms ({resumo})")
        if erros > int(args.get("erros_max", 0)):
            raise ErroPasso(f"{erros} requisição(ões) com erro ({resumo})")
        return f"Carga OK: {resumo}"

    # ------------------------------------------------------------ segurança
    def cmd_verificar_seguranca(self, args):
        args = args if isinstance(args, dict) else {}
        page = getattr(self, "page", None)
        if page is not None and not page.is_closed() and page.url.startswith("http"):
            resp = page.request.get(page.url)
            cabecalhos = {k.lower(): v for k, v in resp.headers.items()}
            url = page.url
            cookies = self.context.cookies() if getattr(self, "context", None) else []
        elif getattr(self, "resposta", None):
            cabecalhos, url, cookies = self.resposta["cabecalhos"], self.resposta["url"], []
        else:
            raise ErroPasso("Abra uma página ou faça uma requisição antes de verificar a segurança.")
        faltando = []
        for nome, explicacao in CABECALHOS_SEGURANCA.items():
            if nome == "strict-transport-security" and not url.startswith("https"):
                continue
            presente = nome in cabecalhos or (nome == "x-frame-options" and "frame-ancestors" in cabecalhos.get("content-security-policy", ""))
            if not presente:
                faltando.append(nome)
                self.registro.observar("Segurança", f"{url.split('?')[0]}: falta o cabeçalho {explicacao}")
        if "server" in cabecalhos and any(ch.isdigit() for ch in cabecalhos["server"]):
            self.registro.observar("Segurança", f"{url.split('?')[0]}: o cabeçalho Server expõe a versão ({cabecalhos['server']}) — facilita ataques direcionados")
        if "x-powered-by" in cabecalhos:
            self.registro.observar("Segurança", f"{url.split('?')[0]}: o cabeçalho X-Powered-By expõe a tecnologia ({cabecalhos['x-powered-by']})")
        for c in cookies:
            problemas = [p for p, ok in (("HttpOnly", c.get("httpOnly")), ("Secure", c.get("secure") or not url.startswith("https")),
                                         ("SameSite", c.get("sameSite") not in (None, "None"))) if not ok]
            if problemas:
                self.registro.observar("Segurança", f"Cookie '{c['name']}' sem {', '.join(problemas)}")
        exigidos = [h.lower() for h in args.get("exigir", [])]
        falhas = [h for h in exigidos if h in faltando or h not in cabecalhos]
        if falhas:
            raise ErroPasso(f"Cabeçalho(s) de segurança obrigatório(s) ausente(s): {', '.join(falhas)}")
        return f"Segurança: {len(CABECALHOS_SEGURANCA) - len(faltando)} cabeçalho(s) presentes, {len(faltando)} ausente(s) (ver observações)"

    # ------------------------------------------------------------ links quebrados
    def cmd_verificar_links(self, args):
        page = self._pagina_obrigatoria()
        limite = int(args.get("limite", 40)) if isinstance(args, dict) else 40
        links = page.evaluate("() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.href)"
                              ".filter(h => h.startsWith('http')))]")[:limite]
        quebrados = []
        for link in links:
            try:
                r = page.request.head(link, timeout=8000, fail_on_status_code=False)
                if r.status in (405, 403):      # alguns servidores não aceitam HEAD
                    r = page.request.get(link, timeout=8000, fail_on_status_code=False)
                if r.status >= 400:
                    quebrados.append(f"{link} ({r.status})")
            except Exception:
                quebrados.append(f"{link} (sem resposta)")
        for q in quebrados:
            self.registro.observar("Links", f"Link quebrado: {q}")
        if quebrados:
            raise ErroPasso(f"{len(quebrados)} link(s) quebrado(s) de {len(links)}: {'; '.join(quebrados[:3])}")
        return f"{len(links)} link(s) verificados, nenhum quebrado"

    def _pagina_obrigatoria(self):
        page = getattr(self, "page", None)
        if page is None or page.is_closed():
            raise ErroPasso("Este comando precisa de uma página web aberta (roteiro do tipo web).")
        return page
