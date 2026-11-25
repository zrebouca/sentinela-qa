"""
Linha de comando do Sentinela QA.

Exemplos:
    sentinela rodar --roteiro roteiros/web_saucedemo.yaml
    sentinela rodar --alvo https://www.saucedemo.com --roteiro meu.yaml --explorar --visivel
    sentinela rodar --alvo calc.exe --roteiro roteiros/desktop_calculadora.yaml
    sentinela validar --roteiro meu.yaml
    sentinela novo --arquivo meu_roteiro.yaml
    sentinela painel          (ou dois cliques no .exe)

Código de saída: 0 = tudo aprovado, 1 = algum caso reprovado/defeito, 2 = erro de uso.
(Útil para CI/CD: o pipeline fica vermelho quando um teste falha.)
"""

import argparse
import os
import sys
import webbrowser

from sentinela import __version__
from sentinela.roteiro import MODELO_ROTEIRO, ErroRoteiro, carregar_roteiro


def _console_utf8():
    # Garante acentos e símbolos (✔ ✘) no terminal do Windows
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _lista(texto: str | None) -> list[str] | None:
    return [t.strip() for t in texto.split(",") if t.strip()] if texto else None


def servir_site_treino(porta: int = 8000, bloquear: bool = True):
    """Serve a pasta site_treino/ (site local para praticar e para o CI)."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from sentinela.painel.banco import pasta_base
    pasta = os.path.join(pasta_base(), "site_treino")
    if not os.path.isdir(pasta):
        print(f"Pasta do site de treino não encontrada: {pasta}")
        sys.exit(2)

    class Silencioso(SimpleHTTPRequestHandler):
        def log_message(self, *a):  # não polui o terminal
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", porta), functools.partial(Silencioso, directory=pasta))
    if not bloquear:
        import threading
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        return servidor
    print(f"Site de treino em http://127.0.0.1:{porta}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


def _comando_banco(args):
    from datetime import datetime

    from sentinela import banco_auditor as ba
    from sentinela.motor import carregar_env
    carregar_env()
    c = ba.config_padrao()
    cred = {"host": args.host or c["host"], "porta": args.porta or c["porta"],
            "usuario": args.usuario or c["usuario"], "senha": args.senha if args.senha is not None else c["senha"]}
    try:
        if args.acao == "listar":
            con = ba.conectar(**cred)
            print("Bancos:", ", ".join(ba.listar_bancos(con)))
            con.close()
            return
        if not args.banco:
            print("Informe --banco"); sys.exit(2)
        if args.acao == "backup":
            print("Backup salvo em", ba.fazer_backup(args.banco, os.path.join(args.saida, "backups"), **cred))
            return
        aud = ba.auditar(args.banco, usar_ia=args.ia, **cred)
        pasta = os.path.join(args.saida, f"auditoria_{args.banco}_{datetime.now():%Y%m%d_%H%M%S}")
        r = ba.gerar_relatorio(aud, pasta)
        print(f"Nota {aud.resumo['nota']}/100 · {aud.resumo['achados']} achado(s) · relatório: {r['html']}")
        for a in aud.achados:
            marca = "  [corrigível]" if a["aplicavel"] else ""
            print(f"  {a['id']} {a['severidade']:<7} {a['objeto']}: {a['problema']}{marca}")
        if args.acao == "aplicar":
            if not args.confirmar or not args.correcoes:
                print("Para aplicar use --correcoes C001,C002 --confirmar (um backup é feito antes)."); sys.exit(2)
            res = ba.aplicar(aud, [x.strip() for x in args.correcoes.split(",")], os.path.join(args.saida, "backups"), **cred)
            print("Backup:", res["backup"])
            sys.exit(0 if all(x["ok"] for x in res["resultados"]) else 1)
    except ba.ErroBanco as e:
        print(f"✘ {e}"); sys.exit(2)


def main(argv=None):
    _console_utf8()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        # Dois cliques no .exe (sem argumentos) -> abre o painel no navegador
        argv = ["painel"]
    if argv[0] == "_pytest":
        # Uso interno: dentro do .exe o Sentinela roda o pytest embutido (o PC não precisa ter Python)
        import pytest
        sys.exit(pytest.main(argv[1:]))

    p = argparse.ArgumentParser(prog="sentinela", description="Sentinela QA — testes automatizados web e desktop guiados por roteiro.")
    p.add_argument("--versao", action="version", version=f"Sentinela QA {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    r = sub.add_parser("rodar", help="Executa um roteiro de teste")
    r.add_argument("--roteiro", required=True, help="Arquivo .yaml/.json com os casos de teste")
    r.add_argument("--alvo", help="URL do site ou caminho do .exe (sobrepõe o 'alvo' do roteiro)")
    r.add_argument("--explorar", action="store_true", help="Faz a exploração leve de validações (dados inválidos)")
    r.add_argument("--sem-ia", action="store_true", help="Não usa a IA para sugerir melhorias")
    r.add_argument("--visivel", action="store_true", help="Mostra o navegador durante o teste")
    r.add_argument("--saida", default="relatorios", help="Pasta onde salvar os relatórios (padrão: relatorios)")
    r.add_argument("--embutir-prints", action="store_true", help="Coloca os prints dentro do HTML (um arquivo só, fácil de enviar)")
    r.add_argument("--abrir", action="store_true", help="Abre o relatório no navegador ao terminar")
    r.add_argument("--casos", help="Roda só estes casos, separados por vírgula (ex.: CT01,CT02)")
    r.add_argument("--pular", help="Não roda estes casos (ex.: CT09)")

    bd = sub.add_parser("banco", help="Auditoria de banco MySQL/MariaDB (XAMPP)")
    bd.add_argument("acao", choices=["listar", "auditar", "aplicar", "backup"])
    bd.add_argument("--banco", help="Nome do banco")
    bd.add_argument("--host"); bd.add_argument("--porta", type=int); bd.add_argument("--usuario")
    bd.add_argument("--senha", help="Prefira SENTINELA_DB_SENHA no .env (a senha na linha de comando fica no histórico)")
    bd.add_argument("--ia", action="store_true", help="Análise extra da estrutura com IA")
    bd.add_argument("--correcoes", help="IDs a aplicar, ex.: C001,C004 (só as marcadas como corrigíveis)")
    bd.add_argument("--confirmar", action="store_true", help="Obrigatório para aplicar (faz backup antes)")
    bd.add_argument("--saida", default="relatorios", help="Pasta da auditoria")

    ex = sub.add_parser("exportar", help="Exporta um roteiro para outro framework (Cypress, Playwright TS, Selenium, RestAssured, Postman...)")
    ex.add_argument("--roteiro", required=True)
    ex.add_argument("--para", required=True, help="playwright-ts | cypress | selenium-py | pytest-api | restassured | appium-py | maestro | postman")
    ex.add_argument("--saida", required=True, help="Pasta onde salvar o código gerado")

    pm = sub.add_parser("postman", help="Importa uma coleção do Postman (v2.1) como roteiro do Sentinela")
    pm.add_argument("--colecao", required=True, help="Arquivo .json exportado do Postman")
    pm.add_argument("--arquivo", required=True, help="Roteiro .yaml a criar")

    xp = sub.add_parser("xampp", help="Liga o XAMPP e instala a Loja PHP de treino")
    xp.add_argument("acao", choices=["status", "iniciar", "instalar"])

    g = sub.add_parser("gherkin", help="Converte um roteiro YAML em cenários Gherkin (.feature)")
    g.add_argument("--roteiro", required=True)
    g.add_argument("--arquivo", help="Onde salvar o .feature (padrão: mostra na tela)")

    st = sub.add_parser("site-treino", help="Sobe o site de treino local em http://127.0.0.1:8000")
    st.add_argument("--porta", type=int, default=8000)

    v = sub.add_parser("validar", help="Só confere se o roteiro está bem escrito (não executa)")
    v.add_argument("--roteiro", required=True)

    n = sub.add_parser("novo", help="Cria um roteiro modelo para você editar")
    n.add_argument("--arquivo", default="meu_roteiro.yaml")

    pn = sub.add_parser("painel", help="Abre o painel web (cadastros, execuções, defeitos)")
    pn.add_argument("--porta", type=int, default=8765)
    pn.add_argument("--sem-navegador", action="store_true", help="Não abre o navegador automaticamente")

    args = p.parse_args(argv)

    if args.comando == "painel":
        from sentinela.painel.app import iniciar_painel
        iniciar_painel(abrir_navegador=not args.sem_navegador, porta=args.porta)
        return

    if args.comando == "exportar":
        from sentinela.exportar import exportar, salvar
        try:
            arquivos = exportar(carregar_roteiro(args.roteiro), args.para)
        except (ErroRoteiro, ValueError) as e:
            print(f"✘ {e}"); sys.exit(2)
        for c in salvar(arquivos, args.saida):
            print("  ✔", c)
        return

    if args.comando == "postman":
        import json as _json
        from sentinela.postman import importar_colecao
        with open(args.colecao, encoding="utf-8-sig") as f:
            texto, est = importar_colecao(_json.load(f))
        with open(args.arquivo, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"✔ {est['casos']} caso(s) importado(s) para {args.arquivo}"
              + (f" · {est['nao_convertidas']} linha(s) de teste sem conversão automática" if est["nao_convertidas"] else ""))
        return

    if args.comando == "xampp":
        from sentinela import xampp
        from sentinela.motor import carregar_env
        carregar_env()
        try:
            if args.acao == "status":
                print(xampp.status())
            elif args.acao == "iniciar":
                print(xampp.iniciar())
            else:
                xampp.iniciar()
                from sentinela.banco_auditor import config_padrao
                c = config_padrao()
                xampp.instalar_loja(c["usuario"], c["senha"])
        except xampp.ErroXampp as e:
            print(f"✘ {e}"); sys.exit(2)
        return

    if args.comando == "banco":
        _comando_banco(args)
        return

    if args.comando == "gherkin":
        from sentinela.gherkin import roteiro_para_feature
        try:
            texto = roteiro_para_feature(carregar_roteiro(args.roteiro))
        except ErroRoteiro as e:
            print(f"✘ Roteiro com problema: {e}")
            sys.exit(2)
        if args.arquivo:
            with open(args.arquivo, "w", encoding="utf-8") as f:
                f.write(texto + "\n")
            print(f"✔ Gherkin salvo em {args.arquivo}")
        else:
            print(texto)
        return

    if args.comando == "site-treino":
        servir_site_treino(args.porta)
        return

    if args.comando == "novo":
        if os.path.exists(args.arquivo):
            print(f"O arquivo '{args.arquivo}' já existe; escolha outro nome.")
            sys.exit(2)
        with open(args.arquivo, "w", encoding="utf-8") as f:
            f.write(MODELO_ROTEIRO)
        print(f"Roteiro modelo criado: {args.arquivo}")
        return

    if args.comando == "validar":
        try:
            rot = carregar_roteiro(args.roteiro)
        except ErroRoteiro as e:
            print(f"✘ Roteiro com problema: {e}")
            sys.exit(2)
        total = sum(len(c.passos) for c in rot.casos)
        print(f"✔ Roteiro OK: {rot.sistema} — {len(rot.casos)} caso(s), {total} passo(s)")
        for c in rot.casos:
            print(f"   {c.id}: {c.descricao} ({len(c.passos)} passos)")
        return

    # rodar
    from sentinela.motor import executar
    try:
        registro, caminhos = executar(
            args.roteiro, alvo=args.alvo, explorar=args.explorar, usar_ia=not args.sem_ia,
            visivel=args.visivel, saida=args.saida, embutir_prints=args.embutir_prints,
            somente=_lista(args.casos), pular=_lista(args.pular),
        )
    except ErroRoteiro as e:
        print(f"✘ Roteiro com problema: {e}")
        sys.exit(2)
    if args.abrir:
        webbrowser.open("file:///" + caminhos["html"].replace("\\", "/"))
    sys.exit(0 if registro.reprovados == 0 and not registro.defeitos else 1)


if __name__ == "__main__":
    main()
