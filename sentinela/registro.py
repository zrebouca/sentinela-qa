"""
Registro de tudo o que aconteceu na execução: caminho percorrido (cada ação
com horário e print), resultados dos casos, defeitos, observações e
sugestões da IA. É a "fonte de verdade" usada para gerar os relatórios.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Acao:
    """Uma linha do caminho percorrido."""
    ordem: int
    horario: str
    caso_id: str
    comando: str
    descricao: str
    status: str                 # "ok" ou "falha"
    print: str | None           # caminho relativo do print (ou None)
    duracao_ms: int
    detalhe: str = ""


@dataclass
class ResultadoCaso:
    id: str
    descricao: str
    funcionalidade: str
    passos: list[str]
    esperado: str
    obtido: str
    status: str                 # "APROVADO" ou "REPROVADO"
    print: str | None
    duracao_s: float


@dataclass
class Defeito:
    id: str
    descricao: str
    severidade: str
    status: str                 # "Aberto"
    passos_reproducao: list[str]
    esperado: str
    obtido: str
    evidencia: str | None
    origem: str                 # "Roteiro" ou "Exploração"
    caso_id: str = ""


@dataclass
class Observacao:
    categoria: str              # Acessibilidade, Console, Rede, Exploração, Execução
    texto: str
    print: str | None = None


@dataclass
class Sugestao:
    categoria: str              # Usabilidade, Texto, Acessibilidade, Funcionalidade
    titulo: str
    descricao: str
    prioridade: str = "Média"
    evidencia: str = ""


@dataclass
class MelhoriaUx:
    """Achado da auditoria de UI/UX: medido na página e com o código da correção pronto."""
    categoria: str              # Contraste, Tipografia, Cores, Alvos de toque, Responsivo
    prioridade: str             # Alta, Média, Baixa
    titulo: str
    descricao: str
    evidencia: str = ""
    codigo: str = ""            # trecho pronto para colar
    linguagem: str = "css"      # css | html | js


@dataclass
class Registro:
    pasta_saida: str
    log: callable = print
    inicio: datetime = field(default_factory=datetime.now)
    fim: datetime | None = None
    acoes: list[Acao] = field(default_factory=list)
    casos: list[ResultadoCaso] = field(default_factory=list)
    defeitos: list[Defeito] = field(default_factory=list)
    observacoes: list[Observacao] = field(default_factory=list)
    sugestoes: list[Sugestao] = field(default_factory=list)
    melhorias_ux: list[MelhoriaUx] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    _chaves_obs: set = field(default_factory=set)

    def __post_init__(self):
        self.pasta_prints = os.path.join(self.pasta_saida, "prints")
        os.makedirs(self.pasta_prints, exist_ok=True)

    # ---------------------------------------------------------------- prints
    def novo_print(self, caso_id: str, comando: str) -> tuple[str, str]:
        """Devolve (caminho_absoluto, caminho_relativo) para salvar um print."""
        n = len(self.acoes) + 1
        nome = re.sub(r"[^A-Za-z0-9_-]", "_", f"{n:03d}_{caso_id}_{comando}") + ".png"
        return os.path.join(self.pasta_prints, nome), f"prints/{nome}"

    # ---------------------------------------------------------------- ações
    def registrar_acao(self, caso_id, comando, descricao, status, print_rel,
                       duracao_ms, detalhe=""):
        acao = Acao(
            ordem=len(self.acoes) + 1,
            horario=datetime.now().strftime("%H:%M:%S"),
            caso_id=caso_id, comando=comando, descricao=descricao,
            status=status, print=print_rel, duracao_ms=duracao_ms, detalhe=detalhe,
        )
        self.acoes.append(acao)
        simbolo = "✔" if status == "ok" else "✘"
        self.log(f"  {simbolo} [{caso_id}] {descricao}" + (f" — {detalhe}" if status != "ok" and detalhe else ""))
        return acao

    # ---------------------------------------------------------------- defeitos
    def novo_defeito(self, **campos) -> Defeito:
        d = Defeito(id=f"BUG-{len(self.defeitos) + 1:03d}", status="Aberto", **campos)
        self.defeitos.append(d)
        return d

    # ---------------------------------------------------------------- observações
    def observar(self, categoria: str, texto: str, print_rel: str | None = None):
        """Adiciona uma observação sem repetir a mesma mensagem."""
        chave = (categoria, texto)
        if chave in self._chaves_obs:
            return
        self._chaves_obs.add(chave)
        self.observacoes.append(Observacao(categoria, texto, print_rel))

    def nova_melhoria_ux(self, **campos) -> MelhoriaUx:
        m = MelhoriaUx(**campos)
        self.melhorias_ux.append(m)
        return m

    def avisar(self, texto: str):
        self.avisos.append(texto)
        self.log(f"⚠ {texto}")

    # ---------------------------------------------------------------- resumo
    @property
    def aprovados(self) -> int:
        return sum(1 for c in self.casos if c.status == "APROVADO")

    @property
    def reprovados(self) -> int:
        return sum(1 for c in self.casos if c.status == "REPROVADO")
