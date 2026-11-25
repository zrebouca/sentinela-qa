"""
Banco de dados local (SQLite) do painel.

Guarda tudo o que o QA cadastra e executa:
  projetos   -> sistemas em teste (nome, tipo, alvo, finalidade, versão, ambiente...)
  roteiros   -> arquivos .yaml de cada projeto
  execucoes  -> cada rodada de testes (opções usadas, finalidade, resultado, log)
  defeitos   -> bugs encontrados, com ciclo de vida (Aberto -> Em análise -> Corrigido -> Fechado)
  atividades -> linha do tempo do que aconteceu no sistema

O arquivo fica em  dados/sentinela.db  (ao lado do .exe ou na pasta do projeto).
"""

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime

_trava = threading.Lock()

STATUS_DEFEITO = ["Aberto", "Em análise", "Corrigido", "Fechado", "Não é defeito"]
FINALIDADES = ["Regressão", "Smoke (fumaça)", "Aceitação", "Exploratório", "Validação de correção", "Demonstração"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS projetos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL,              -- web | desktop
    alvo TEXT NOT NULL,
    finalidade TEXT DEFAULT '',
    versao TEXT DEFAULT '',
    responsavel TEXT DEFAULT '',
    ambiente TEXT DEFAULT '',
    cor TEXT DEFAULT '#3157d5',
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roteiros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    arquivo TEXT NOT NULL,           -- caminho do .yaml
    descricao TEXT DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    roteiro_id INTEGER REFERENCES roteiros(id) ON DELETE SET NULL,
    finalidade TEXT DEFAULT '',
    observacoes TEXT DEFAULT '',
    explorar INTEGER DEFAULT 0,
    usar_ia INTEGER DEFAULT 1,
    visivel INTEGER DEFAULT 0,
    status TEXT NOT NULL,            -- Na fila | Executando | Concluída | Erro
    criado_em TEXT NOT NULL,
    iniciado_em TEXT,
    finalizado_em TEXT,
    duracao_s REAL DEFAULT 0,
    total INTEGER DEFAULT 0,
    aprovados INTEGER DEFAULT 0,
    reprovados INTEGER DEFAULT 0,
    defeitos INTEGER DEFAULT 0,
    observacoes_qtd INTEGER DEFAULT 0,
    sugestoes INTEGER DEFAULT 0,
    pasta_relatorio TEXT,
    log TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS defeitos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id INTEGER NOT NULL REFERENCES execucoes(id) ON DELETE CASCADE,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    codigo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    severidade TEXT NOT NULL,
    status TEXT NOT NULL,
    origem TEXT DEFAULT '',
    caso_id TEXT DEFAULT '',
    passos TEXT DEFAULT '[]',
    esperado TEXT DEFAULT '',
    obtido TEXT DEFAULT '',
    evidencia TEXT,
    comentario TEXT DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS atividades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL,
    tipo TEXT NOT NULL,              -- projeto | roteiro | execucao | defeito | config
    texto TEXT NOT NULL,
    link TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS auditorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host TEXT NOT NULL,
    banco TEXT NOT NULL,
    nota INTEGER,
    achados INTEGER,
    criticos INTEGER,
    pasta TEXT,
    usou_ia INTEGER DEFAULT 0,
    criado_em TEXT NOT NULL,
    aplicacoes TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS preferencias (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def pasta_base() -> str:
    """Pasta do .exe (quando empacotado) ou a raiz do projeto (quando em Python)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pasta_dados() -> str:
    p = os.path.join(pasta_base(), "dados")
    os.makedirs(p, exist_ok=True)
    return p


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(os.path.join(pasta_dados(), "sentinela.db"), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def iniciar():
    with conectar() as con:
        con.executescript(ESQUEMA)


# ---------------------------------------------------------------- utilitários
def consulta(sql: str, params=(), um=False):
    with _trava, conectar() as con:
        cur = con.execute(sql, params)
        linhas = cur.fetchall()
    linhas = [dict(l) for l in linhas]
    return (linhas[0] if linhas else None) if um else linhas


def executar(sql: str, params=()) -> int:
    with _trava, conectar() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid


def registrar_atividade(tipo: str, texto: str, link: str = ""):
    executar("INSERT INTO atividades (quando, tipo, texto, link) VALUES (?,?,?,?)",
             (agora(), tipo, texto, link))


def pref(chave: str, padrao=None):
    linha = consulta("SELECT valor FROM preferencias WHERE chave=?", (chave,), um=True)
    return linha["valor"] if linha else padrao


def salvar_pref(chave: str, valor):
    executar("INSERT INTO preferencias (chave, valor) VALUES (?,?) "
             "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, str(valor)))


# ---------------------------------------------------------------- defeitos
def salvar_defeitos(execucao_id: int, projeto_id: int, registro):
    """Copia os defeitos de uma execução (objeto Registro) para o banco."""
    for d in registro.defeitos:
        executar(
            "INSERT INTO defeitos (execucao_id, projeto_id, codigo, descricao, severidade, status, origem,"
            " caso_id, passos, esperado, obtido, evidencia, criado_em, atualizado_em)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (execucao_id, projeto_id, d.id, d.descricao, d.severidade, "Aberto", d.origem, d.caso_id,
             json.dumps(d.passos_reproducao, ensure_ascii=False), d.esperado, d.obtido, d.evidencia,
             agora(), agora()),
        )
