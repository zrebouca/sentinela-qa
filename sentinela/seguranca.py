"""
Varredura de segurança de aplicações web (OWASP-style), só contra sistemas seus.

Inspirada nos 14 pontos que um atacante tentaria num app feito às pressas. Cada ponto
vira uma verificação automática que reporta DEFEITO (se vulnerável) ou OBSERVAÇÃO (se ok):

   1  Painel admin acessível pela URL sem login .......... _rotas_admin
   2  Trocar o id na URL e ver dado de outro (IDOR) ...... _idor            (config)
   3  Chave de API / segredo exposto no front-end ........ _segredos_front
   4  Preço vindo do cliente é aceito no servidor ........ _preco           (config)
   5  Pedido/pagamento falso direto na API ............... recipe (requisitar + verificar_status)
   6  (idem — lógica de negócio) ......................... recipe
   7  Reusar o mesmo cupom .............................. recipe
   8  Login devolve o papel do usuário (vira admin) ...... _papel_login     (config)
   9  Código/login sem limite de tentativas (brute force)  _forca_bruta     (config)
  10  IA obedece "ignore as instruções" (prompt injection) recipe (requisitar + verificar_sem_texto)
  11  Script no campo (XSS refletido) .................... _injecao
  12  Enviar arquivo que não é foto (upload .php) ........ _upload          (config)
  13  .env / .git exposto no servidor .................... _arquivos_expostos
  14  SQL injection na busca ............................ _injecao

Uso no roteiro (tipo web ou api):

  - varredura_seguranca:
      base: http://localhost/sentinela-loja     # padrão: alvo do roteiro / página aberta
      rotas_extras: [/relatorio.php]             # opcional
      injecao:                                   # onde testar SQLi e XSS
        - { url: /produtos.php, parametro: busca }
      login:                                     # pontos 8 e 9
        url: /login.php
        campos: { usuario: "qa@teste.com", senha: "123456" }
        campo_senha: senha
      preco: { url: /api/produtos.php, metodo: POST, campo: preco, valor: 0.01 }   # ponto 4
      upload: { url: /perfil.php, campo: foto }                                     # ponto 12
      falhar_se_vulneravel: false                # true = reprova o caso se achar algo Alto/Crítico

Também há `verificar_injecao` para testar SQLi+XSS num único parâmetro.

Regra de ouro: só rode contra sistemas de treino ou seus, com autorização. É um teste
intencionalmente "malcriado" com as entradas; aponte-o só para onde você pode.
"""

import re
import urllib.parse

from sentinela.erros import ErroPasso

# Caminhos sensíveis que não deveriam abrir sem login / não deveriam existir em produção
ROTAS_ADMIN = ["admin", "admin/", "administrador", "painel", "dashboard", "phpmyadmin", "adminer.php", "wp-admin/"]
ARQUIVOS_EXPOSTOS = [".env", ".env.bak", ".git/config", ".git/HEAD", "config.php.bak", "config.bak",
                     "backup.sql", "dump.sql", "banco.sql", "composer.json", ".htpasswd", "config.inc.php.bak"]
# Padrões de segredo que não podem aparecer no HTML/JS que vai para o navegador
SEGREDOS = [
    (r"sk_live_[0-9A-Za-z]{10,}", "chave secreta do Stripe (sk_live_)"),
    (r"AKIA[0-9A-Z]{16}", "chave de acesso da AWS (AKIA…)"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "chave de API do Google (AIza…)"),
    (r"ghp_[0-9A-Za-z]{30,}", "token do GitHub (ghp_…)"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "chave privada embutida"),
    (r"(?i)(?:api[_-]?key|secret|token|password|senha)\s*[:=]\s*[\"'][^\"']{8,}[\"']", "segredo escrito direto no código"),
]
# Sinais de erro de banco na resposta = provável SQL injection
ERROS_SQL = ["sql syntax", "mysql_fetch", "mysqli", "you have an error in your sql",
             "warning: mysql", "unclosed quotation", "sqlstate", "ora-0", "pg_query",
             "sqlite3.operationalerror", "near \"", "syntax error at or near"]
PAYLOADS_SQLI = ["'", "' OR '1'='1", "'; --", "\" OR \"\"=\""]
# Campos que, se vierem na resposta do login, deixam o cliente "escolher" ser admin
CAMPOS_PAPEL = ["perfil", "role", "papel", "is_admin", "isadmin", "admin", "tipo_usuario", "nivel", "permissao"]


class ComandosSeguranca:
    """Mixin com a varredura de segurança. Usa fazer_requisicao (urllib), então funciona
    tanto em roteiro web quanto api, e dentro do .exe."""

    # ---------------------------------------------------------------- utilidades
    def _base_seg(self, args: dict) -> str:
        base = args.get("base")
        if not base:
            page = getattr(self, "page", None)
            if page is not None and not page.is_closed() and page.url.startswith("http"):
                p = urllib.parse.urlsplit(page.url)
                base = f"{p.scheme}://{p.netloc}{p.path.rsplit('/', 1)[0]}"
            else:
                base = getattr(self, "alvo_api", None) or getattr(self, "alvo", None)
        if not base:
            raise ErroPasso("varredura_seguranca precisa de 'base' (ou um alvo/página aberta).")
        return base.rstrip("/")

    def _url(self, base: str, caminho: str) -> str:
        if caminho.startswith(("http://", "https://")):
            return caminho
        return base + "/" + caminho.lstrip("/")

    def _http(self, url: str, metodo="GET", **kw):
        from sentinela.executor_api import fazer_requisicao
        try:
            return fazer_requisicao(metodo, url, tempo_limite=10, **kw)
        except ErroPasso:
            return None

    def _vuln(self, ponto, descricao, severidade, esperado, obtido, passos):
        self._seg_achados += 1
        if severidade in ("Alta", "Crítica"):
            self._seg_graves += 1
        self.registro.novo_defeito(
            descricao=f"[Segurança #{ponto}] {descricao}", severidade=severidade,
            passos_reproducao=passos, esperado=esperado, obtido=obtido, evidencia=None,
            origem="Segurança", caso_id=getattr(self, "caso_atual", "SEG"))

    def _ok(self, texto):
        self.registro.observar("Segurança", texto)

    # ---------------------------------------------------------------- comando principal
    def cmd_varredura_seguranca(self, args):
        args = args if isinstance(args, dict) else {}
        base = self._base_seg(args)
        self._seg_achados = 0
        self._seg_graves = 0
        self.registro.log(f"\n▶ Varredura de segurança em {base}")

        self._rotas_admin(base, args.get("rotas_extras") or [])
        self._arquivos_expostos(base)
        self._segredos_front(base)
        for alvo in args.get("injecao") or []:
            self._injecao(base, alvo)
        if args.get("login"):
            self._papel_login(base, args["login"])
            self._forca_bruta(base, args["login"])
        if args.get("idor"):
            self._idor(base, args["idor"])
        if args.get("preco"):
            self._preco(base, args["preco"])
        if args.get("upload"):
            self._upload(base, args["upload"])

        resumo = (f"Varredura de segurança: {self._seg_achados} achado(s)"
                  f"{f', {self._seg_graves} grave(s)' if self._seg_graves else ''}.")
        if args.get("falhar_se_vulneravel") and self._seg_graves:
            raise ErroPasso(resumo + " Veja os defeitos de origem 'Segurança'.")
        return resumo + (" Veja defeitos/observações." if self._seg_achados else " Nada crítico encontrado.")

    def cmd_verificar_injecao(self, args):
        """SQLi + XSS num único parâmetro: { url, parametro, metodo? }."""
        args = args if isinstance(args, dict) else {}
        self._seg_achados = getattr(self, "_seg_achados", 0)
        self._seg_graves = getattr(self, "_seg_graves", 0)
        base = getattr(self, "alvo_api", None) or getattr(self, "alvo", None) or ""
        self._injecao(base.rstrip("/"), args)
        return f"Injeção testada em {args.get('parametro')} de {args.get('url')}: {self._seg_achados} achado(s)."

    # ---------------------------------------------------------------- 1. painel admin sem login
    def _rotas_admin(self, base, extras):
        for caminho in ROTAS_ADMIN + list(extras):
            r = self._http(self._url(base, caminho))
            if not r:
                continue
            texto = r["texto"].lower()
            pede_login = r["status"] in (301, 302, 401, 403) or any(
                p in texto for p in ("senha", "password", "entrar", "login", "não autorizado", "unauthorized"))
            if r["status"] == 200 and not pede_login and len(r["texto"]) > 150:
                self._vuln(1, f"Área restrita '/{caminho}' abriu sem login (HTTP 200).", "Alta",
                           "Área administrativa exige autenticação (redireciona para o login ou 401/403).",
                           f"GET /{caminho} devolveu 200 com conteúdo, sem pedir login.",
                           [f"Abra {self._url(base, caminho)} sem estar logado"])
            else:
                self._ok(f"/{caminho}: protegido ou inexistente (HTTP {r['status']}).")

    # ---------------------------------------------------------------- 13. .env / .git expostos
    def _arquivos_expostos(self, base):
        for caminho in ARQUIVOS_EXPOSTOS:
            r = self._http(self._url(base, caminho))
            if r and r["status"] == 200 and r["texto"].strip():
                corpo = r["texto"]
                sensivel = any(s in corpo for s in ("DB_", "APP_KEY", "PASSWORD", "SECRET", "[core]",
                                                    "PRIVATE KEY", "ref:", "=")) and len(corpo) < 100000
                if sensivel:
                    self._vuln(13, f"Arquivo sensível '/{caminho}' acessível pelo navegador.", "Crítica",
                               "Arquivos de configuração e repositório não ficam acessíveis pela web.",
                               f"GET /{caminho} devolveu 200 com conteúdo ({r['tamanho']} bytes).",
                               [f"Abra {self._url(base, caminho)}"])

    # ---------------------------------------------------------------- 3. segredo no front-end
    def _segredos_front(self, base):
        paginas = [base + "/"]
        r = self._http(base + "/")
        if r:
            # junta os <script src> do mesmo domínio
            for m in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', r["texto"], re.I)[:10]:
                url = m if m.startswith("http") else self._url(base, m)
                if urllib.parse.urlsplit(url).netloc == urllib.parse.urlsplit(base).netloc:
                    paginas.append(url)
        vistos = set()
        for url in paginas:
            rr = r if url == base + "/" else self._http(url)
            if not rr:
                continue
            for padrao, nome in SEGREDOS:
                for achado in re.findall(padrao, rr["texto"]):
                    trecho = (achado if isinstance(achado, str) else achado[0])[:24]
                    if (nome, trecho) in vistos:
                        continue
                    vistos.add((nome, trecho))
                    self._vuln(3, f"{nome} exposto no front-end ({url.split('/')[-1] or 'página'}).", "Alta",
                               "Segredos ficam só no servidor, nunca no HTML/JS que vai ao navegador.",
                               f"Encontrado no conteúdo enviado ao navegador: {trecho}…",
                               [f"Abra {url} e veja o código-fonte"])
        if not vistos:
            self._ok("Nenhum segredo (chave de API, token, senha) encontrado no front-end.")

    # ---------------------------------------------------------------- 11 + 14. XSS e SQLi
    def _injecao(self, base, alvo):
        if not isinstance(alvo, dict) or not alvo.get("url") or not alvo.get("parametro"):
            raise ErroPasso("injeção precisa de { url, parametro }.")
        metodo = str(alvo.get("metodo", "GET")).upper()
        url = self._url(base, alvo["url"])
        campo = alvo["parametro"]

        def enviar(valor):
            if metodo == "GET":
                return self._http(url, consulta={campo: valor})
            return self._http(url, metodo=metodo, corpo={campo: valor})

        # 14. SQL injection: erro de banco na resposta?
        for p in PAYLOADS_SQLI:
            r = enviar(p)
            if r and any(s in r["texto"].lower() for s in ERROS_SQL):
                self._vuln(14, f"Possível SQL injection em '{campo}' ({alvo['url']}).", "Crítica",
                           "Entradas são tratadas com consultas parametrizadas; nenhum erro de SQL vaza.",
                           f"O valor {p!r} fez a resposta expor um erro de banco de dados.",
                           [f"{metodo} {url} com {campo}={p}"])
                break
        else:
            self._ok(f"'{campo}' ({alvo['url']}): sem sinais de SQL injection.")

        # 11. XSS refletido: o payload volta sem escapar?
        marca = "Sx" + "9z7q"
        payload = f'"><svg/onload=alert(1)>{marca}'
        r = enviar(payload)
        if r and payload in r["texto"] and "text/html" in r["cabecalhos"].get("content-type", ""):
            self._vuln(11, f"XSS refletido em '{campo}' ({alvo['url']}).", "Alta",
                       "O que o usuário digita é escapado antes de voltar para a página (&lt;, &gt;).",
                       "O <svg onload> voltou intacto no HTML — o navegador executaria o script.",
                       [f"{metodo} {url} com {campo}={payload}"])
        else:
            self._ok(f"'{campo}' ({alvo['url']}): entrada escapada (sem XSS refletido).")

    # ---------------------------------------------------------------- 8. login devolve o papel
    def _papel_login(self, base, cfg):
        url = self._url(base, cfg.get("url", "/login"))
        r = self._http(url, metodo=str(cfg.get("metodo", "POST")).upper(), corpo=cfg.get("campos") or {})
        if not r:
            return
        texto = r["texto"]
        achados = [c for c in CAMPOS_PAPEL if re.search(rf'["\']{c}["\']\s*:', texto, re.I)]
        if achados:
            self._vuln(8, f"A resposta do login expõe o papel do usuário ({', '.join(achados)}).", "Média",
                       "O papel/permissão fica no servidor (ou dentro de um token assinado), não solto na resposta.",
                       f"A resposta do login traz o campo {achados[0]!r}; se o app confiar nisso no cliente, dá para virar admin.",
                       [f"POST {url} e veja a resposta JSON"])
        else:
            self._ok("A resposta do login não expõe papel/permissão diretamente.")

    # ---------------------------------------------------------------- 9. força bruta (sem limite)
    def _forca_bruta(self, base, cfg):
        url = self._url(base, cfg.get("url", "/login"))
        campos = dict(cfg.get("campos") or {})
        campo_senha = cfg.get("campo_senha", "senha")
        bloqueou = False
        for i in range(8):
            campos[campo_senha] = f"errada{i}!"
            r = self._http(url, metodo=str(cfg.get("metodo", "POST")).upper(), corpo=campos)
            if not r:
                return
            if r["status"] == 429 or any(s in r["texto"].lower() for s in
                                         ("muitas tentativas", "tente novamente", "bloqueado", "too many", "aguarde")):
                bloqueou = True
                break
        if bloqueou:
            self._ok(f"Login limita tentativas (bloqueou após {i + 1} erros).")
        else:
            self._vuln(9, "Login sem limite de tentativas (vulnerável a força bruta).", "Média",
                       "Após algumas senhas erradas o sistema bloqueia ou atrasa (rate limit / captcha).",
                       "8 senhas erradas seguidas e nenhuma foi barrada.",
                       [f"POST {url} com senha errada várias vezes"])

    # ---------------------------------------------------------------- 2. IDOR
    def _idor(self, base, cfg):
        url_modelo = cfg.get("url")
        ids = cfg.get("ids") or []
        if not url_modelo or "{id}" not in url_modelo or len(ids) < 2:
            raise ErroPasso("idor precisa de { url: '/conta?id={id}', ids: [meu, outro] }.")
        r_meu = self._http(self._url(base, url_modelo.replace("{id}", str(ids[0]))))
        r_outro = self._http(self._url(base, url_modelo.replace("{id}", str(ids[1]))))
        if r_meu and r_outro and r_outro["status"] == 200 and len(r_outro["texto"]) > 100 \
                and r_outro["texto"] != r_meu["texto"]:
            self._vuln(2, "Possível IDOR: trocando o id na URL vejo o dado de outra pessoa.", "Alta",
                       "O servidor confere se o registro pertence a quem está logado (403 para o id de outro).",
                       f"Troquei o id {ids[0]} por {ids[1]} e recebi outro conteúdo (HTTP 200).",
                       [f"Abra {self._url(base, url_modelo.replace('{id}', str(ids[1])))} logado como o id {ids[0]}"])
        else:
            self._ok("Troca de id na URL não devolveu dado de outro usuário.")

    # ---------------------------------------------------------------- 4. preço vindo do cliente
    def _preco(self, base, cfg):
        url = self._url(base, cfg.get("url", "/"))
        campo = cfg.get("campo", "preco")
        valor = cfg.get("valor", 0.01)
        corpo = dict(cfg.get("campos") or {})
        corpo[campo] = valor
        r = self._http(url, metodo=str(cfg.get("metodo", "POST")).upper(), corpo=corpo)
        if not r:
            return
        aceitou = r["status"] in (200, 201) and str(valor) in r["texto"]
        if aceitou:
            self._vuln(4, f"O servidor aceitou o '{campo}' enviado pelo cliente ({valor}).", "Alta",
                       "Preço/valor vem do banco no servidor, nunca do que o cliente manda.",
                       f"Enviei {campo}={valor} e o servidor aceitou e devolveu esse valor.",
                       [f"{cfg.get('metodo', 'POST')} {url} com {campo}={valor}"])
        else:
            self._ok(f"O servidor não aceitou o '{campo}' manipulado pelo cliente.")

    # ---------------------------------------------------------------- 12. upload disfarçado
    def _upload(self, base, cfg):
        url = self._url(base, cfg.get("url", "/"))
        campo = cfg.get("campo", "arquivo")
        limite = "----SentinelaBoundary7MA4YWxk"
        conteudo = "<?php echo 'teste-sentinela'; ?>"
        corpo = (
            f"--{limite}\r\n"
            f'Content-Disposition: form-data; name="{campo}"; filename="teste.php"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
            f"{conteudo}\r\n--{limite}--\r\n")
        r = self._http(url, metodo="POST", corpo_texto=corpo,
                        cabecalhos={"Content-Type": f"multipart/form-data; boundary={limite}"})
        if not r:
            return
        recusou = r["status"] in (400, 415, 422) or any(
            s in r["texto"].lower() for s in ("inválid", "não permitid", "apenas imagens", "tipo de arquivo", "not allowed"))
        if r["status"] in (200, 201) and not recusou:
            self._vuln(12, "Upload aceitou um arquivo .php disfarçado de imagem.", "Crítica",
                       "O servidor valida o conteúdo real do arquivo e recusa executáveis (.php).",
                       "Enviei 'teste.php' com Content-Type de imagem e o servidor aceitou.",
                       [f"POST {url} com um arquivo .php no campo '{campo}'"])
        else:
            self._ok("Upload recusou o arquivo .php disfarçado.")
