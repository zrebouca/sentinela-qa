"""
Auditoria de UI/UX de páginas web (mede o design REAL da página e sugere a correção).

Diferente das "Melhorias da IA" (que são opiniões geradas por um modelo), esta auditoria
é DETERMINÍSTICA: ela lê o CSS já aplicado na página (cores, fontes, tamanhos, caixas dos
botões) e aponta problemas medíveis, cada um com um trecho de código pronto para colar.

O que ela verifica (tudo configurável):
   • Contraste de texto x fundo (WCAG 2.1 AA) ...... abaixo de 4.5:1 (ou 3:1 em texto grande)
   • Tamanho de fonte do corpo .................... texto miúdo (< 12px) cansa / não lê no celular
   • Consistência de fontes ....................... muitas famílias diferentes = visual bagunçado
   • Consistência de cores ........................ paleta grande demais = falta de sistema
   • Alvos de toque ............................... botões/links menores que 44x44 (dedo não acerta)
   • Responsivo ................................... falta <meta viewport> / rolagem horizontal

Uso no roteiro (tipo web). Normalmente sem argumentos:

  - auditoria_ux

Ou ajustando os limites:

  - auditoria_ux:
      min_contraste: 4.5        # mínimo WCAG AA (padrão)
      min_alvo_px: 44           # tamanho mínimo de botão/link (padrão)
      min_fonte_px: 12          # corpo de texto confortável (padrão)
      max_fontes: 3             # nº de famílias de fonte toleradas (padrão)
      max_cores: 12             # nº de cores distintas toleradas (padrão)
      max_itens: 6              # quantos exemplos reportar por categoria (padrão)
      falhar_se_grave: false    # true = reprova o caso se achar algo de prioridade Alta

As melhorias entram no relatório na seção "Auditoria de UI/UX", cada uma com o código.
Como é só leitura (não digita nem envia nada), é seguro em qualquer página que você possa abrir.
"""

from sentinela.erros import ErroPasso

# Famílias que são apenas "fallback" do sistema — não contam como fonte de marca
FONTES_GENERICAS = {
    "system-ui", "-apple-system", "blinkmacsystemfont", "sans-serif", "serif",
    "monospace", "cursive", "fantasy", "ui-sans-serif", "ui-serif", "ui-monospace",
    "ui-rounded", "inherit", "initial", "unset", "math", "emoji",
}


# ---------------------------------------------------------------- contraste (puro, testável)
def _canal_linear(c: float) -> float:
    cs = c / 255.0
    return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4


def _luminancia(rgb) -> float:
    """Luminância relativa WCAG de uma cor [r, g, b] (0..255)."""
    return 0.2126 * _canal_linear(rgb[0]) + 0.7152 * _canal_linear(rgb[1]) + 0.0722 * _canal_linear(rgb[2])


def _contraste(a, b) -> float:
    """Razão de contraste WCAG entre duas cores opacas (1.0 a 21.0)."""
    la, lb = _luminancia(a), _luminancia(b)
    claro, escuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (escuro + 0.05)


def _compor(fg, bg):
    """Mistura uma cor de frente (possivelmente com alfa) sobre o fundo opaco."""
    if len(fg) < 4 or fg[3] >= 1:
        return [round(x) for x in fg[:3]]
    a = fg[3]
    return [round(fg[i] * a + bg[i] * (1 - a)) for i in range(3)]


def _texto_grande(size_px: float, bold: bool) -> bool:
    """WCAG: texto 'grande' = >= 24px, ou >= 18.66px se for negrito."""
    return size_px >= 24 or (bold and size_px >= 18.66)


def _min_contraste(size_px: float, bold: bool) -> float:
    return 3.0 if _texto_grande(size_px, bold) else 4.5


def avaliar_contraste(fg_rgba, bg_rgb, size_px: float, bold: bool):
    """Devolve (passa, razao, minimo) para um texto sobre um fundo."""
    fg = _compor(fg_rgba, bg_rgb)
    razao = _contraste(fg, bg_rgb)
    minimo = _min_contraste(size_px, bold)
    return (razao >= minimo, round(razao, 2), minimo)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb[:3])


def cor_sugerida(bg_rgb) -> str:
    """Escolhe um texto quase-preto ou quase-branco que passe com folga sobre o fundo."""
    escuro, claro = (26, 26, 26), (245, 245, 245)
    return _hex(escuro if _luminancia(bg_rgb) > 0.4 else claro)


# ---------------------------------------------------------------- extração (roda no navegador)
JS_UX = r"""
() => {
  const MAXEL = 2500;
  const parse = s => {
    const m = s && s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    if (p.length < 3 || p.some(isNaN)) return null;
    return [p[0], p[1], p[2], p.length >= 4 ? p[3] : 1];
  };
  const temBgImagem = el => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const bi = getComputedStyle(n).backgroundImage;
      if (bi && bi !== 'none') return true;
    }
    return false;
  };
  const bgSolido = el => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c[3] >= 0.5) return [c[0], c[1], c[2]];
    }
    return [255, 255, 255];
  };
  const temTexto = el => {
    for (const no of el.childNodes)
      if (no.nodeType === 3 && no.textContent.trim().length > 1) return true;
    return false;
  };
  const visivel = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const st = getComputedStyle(el);
    return !(st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) < 0.1);
  };
  const sel = el => {
    let s = el.tagName.toLowerCase();
    if (el.id) return s + '#' + el.id;
    const cls = (typeof el.className === 'string') ? el.className.trim().split(/\s+/)[0] : '';
    return cls ? s + '.' + cls : s;
  };

  const amostras = [], vistas = new Set(), fontes = new Set(), tamanhos = {}, cores = new Set();
  for (const el of [...document.querySelectorAll('body *')].slice(0, MAXEL)) {
    if (!visivel(el)) continue;
    const st = getComputedStyle(el);
    const fam = (st.fontFamily || '').split(',')[0].replace(/["']/g, '').trim().toLowerCase();
    if (fam) fontes.add(fam);
    const cfg = parse(st.color); if (cfg) cores.add(cfg.slice(0, 3).map(Math.round).join(','));
    const cbg = parse(st.backgroundColor); if (cbg && cbg[3] >= 0.5) cores.add(cbg.slice(0, 3).map(Math.round).join(','));
    if (!temTexto(el)) continue;
    const size = parseFloat(st.fontSize) || 16;
    const bold = (parseInt(st.fontWeight) || 400) >= 700;
    const k = Math.round(size);
    tamanhos[k] = (tamanhos[k] || 0) + 1;
    const fg = parse(st.color);
    if (!fg || temBgImagem(el)) continue;
    const bg = bgSolido(el);
    const chave = fg.map(Math.round).join(',') + '|' + bg.join(',') + '|' + k + '|' + bold;
    if (vistas.has(chave)) continue;
    vistas.add(chave);
    const txt = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    amostras.push({ sel: sel(el), fg, bg, size, bold, texto: txt });
  }

  const INTER = 'a[href],button,input[type=button],input[type=submit],input[type=reset],[role=button],select,summary';
  const alvos = [], vistosA = new Set();
  for (const el of [...document.querySelectorAll(INTER)].slice(0, 1500)) {
    if (!visivel(el)) continue;
    const r = el.getBoundingClientRect();
    const w = Math.round(r.width), h = Math.round(r.height), s = sel(el);
    if (vistosA.has(s) || (w >= 44 && h >= 44)) continue;
    vistosA.add(s);
    const txt = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    alvos.push({ sel: s, w, h, texto: txt });
  }

  return {
    amostras: amostras.slice(0, 120),
    fontes: [...fontes].slice(0, 25),
    tamanhos,
    cores: [...cores].slice(0, 60),
    alvos: alvos.slice(0, 40),
    viewport_meta: !!document.querySelector('meta[name=viewport]'),
    overflow: (document.documentElement.scrollWidth - window.innerWidth) > 4,
    largura_pagina: document.documentElement.scrollWidth,
    largura_janela: window.innerWidth,
  };
}
"""


class ComandosUx:
    """Mixin com a auditoria de UI/UX. Só faz sentido em teste WEB (precisa da página
    renderizada para ler o CSS aplicado). Reporta MELHORIAS, cada uma com o código pronto."""

    def _melhoria(self, categoria, prioridade, titulo, descricao, evidencia, codigo, linguagem="css"):
        self._ux_achados += 1
        if prioridade == "Alta":
            self._ux_graves += 1
        self.registro.nova_melhoria_ux(
            categoria=categoria, prioridade=prioridade, titulo=titulo,
            descricao=descricao, evidencia=evidencia, codigo=codigo.strip(), linguagem=linguagem)

    def cmd_auditoria_ux(self, args):
        page = getattr(self, "page", None)
        if page is None or page.is_closed():
            raise ErroPasso("auditoria_ux só funciona em teste web (abra uma página antes com 'abrir').")
        args = args if isinstance(args, dict) else {}
        min_contraste = float(args.get("min_contraste", 4.5))
        min_alvo = int(args.get("min_alvo_px", 44))
        min_fonte = float(args.get("min_fonte_px", 12))
        max_fontes = int(args.get("max_fontes", 3))
        max_cores = int(args.get("max_cores", 12))
        max_itens = int(args.get("max_itens", 6))

        self._ux_achados = 0
        self._ux_graves = 0
        self.registro.log(f"\n▶ Auditoria de UI/UX em {page.url}")
        dados = page.evaluate(JS_UX)

        self._checar_contraste(dados.get("amostras", []), min_contraste, max_itens)
        self._checar_fontes_tamanho(dados.get("tamanhos", {}), min_fonte)
        self._checar_familias(dados.get("fontes", []), max_fontes)
        self._checar_cores(dados.get("cores", []), max_cores)
        self._checar_alvos(dados.get("alvos", []), min_alvo, max_itens)
        self._checar_responsivo(dados)

        resumo = (f"Auditoria de UI/UX: {self._ux_achados} melhoria(s)"
                  f"{f', {self._ux_graves} de prioridade alta' if self._ux_graves else ''}.")
        if args.get("falhar_se_grave") and self._ux_graves:
            raise ErroPasso(resumo + " Veja a seção 'Auditoria de UI/UX'.")
        return resumo + (" Veja a seção 'Auditoria de UI/UX'." if self._ux_achados
                         else " Nada relevante a melhorar — mandou bem!")

    # ---------------------------------------------------------------- contraste
    def _checar_contraste(self, amostras, minimo, max_itens):
        falhas = []
        for a in amostras:
            passa, razao, exigido = avaliar_contraste(a["fg"], a["bg"], a["size"], a["bold"])
            if not passa and razao < minimo:
                falhas.append((razao, exigido, a))
        falhas.sort(key=lambda t: t[0])
        for razao, exigido, a in falhas[:max_itens]:
            fg_hex, bg_hex = _hex(_compor(a["fg"], a["bg"])), _hex(a["bg"])
            sugerida = cor_sugerida(a["bg"])
            trecho = f'"{a["texto"]}" ' if a["texto"] else ""
            codigo = (f"/* Contraste atual {razao}:1 (texto {fg_hex} sobre {bg_hex}).\n"
                      f"   WCAG AA exige no mínimo {exigido:g}:1. Escureça o texto\n"
                      f"   (ou clareie o fundo) até alcançar o mínimo. Ex.: */\n"
                      f"{a['sel']} {{\n  color: {sugerida};   /* passa com folga sobre {bg_hex} */\n}}")
            self._melhoria(
                "Contraste", "Alta",
                f"Texto com contraste {razao}:1 (abaixo de {exigido:g}:1)",
                f"O texto {trecho}em {fg_hex} sobre {bg_hex} tem contraste {razao}:1, "
                f"abaixo do mínimo WCAG AA de {exigido:g}:1. Pessoas com baixa visão (e qualquer um "
                f"no sol) não leem bem. Corrija a cor até passar de {exigido:g}:1.",
                a["sel"], codigo)
        if len(falhas) > max_itens:
            self.registro.observar("UI/UX", f"Contraste: +{len(falhas) - max_itens} outro(s) trecho(s) de texto "
                                            f"também abaixo do mínimo (veja os exemplos na seção de melhorias).")

    # ---------------------------------------------------------------- tamanho de fonte
    def _checar_fontes_tamanho(self, tamanhos, minimo):
        tamanhos = {int(k): int(v) for k, v in tamanhos.items()}
        pequenos = {k: v for k, v in tamanhos.items() if k < minimo}
        if not pequenos:
            return
        menor = min(pequenos)
        qtd = sum(pequenos.values())
        prioridade = "Alta" if menor < 10 else "Média"
        codigo = ("body {\n  font-size: 16px;   /* corpo confortável, inclusive no celular */\n"
                  "  line-height: 1.5;\n}\nsmall, .legenda { font-size: 0.875rem; }  /* ~14px, o mínimo p/ apoio */")
        self._melhoria(
            "Tipografia", prioridade,
            f"Texto muito pequeno ({menor}px)",
            f"Há {qtd} trecho(s) de texto com fonte abaixo de {minimo:g}px (o menor tem {menor}px). "
            f"Texto miúdo cansa a leitura e some no celular. Use ~16px no corpo e no mínimo 14px em apoios.",
            f"menor fonte: {menor}px", codigo)

    # ---------------------------------------------------------------- famílias de fonte
    def _checar_familias(self, fontes, maximo):
        marca = [f for f in fontes if f and f not in FONTES_GENERICAS]
        if len(marca) <= maximo:
            return
        lista = ", ".join(marca[:8]) + ("…" if len(marca) > 8 else "")
        codigo = (":root {\n  --fonte-base: \"Inter\", system-ui, -apple-system, sans-serif;\n"
                  "  --fonte-titulo: var(--fonte-base);   /* use 1, no máx. 2 famílias */\n}\n"
                  "body, input, button, select, textarea { font-family: var(--fonte-base); }\n"
                  "h1, h2, h3, h4 { font-family: var(--fonte-titulo); }")
        self._melhoria(
            "Tipografia", "Baixa",
            f"{len(marca)} famílias de fonte diferentes",
            f"A página mistura {len(marca)} famílias de fonte ({lista}). Mais de {maximo} deixa o visual "
            f"inconsistente e pesa o carregamento. Padronize em 1 (no máximo 2) famílias por tokens.",
            lista, codigo)

    # ---------------------------------------------------------------- paleta de cores
    def _checar_cores(self, cores, maximo):
        if len(cores) <= maximo:
            return
        codigo = (":root {\n  /* Centralize a paleta em tokens e reutilize sempre os mesmos. */\n"
                  "  --cor-primaria: #2563eb;\n  --cor-texto:    #1a1a1a;\n  --cor-fundo:    #ffffff;\n"
                  "  --cor-borda:    #e5e7eb;\n  --cor-sucesso:  #16a34a;\n  --cor-erro:     #dc2626;\n}")
        self._melhoria(
            "Cores", "Baixa",
            f"{len(cores)} cores distintas na página",
            f"Foram detectadas {len(cores)} cores diferentes (texto, fundo e bordas). Acima de ~{maximo} "
            f"costuma indicar falta de um sistema de design. Reduza para uma paleta de tokens reaproveitáveis.",
            f"{len(cores)} cores", codigo)

    # ---------------------------------------------------------------- alvos de toque
    def _checar_alvos(self, alvos, minimo, max_itens):
        if not alvos:
            return
        minusculos = [a for a in alvos if a["w"] < 24 or a["h"] < 24]
        prioridade = "Alta" if minusculos else "Média"
        exemplos = sorted(alvos, key=lambda a: a["w"] * a["h"])[:max_itens]
        linhas = "; ".join(f"{a['sel']} ({a['w']}x{a['h']}px"
                           + (f', "{a["texto"]}"' if a["texto"] else "") + ")" for a in exemplos)
        codigo = (f"/* Alvo de toque mínimo recomendado: {minimo}x{minimo}px (WCAG 2.5.5 / mobile). */\n"
                  "a, button, [role=button], input[type=submit], select {\n"
                  f"  min-height: {minimo}px;\n  min-width: {minimo}px;\n"
                  "  padding: 12px 16px;\n  display: inline-flex;\n  align-items: center;\n"
                  "  justify-content: center;\n}")
        self._melhoria(
            "Alvos de toque", prioridade,
            f"{len(alvos)} botão(ões)/link(s) menores que {minimo}x{minimo}px",
            f"Elementos clicáveis pequenos são difíceis de acertar no dedo (e falham no WCAG 2.5.5). "
            f"Exemplos: {linhas}. Garanta {minimo}x{minimo}px de área clicável.",
            f"{len(alvos)} alvos pequenos", codigo)

    # ---------------------------------------------------------------- responsivo
    def _checar_responsivo(self, dados):
        if not dados.get("viewport_meta"):
            codigo = '<meta name="viewport" content="width=device-width, initial-scale=1">'
            self._melhoria(
                "Responsivo", "Alta", "Falta a <meta viewport>",
                "A página não declara a meta viewport, então o celular renderiza tudo encolhido e o "
                "usuário precisa dar zoom. Adicione a linha abaixo dentro do <head>.",
                "<head> sem meta viewport", codigo, linguagem="html")
        if dados.get("overflow"):
            lp, lj = dados.get("largura_pagina"), dados.get("largura_janela")
            codigo = ("/* Algo está mais largo que a tela e gera rolagem lateral. Caça-culpados:\n"
                      "   procure larguras fixas em px, imagens/tabelas sem limite e margens negativas. */\n"
                      "img, video, table, pre, iframe { max-width: 100%; }\n"
                      "* { min-width: 0; }   /* evita que filhos de flex/grid estourem o contêiner */")
            self._melhoria(
                "Responsivo", "Média", "Rolagem horizontal na página",
                f"O conteúdo tem {lp}px de largura numa janela de {lj}px, o que cria rolagem lateral — "
                f"sinal clássico de largura fixa ou elemento sem limite. Revise com o código abaixo.",
                f"{lp}px de conteúdo em {lj}px de janela", codigo)
