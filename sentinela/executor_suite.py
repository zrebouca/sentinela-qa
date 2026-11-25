"""
Executor de SUÍTES de outros frameworks (tipo: suite).

O Sentinela roda a ferramenta que o time já usa e lê o resultado no formato
JUnit XML — o "idioma comum" dos frameworks de teste. Assim os resultados de
Pytest, Jest, Vitest, Cypress, Newman (Postman), Playwright TS, JUnit/TestNG
(Maven) ou Maestro entram no mesmo relatório, histórico e gestão de defeitos.

Exemplo de roteiro:

    sistema: Carrinho (testes unitários em Jest)
    tipo: suite
    ferramenta: jest                      # pytest | jest | vitest | cypress | newman | playwright-ts | maven | maestro
    pasta: ../exemplos_frameworks/jest_unitario
    # comando / junit / preparar são opcionais (cada ferramenta tem um padrão)
"""

import glob
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from sentinela.executor_base import ErroPasso, ExecutorBase
from sentinela.registro import ResultadoCaso


def _pytest_cmd() -> str:
    # Dentro do .exe usa o pytest embutido no próprio sentinela.exe (comando interno _pytest)
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" _pytest'
    return f'"{sys.executable}" -m pytest'


PRESETS = {
    "pytest": {"comando": "{pytest} -q -p no:cacheprovider --junitxml=resultados/junit.xml", "junit": "resultados/junit.xml",
               "nome": "Pytest"},
    "jest": {"comando": "npx jest --ci --reporters=default --reporters=jest-junit", "junit": "resultados/junit.xml",
             "preparar": "npm install --no-audit --no-fund", "env": {"JEST_JUNIT_OUTPUT_DIR": "resultados",
                                                                     "JEST_JUNIT_OUTPUT_NAME": "junit.xml"}, "nome": "Jest"},
    "vitest": {"comando": "npx vitest run --reporter=default --reporter=junit --outputFile.junit=resultados/junit.xml",
               "junit": "resultados/junit.xml", "preparar": "npm install --no-audit --no-fund", "nome": "Vitest"},
    "cypress": {"comando": 'npx cypress run --reporter junit --reporter-options "mochaFile=resultados/junit-[hash].xml"',
                "junit": "resultados/*.xml", "preparar": "npm install --no-audit --no-fund", "nome": "Cypress"},
    "newman": {"comando": "npx --yes newman run colecao.postman_collection.json -r cli,junit "
                          "--reporter-junit-export resultados/junit.xml", "junit": "resultados/junit.xml",
               "nome": "Newman (Postman)"},
    "playwright-ts": {"comando": "npx playwright test", "junit": "resultados/junit.xml",
                      "preparar": "npm install --no-audit --no-fund",
                      "env": {"PLAYWRIGHT_JUNIT_OUTPUT_NAME": "resultados/junit.xml"}, "nome": "Playwright (TypeScript)"},
    "maven": {"comando": "mvn -q test", "junit": "target/surefire-reports/*.xml", "nome": "JUnit 5 / TestNG (Maven)"},
    "maestro": {"comando": "maestro test flows --format junit --output resultados/junit.xml",
                "junit": "resultados/junit.xml", "nome": "Maestro (mobile)"},
}


class ExecutorSuite(ExecutorBase):
    tipo = "suite"

    def iniciar(self):
        cfg = self.roteiro.suite or {}
        ferramenta = str(cfg.get("ferramenta", "")).lower()
        if ferramenta not in PRESETS and not cfg.get("comando"):
            raise ErroPasso(f"Ferramenta '{ferramenta}' desconhecida. Use: {', '.join(PRESETS)} (ou informe 'comando').")
        preset = PRESETS.get(ferramenta, {})
        self.ferramenta = preset.get("nome", ferramenta or "comando")
        self.navegador = self.ferramenta
        pasta = cfg.get("pasta") or "."
        self.pasta = os.path.normpath(pasta if os.path.isabs(pasta) else os.path.join(self.roteiro.pasta, pasta))
        if not os.path.isdir(self.pasta):
            from sentinela.painel.banco import pasta_base
            alternativa = os.path.normpath(os.path.join(pasta_base(), pasta.lstrip("./\\").replace("../", "")))
            if os.path.isdir(alternativa):
                self.pasta = alternativa
            else:
                raise ErroPasso(f"Pasta da suíte não encontrada: {self.pasta}")
        self.comando = str(cfg.get("comando") or preset.get("comando", "")).replace("{pytest}", _pytest_cmd())
        self.junit = str(cfg.get("junit") or preset.get("junit", "resultados/junit.xml"))
        self.preparar = cfg.get("preparar") or preset.get("preparar")
        self.env = dict(os.environ, **preset.get("env", {}), **{k: str(v) for k, v in (cfg.get("env") or {}).items()})
        self.registro.log(f"Ferramenta: {self.ferramenta} · pasta: {self.pasta}")

    def _rodar(self, comando: str, limite: int) -> tuple[int, str]:
        self.registro.log(f"$ {comando}")
        try:
            r = subprocess.run(comando, cwd=self.pasta, shell=True, env=self.env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=limite)
        except subprocess.TimeoutExpired:
            raise ErroPasso(f"O comando passou de {limite // 60} minutos e foi interrompido: {comando}")
        saida = (r.stdout or "") + (r.stderr or "")
        for linha in saida.splitlines()[-60:]:
            self.registro.log("   " + linha)
        return r.returncode, saida

    def executar_todos(self):
        inicio = time.time()
        self.caso_atual = "SUITE"
        if self.preparar and not os.path.isdir(os.path.join(self.pasta, "node_modules")):
            t0 = time.time()
            codigo, saida = self._rodar(self.preparar, 900)
            self.registro.registrar_acao("SUITE", "preparar", f"Preparar a suíte ({self.preparar})",
                                         "ok" if codigo == 0 else "falha", None, int((time.time() - t0) * 1000),
                                         "" if codigo == 0 else saida.strip().splitlines()[-1:][0][:200] if saida.strip() else "")
            if codigo != 0:
                self._falha_geral(f"Falha ao preparar a suíte ({self.preparar}). Verifique se o Node.js/npm está instalado.")
                return
        for antigo in glob.glob(os.path.join(self.pasta, self.junit)):
            os.remove(antigo)
        t0 = time.time()
        codigo, saida = self._rodar(self.comando, 1800)
        arquivos = glob.glob(os.path.join(self.pasta, self.junit))
        self.registro.registrar_acao("SUITE", "comando", f"Rodar {self.ferramenta}: {self.comando}",
                                     "ok" if arquivos else "falha", None, int((time.time() - t0) * 1000),
                                     f"código de saída {codigo}")
        if not arquivos:
            dica = ""
            if "não é reconhecido" in saida or "not recognized" in saida or "command not found" in saida:
                dica = " A ferramenta não está instalada neste computador."
            self._falha_geral(f"{self.ferramenta} não gerou o resultado JUnit ({self.junit}).{dica} "
                              f"Últimas linhas: {saida.strip()[-300:]}")
            return
        self._ler_junit(arquivos, time.time() - inicio)

    def _falha_geral(self, msg: str):
        self.registro.casos.append(ResultadoCaso("SUITE", f"Execução da suíte {self.ferramenta}", "",
                                                 [self.comando], "A suíte roda e gera o resultado", msg,
                                                 "REPROVADO", None, 0))
        self.registro.novo_defeito(descricao=msg[:400], severidade="Alta", passos_reproducao=[f"cd {self.pasta}", self.comando],
                                   esperado="A suíte roda e gera o resultado JUnit", obtido=msg, evidencia=None,
                                   origem=self.ferramenta, caso_id="SUITE")

    def _ler_junit(self, arquivos: list[str], duracao: float):
        n = 0
        for arq in arquivos:
            try:
                raiz = ET.parse(arq).getroot()
            except ET.ParseError as e:
                self.registro.avisar(f"Resultado JUnit inválido ({os.path.basename(arq)}): {e}")
                continue
            for tc in raiz.iter("testcase"):
                n += 1
                cid = f"T{n:02d}"
                classe, nome = tc.get("classname", ""), tc.get("name", "teste")
                desc = f"{classe} › {nome}" if classe and classe not in nome else nome
                tempo = float(tc.get("time") or 0)
                falha = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
                pulado = tc.find("skipped") is not None
                self.caso_atual = cid
                if pulado:
                    self.registro.observar(self.ferramenta, f"Teste pulado: {desc}")
                    self.registro.registrar_acao(cid, "teste", desc, "ok", None, int(tempo * 1000), "pulado (skipped)")
                    continue
                if falha is not None:
                    mensagem = (falha.get("message") or (falha.text or "").strip().splitlines()[0:1] or ["falhou"])
                    mensagem = mensagem if isinstance(mensagem, str) else mensagem[0]
                    detalhe = (falha.text or "").strip()
                    status, obtido = "REPROVADO", f"Falhou: {mensagem[:300]}"
                    self.registro.novo_defeito(
                        descricao=f"{desc}: {mensagem[:250]}", severidade="Média",
                        passos_reproducao=[f"cd {self.pasta}", self.comando, f"Teste: {desc}"],
                        esperado="O teste passa", obtido=(detalhe or mensagem)[:1500], evidencia=None,
                        origem=self.ferramenta, caso_id=cid)
                else:
                    status, obtido = "APROVADO", f"Passou em {tempo:.2f}s"
                self.registro.registrar_acao(cid, "teste", desc, "ok" if status == "APROVADO" else "falha",
                                             None, int(tempo * 1000), "" if status == "APROVADO" else obtido)
                self.registro.casos.append(ResultadoCaso(cid, desc, classe, [f"{self.ferramenta}: {nome}"],
                                                         "O teste passa", obtido, status, None, round(tempo, 2)))
        if n == 0:
            self.registro.avisar("O resultado JUnit não tinha nenhum caso de teste.")
        self.registro.log(f"  {n} teste(s) lido(s) do JUnit em {duracao:.1f}s")
