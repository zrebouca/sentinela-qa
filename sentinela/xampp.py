"""
Integração com o XAMPP (Apache + PHP + MariaDB) para os sistemas de treino.

    sentinela xampp status      mostra se MySQL e Apache estão rodando
    sentinela xampp iniciar     liga MySQL e Apache (se estiverem parados)
    sentinela xampp instalar    cria o banco sentinela_loja e copia a Loja PHP para htdocs/sentinela-loja

A Loja PHP fica em http://localhost/sentinela-loja (usuário qa@loja.test / treino123 — fictícios).
"""

import os
import shutil
import socket
import subprocess

from sentinela.painel.banco import pasta_base

PASTA_PADRAO = r"C:\xampp"
URL_LOJA = "http://localhost/sentinela-loja"


class ErroXampp(Exception):
    pass


def pasta_xampp() -> str:
    pasta = os.getenv("SENTINELA_XAMPP", PASTA_PADRAO)
    if not os.path.isdir(pasta):
        raise ErroXampp(f"XAMPP não encontrado em {pasta} (defina SENTINELA_XAMPP no .env).")
    return pasta


def porta_aberta(porta: int, host="127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex((host, porta)) == 0


def status() -> dict:
    try:
        pasta = pasta_xampp()
    except ErroXampp as e:
        return {"instalado": False, "erro": str(e), "mysql": porta_aberta(3306), "apache": porta_aberta(80)}
    return {"instalado": True, "pasta": pasta, "mysql": porta_aberta(3306), "apache": porta_aberta(80),
            "loja": os.path.isdir(os.path.join(pasta, "htdocs", "sentinela-loja"))}


def _iniciar_processo(exe: str, args: list[str], cwd: str):
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe, *args], cwd=cwd, creationflags=flags, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


def iniciar(log=print) -> dict:
    import time
    pasta = pasta_xampp()
    if not porta_aberta(3306):
        log("Ligando o MySQL (MariaDB) do XAMPP...")
        bin_mysql = os.path.join(pasta, "mysql", "bin")
        _iniciar_processo(os.path.join(bin_mysql, "mysqld.exe"),
                          [f"--defaults-file={os.path.join(bin_mysql, 'my.ini')}", "--standalone"], bin_mysql)
    if not porta_aberta(80):
        log("Ligando o Apache do XAMPP...")
        bin_apache = os.path.join(pasta, "apache", "bin")
        _iniciar_processo(os.path.join(bin_apache, "httpd.exe"), [], bin_apache)
    for _ in range(30):
        if porta_aberta(3306) and porta_aberta(80):
            break
        time.sleep(0.5)
    st = status()
    if not st["mysql"]:
        raise ErroXampp("O MySQL não subiu. Abra o XAMPP Control Panel e veja o log do MySQL.")
    if not st["apache"]:
        raise ErroXampp("O Apache não subiu (a porta 80 pode estar ocupada por outro programa, ex.: Skype/IIS).")
    return st


def _hash_senha(senha: str) -> str:
    """Gera o hash bcrypt com o próprio PHP do XAMPP (o mesmo que o sistema usa no login)."""
    php = os.path.join(pasta_xampp(), "php", "php.exe")
    r = subprocess.run([php, "-r", "echo password_hash($argv[1], PASSWORD_DEFAULT);", senha],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not r.stdout.startswith("$2"):
        raise ErroXampp(f"Não foi possível gerar o hash da senha com o PHP: {r.stderr[:150]}")
    return r.stdout.strip()


def instalar_loja(usuario="root", senha="", log=print) -> str:
    from sentinela.banco_auditor import conectar
    origem = os.path.join(pasta_base(), "sistemas_treino", "loja_php")
    if not os.path.isdir(origem):
        raise ErroXampp(f"Arquivos da Loja PHP não encontrados em {origem}")
    pasta = pasta_xampp()
    if not porta_aberta(3306):
        raise ErroXampp("O MySQL está parado. Rode 'sentinela xampp iniciar' antes.")

    log("Criando o banco sentinela_loja (com problemas plantados para a auditoria)...")
    with open(os.path.join(origem, "banco.sql"), encoding="utf-8") as f:
        sql = f.read()
    comandos = [c.strip() for c in "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).split(";")
                if c.strip()]
    con = conectar("127.0.0.1", 3306, usuario, senha)
    try:
        with con.cursor() as c:
            for comando in comandos:
                c.execute(comando)
            c.execute("INSERT INTO sentinela_loja.usuarios (nome, email, senha, perfil) VALUES (%s, %s, %s, %s)",
                      ("QA Treino", "qa@loja.test", _hash_senha(os.getenv("LOJA_SENHA_TREINO", "treino123")), "admin"))
    finally:
        con.close()

    destino = os.path.join(pasta, "htdocs", "sentinela-loja")
    log(f"Copiando o sistema para {destino}...")
    shutil.copytree(origem, destino, dirs_exist_ok=True, ignore=shutil.ignore_patterns("banco.sql"))
    log(f"Pronto: {URL_LOJA}")
    return URL_LOJA
