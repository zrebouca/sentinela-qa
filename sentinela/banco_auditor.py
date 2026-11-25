"""
Auditor de banco de dados (MySQL / MariaDB — o banco do XAMPP).

O que faz:
  1. Conecta com usuário e senha (lidos do .env ou informados no painel).
  2. Lê a ESTRUTURA pelo information_schema: tabelas, colunas, índices,
     chaves estrangeiras, tamanho, engine, charset e configurações do servidor.
     Não lê o conteúdo das tabelas — só faz contagens (ex.: quantas senhas parecem
     estar sem hash, quantos registros órfãos existem). Nenhum dado pessoal sai do banco.
  3. Aplica regras de boas práticas e devolve, para cada problema:
       - o que está errado e por que isso importa;
       - COMO corrigir (SQL pronto);
       - ONDE agir (banco, código da aplicação ou configuração do servidor);
       - qual PROBLEMA FUTURO é provável se nada for feito (previsão).
  4. Calcula uma nota de saúde (0 a 100) e estima o crescimento do banco.
  5. Opcional: aplica as correções escolhidas, SEMPRE fazendo backup (mysqldump) antes.

Uso pela linha de comando:
    sentinela banco auditar --banco pdv_pro
    sentinela banco aplicar --banco sentinela_loja --correcoes C001,C004 --confirmar
"""

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime

SEV_PESO = {"Crítica": 15, "Alta": 8, "Média": 4, "Baixa": 1, "Info": 0}
LIMITES_INT = {"tinyint": 127, "smallint": 32767, "mediumint": 8388607, "int": 2147483647, "bigint": 9223372036854775807}
LIMITES_INT_UNSIGNED = {"tinyint": 255, "smallint": 65535, "mediumint": 16777215, "int": 4294967295,
                        "bigint": 18446744073709551615}

RE_DINHEIRO = re.compile(r"(preco|preço|valor|total|saldo|custo|salario|desconto|price|amount|subtotal|frete|troco)", re.I)
RE_DATA = re.compile(r"(^data|^dt_|_data$|_em$|nascimento|criado|atualizado|vencimento|created|updated|_at$|date)", re.I)
RE_SENHA = re.compile(r"^(senha|password|pass|pwd|hash_senha|senha_hash)$", re.I)
RE_UNICO = re.compile(r"^(cpf|cnpj|email|e_mail|login|usuario|username|codigo_barras|sku)$", re.I)
RE_OBRIGATORIO = re.compile(r"^(nome|name|email|status|titulo|descricao|login|usuario)$", re.I)


class ErroBanco(Exception):
    pass


@dataclass
class Achado:
    id: str
    categoria: str          # Estrutura, Integridade, Desempenho, Segurança, Tipos de dados, Servidor, Futuro
    severidade: str         # Crítica, Alta, Média, Baixa, Info
    objeto: str             # banco, tabela ou tabela.coluna
    problema: str
    impacto: str            # por que importa
    previsao: str           # problema futuro provável
    onde_agir: str          # Banco de dados / Código da aplicação / Configuração do servidor
    como_corrigir: str      # explicação
    sql: str = ""           # SQL sugerido (vazio quando a correção não é no banco)
    aplicavel: bool = False  # pode ser aplicado automaticamente pelo Sentinela


@dataclass
class Auditoria:
    host: str
    banco: str
    versao: str
    quando: str
    tabelas: list = field(default_factory=list)
    relacoes: list = field(default_factory=list)
    achados: list = field(default_factory=list)
    resumo: dict = field(default_factory=dict)
    previsoes: list = field(default_factory=list)
    sugestoes_ia: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


# ====================================================================== conexão
def config_padrao() -> dict:
    """Credenciais vindas do .env (padrão do XAMPP: root sem senha em localhost)."""
    return {
        "host": os.getenv("SENTINELA_DB_HOST", "127.0.0.1"),
        "porta": int(os.getenv("SENTINELA_DB_PORTA", "3306")),
        "usuario": os.getenv("SENTINELA_DB_USUARIO", "root"),
        "senha": os.getenv("SENTINELA_DB_SENHA", ""),
    }


def conectar(host="127.0.0.1", porta=3306, usuario="root", senha="", banco=None):
    import pymysql
    try:
        return pymysql.connect(host=host, port=int(porta), user=usuario, password=senha, database=banco,
                               charset="utf8mb4", connect_timeout=8, autocommit=True,
                               cursorclass=pymysql.cursors.DictCursor)
    except pymysql.err.OperationalError as e:
        codigo = e.args[0] if e.args else 0
        dicas = {2003: "o MySQL não está rodando (abra o XAMPP e clique em Start no MySQL)",
                 1045: "usuário ou senha incorretos", 1049: f"o banco '{banco}' não existe"}
        raise ErroBanco(f"Não foi possível conectar: {dicas.get(codigo, e.args[-1] if e.args else e)}") from e


def listar_bancos(con) -> list[str]:
    with con.cursor() as c:
        c.execute("SHOW DATABASES")
        sistema = {"information_schema", "mysql", "performance_schema", "sys", "phpmyadmin"}
        return [r["Database"] for r in c.fetchall() if r["Database"] not in sistema]


def _q(con, sql, params=()):
    with con.cursor() as c:
        c.execute(sql, params)
        return c.fetchall()


def _ident(nome: str) -> str:
    """Nome de tabela/coluna entre crases (seguro para montar SQL)."""
    return "`" + str(nome).replace("`", "``") + "`"


# ====================================================================== coleta
def coletar(con, banco: str) -> dict:
    tabelas = _q(con, """SELECT TABLE_NAME nome, ENGINE engine, TABLE_ROWS linhas, DATA_LENGTH dados,
        INDEX_LENGTH indices, AUTO_INCREMENT auto_inc, TABLE_COLLATION collation, CREATE_TIME criada,
        TABLE_COMMENT comentario FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME""", (banco,))
    colunas = _q(con, """SELECT TABLE_NAME tabela, COLUMN_NAME nome, DATA_TYPE tipo, COLUMN_TYPE tipo_completo,
        IS_NULLABLE nulo, COLUMN_DEFAULT padrao, COLUMN_KEY chave, EXTRA extra,
        CHARACTER_MAXIMUM_LENGTH tamanho, CHARACTER_SET_NAME charset, ORDINAL_POSITION pos
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION""", (banco,))
    indices = _q(con, """SELECT TABLE_NAME tabela, INDEX_NAME nome, NON_UNIQUE nao_unico, SEQ_IN_INDEX seq,
        COLUMN_NAME coluna FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX""", (banco,))
    fks = _q(con, """SELECT k.TABLE_NAME tabela, k.COLUMN_NAME coluna, k.REFERENCED_TABLE_NAME ref_tabela,
        k.REFERENCED_COLUMN_NAME ref_coluna, k.CONSTRAINT_NAME nome, r.DELETE_RULE ao_excluir
        FROM information_schema.KEY_COLUMN_USAGE k
        LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS r
          ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME
        WHERE k.TABLE_SCHEMA=%s AND k.REFERENCED_TABLE_NAME IS NOT NULL""", (banco,))
    variaveis = {r["Variable_name"]: r["Value"] for r in _q(con, "SHOW VARIABLES WHERE Variable_name IN "
                 "('version','sql_mode','character_set_server','collation_server','max_connections',"
                 "'innodb_buffer_pool_size','slow_query_log','long_query_time','log_bin','default_storage_engine',"
                 "'max_allowed_packet','wait_timeout','bind_address')")}
    try:
        usuarios = _q(con, "SELECT User usuario, Host host, (authentication_string='' AND "
                           "COALESCE(Password,'')='') AS sem_senha FROM mysql.user")
    except Exception:
        try:
            usuarios = _q(con, "SELECT User usuario, Host host, (authentication_string='') AS sem_senha FROM mysql.user")
        except Exception:
            usuarios = None   # sem permissão para ver usuários
    return {"tabelas": tabelas, "colunas": colunas, "indices": indices, "fks": fks,
            "variaveis": variaveis, "usuarios": usuarios}


# ====================================================================== análise
class _Contador:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"C{self.n:03d}"


def analisar(con, banco: str, dados: dict) -> list[Achado]:
    ach: list[Achado] = []
    novo_id = _Contador()

    def add(**k):
        ach.append(Achado(id=novo_id(), **k))

    tabelas = {t["nome"]: t for t in dados["tabelas"]}
    cols_por_tab: dict[str, list] = {}
    for c in dados["colunas"]:
        cols_por_tab.setdefault(c["tabela"], []).append(c)
    idx_por_tab: dict[str, dict] = {}
    for i in dados["indices"]:
        idx_por_tab.setdefault(i["tabela"], {}).setdefault(i["nome"], {"unico": not i["nao_unico"], "colunas": []})
        idx_por_tab[i["tabela"]][i["nome"]]["colunas"].append(i["coluna"])
    fk_cols = {(f["tabela"], f["coluna"]) for f in dados["fks"]}

    def indexada(tab, col):
        return any(ix["colunas"][0] == col for ix in idx_por_tab.get(tab, {}).values())

    def unica(tab, col):
        return any(ix["unico"] and ix["colunas"] == [col] for ix in idx_por_tab.get(tab, {}).values())

    # ------------------------------------------------------------ servidor
    v = dados["variaveis"]
    versao = v.get("version", "")
    m = re.match(r"(\d+)\.(\d+)", versao)
    if m and "mariadb" in versao.lower() and (int(m[1]), int(m[2])) < (10, 6):
        add(categoria="Servidor", severidade="Média", objeto="servidor",
            problema=f"MariaDB {m[1]}.{m[2]} já saiu de suporte (sem correções de segurança).",
            impacto="Falhas de segurança descobertas não serão mais corrigidas nesta versão.",
            previsao="Incompatibilidade com bibliotecas novas e risco de vulnerabilidades conhecidas.",
            onde_agir="Configuração do servidor",
            como_corrigir="Atualize o XAMPP (ou o MariaDB) para uma versão LTS atual (10.11 ou 11.4). Faça backup antes.")
    if "STRICT_TRANS_TABLES" not in v.get("sql_mode", "") and "STRICT_ALL_TABLES" not in v.get("sql_mode", ""):
        add(categoria="Servidor", severidade="Média", objeto="servidor",
            problema="O sql_mode não está em modo estrito (STRICT_TRANS_TABLES).",
            impacto="Valores inválidos são aceitos em silêncio: textos cortados, datas '0000-00-00', números truncados.",
            previsao="Dados corrompidos sem nenhum erro aparecer na aplicação — difícil de descobrir depois.",
            onde_agir="Configuração do servidor",
            como_corrigir="No my.ini, em [mysqld]: sql_mode=STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,"
                          "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION — teste a aplicação antes.",
            sql="SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';")
    if v.get("character_set_server", "").lower().startswith(("latin1", "utf8mb3")) or v.get("character_set_server") == "utf8":
        add(categoria="Servidor", severidade="Baixa", objeto="servidor",
            problema=f"Charset padrão do servidor é {v.get('character_set_server')}.",
            impacto="Tabelas novas nascem sem suporte completo a acentos/emojis.",
            previsao="Erros 'Incorrect string value' quando usuários digitarem emojis ou certos caracteres.",
            onde_agir="Configuração do servidor",
            como_corrigir="No my.ini: character-set-server=utf8mb4 e collation-server=utf8mb4_unicode_ci.")
    if v.get("slow_query_log", "OFF").upper() in ("OFF", "0"):
        add(categoria="Servidor", severidade="Baixa", objeto="servidor",
            problema="O log de consultas lentas (slow_query_log) está desligado.",
            impacto="Não há como descobrir quais consultas deixam o sistema lento.",
            previsao="Quando o sistema ficar lento com mais dados, não haverá pistas de onde agir.",
            onde_agir="Configuração do servidor",
            como_corrigir="Ligue o log de consultas lentas (acima de 1 segundo).",
            sql="SET GLOBAL slow_query_log = 'ON';\nSET GLOBAL long_query_time = 1;")

    if dados["usuarios"] is not None:
        # Usuários sem senha: um achado por usuário (juntando os hosts)
        sem_senha: dict[str, list] = {}
        for u in dados["usuarios"]:
            if u["usuario"] and u["sem_senha"]:
                sem_senha.setdefault(u["usuario"], []).append(u["host"])
        for usuario, hosts in sem_senha.items():
            add(categoria="Segurança", severidade="Crítica" if usuario == "root" else "Alta", objeto="servidor",
                problema=f"O usuário '{usuario}' não tem senha (hosts: {', '.join(hosts)}).",
                impacto="Qualquer programa no computador (ou na rede, se a porta 3306 estiver aberta) acessa e apaga tudo.",
                previsao="Perda ou vazamento total dos dados se o PC for exposto na rede ou infectado.",
                onde_agir="Configuração do servidor + código da aplicação (atualizar a senha na conexão)",
                como_corrigir="Defina uma senha forte e crie um usuário só para a aplicação, com permissão "
                              "apenas no banco dela (não use root na aplicação). No XAMPP, atualize também "
                              "o phpMyAdmin (config.inc.php).",
                sql="-- troque SENHA_FORTE antes de rodar; atualize também o PHP/aplicação\n"
                    + "\n".join(f"ALTER USER '{usuario}'@'{h}' IDENTIFIED BY 'SENHA_FORTE';" for h in hosts)
                    + f"\nCREATE USER IF NOT EXISTS 'app_{banco}'@'localhost' IDENTIFIED BY 'OUTRA_SENHA_FORTE';\n"
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_ident(banco)}.* TO 'app_{banco}'@'localhost';")
        for u in dados["usuarios"]:
            if not u["usuario"]:
                add(categoria="Segurança", severidade="Alta", objeto="servidor",
                    problema=f"Existe usuário anônimo (sem nome) em '{u['host']}'.",
                    impacto="Qualquer pessoa consegue se conectar sem usuário.",
                    previsao="Acesso indevido ao banco por qualquer programa da rede.",
                    onde_agir="Configuração do servidor", como_corrigir="Remova o usuário anônimo.",
                    sql=f"DROP USER ''@'{u['host']}';")
            if u["host"] == "%" and u["usuario"]:
                add(categoria="Segurança", severidade="Média", objeto="servidor",
                    problema=f"O usuário '{u['usuario']}' aceita conexão de qualquer endereço ('%').",
                    impacto="Se a porta 3306 ficar exposta, tentativas de invasão podem vir de qualquer lugar.",
                    previsao="Ataques de força bruta na senha do banco.",
                    onde_agir="Configuração do servidor",
                    como_corrigir="Restrinja o host do usuário a 'localhost' ou ao IP do servidor da aplicação.")
    else:
        add(categoria="Segurança", severidade="Info", objeto="servidor",
            problema="O usuário usado na auditoria não pode ler a lista de usuários (mysql.user).",
            impacto="As verificações de senha dos usuários do banco não foram feitas.", previsao="-",
            onde_agir="—", como_corrigir="Rode a auditoria com um usuário administrador para checar isso.")

    # ------------------------------------------------------------ tabelas
    for nome, t in tabelas.items():
        cols = cols_por_tab.get(nome, [])
        nomes_cols = {c["nome"] for c in cols}
        idx = idx_por_tab.get(nome, {})
        tid = _ident(nome)

        if "PRIMARY" not in idx:
            pk_sql = (f"ALTER TABLE {tid} ADD COLUMN id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST;"
                      if "id" not in nomes_cols else f"ALTER TABLE {tid} ADD PRIMARY KEY (`id`);")
            add(categoria="Estrutura", severidade="Alta", objeto=nome,
                problema="Tabela sem chave primária (PRIMARY KEY).",
                impacto="Não há como identificar um registro com segurança; atualizações podem atingir linhas erradas.",
                previsao="Registros duplicados, lentidão em UPDATE/DELETE e problemas de replicação/backup.",
                onde_agir="Banco de dados", como_corrigir="Crie uma chave primária (normalmente uma coluna id).",
                sql=pk_sql, aplicavel=True)

        if (t["engine"] or "").lower() == "myisam":
            add(categoria="Estrutura", severidade="Média", objeto=nome,
                problema="Tabela usa o engine MyISAM.",
                impacto="MyISAM não tem transações nem chaves estrangeiras e trava a tabela inteira a cada escrita.",
                previsao="Tabela corrompida após queda de energia e lentidão com vários usuários ao mesmo tempo.",
                onde_agir="Banco de dados", como_corrigir="Converta para InnoDB.",
                sql=f"ALTER TABLE {tid} ENGINE=InnoDB;", aplicavel=True)

        coll = (t["collation"] or "").lower()
        if coll and not coll.startswith("utf8mb4"):
            add(categoria="Tipos de dados", severidade="Média", objeto=nome,
                problema=f"Tabela com collation {t['collation']} (não é utf8mb4).",
                impacto="Não guarda emojis e alguns caracteres; mistura de charsets causa erros em JOINs.",
                previsao="Erro 'Incorrect string value' ou textos com '???' quando entrarem caracteres especiais.",
                onde_agir="Banco de dados", como_corrigir="Converta a tabela para utf8mb4.",
                sql=f"ALTER TABLE {tid} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;", aplicavel=True)

        if cols and not (nomes_cols & {"criado_em", "created_at", "data_cadastro", "dt_cadastro", "data_criacao"}):
            add(categoria="Estrutura", severidade="Baixa", objeto=nome,
                problema="Tabela sem coluna de data de criação (auditoria).",
                impacto="Não dá para saber quando cada registro entrou — atrapalha investigar problemas e relatórios.",
                previsao="Em um incidente, não será possível descobrir desde quando os dados estão errados.",
                onde_agir="Banco de dados",
                como_corrigir="Adicione criado_em com valor automático (não quebra o código que já existe).",
                sql=f"ALTER TABLE {tid} ADD COLUMN criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;", aplicavel=True)

        # índices redundantes: um índice que é prefixo de outro
        lista_idx = [(n, i["colunas"]) for n, i in idx.items() if n != "PRIMARY"]
        for n1, c1 in lista_idx:
            for n2, c2 in lista_idx:
                if n1 != n2 and len(c1) < len(c2) and c2[:len(c1)] == c1 and not idx[n1]["unico"]:
                    add(categoria="Desempenho", severidade="Baixa", objeto=nome,
                        problema=f"Índice '{n1}' ({', '.join(c1)}) é redundante — já coberto por '{n2}'.",
                        impacto="Índices extras deixam INSERT/UPDATE mais lentos e ocupam espaço.",
                        previsao="Escritas mais lentas conforme a tabela cresce.", onde_agir="Banco de dados",
                        como_corrigir="Remova o índice redundante.",
                        sql=f"ALTER TABLE {tid} DROP INDEX {_ident(n1)};", aplicavel=True)

        # AUTO_INCREMENT perto do limite
        for c in cols:
            if "auto_increment" in (c["extra"] or "") and t["auto_inc"]:
                limites = LIMITES_INT_UNSIGNED if "unsigned" in c["tipo_completo"] else LIMITES_INT
                limite = limites.get(c["tipo"])
                if limite:
                    uso = t["auto_inc"] / limite
                    if uso > 0.5:
                        add(categoria="Futuro", severidade="Crítica" if uso > 0.8 else "Alta", objeto=f"{nome}.{c['nome']}",
                            problema=f"AUTO_INCREMENT já usou {uso:.0%} do limite do tipo {c['tipo_completo']}.",
                            impacto="Quando chegar ao limite, nenhum registro novo poderá ser inserido.",
                            previsao="Sistema para de cadastrar (erro 'Duplicate entry' / 'Out of range').",
                            onde_agir="Banco de dados",
                            como_corrigir="Aumente o tipo da coluna para BIGINT UNSIGNED.",
                            sql=f"ALTER TABLE {tid} MODIFY {_ident(c['nome'])} BIGINT UNSIGNED NOT NULL AUTO_INCREMENT;",
                            aplicavel=True)

        # ------------------------------------------------------------ colunas
        for c in cols:
            cn, tipo = c["nome"], (c["tipo"] or "").lower()
            ref = f"{nome}.{cn}"
            cid = _ident(cn)

            if RE_DINHEIRO.search(cn) and tipo in ("float", "double", "real"):
                add(categoria="Tipos de dados", severidade="Alta", objeto=ref,
                    problema=f"Valor em dinheiro guardado como {tipo.upper()}.",
                    impacto="FLOAT/DOUBLE são aproximados: 0,1 + 0,2 vira 0,30000000000000004.",
                    previsao="Centavos sumindo ou sobrando em totais, troco e relatórios financeiros.",
                    onde_agir="Banco de dados", como_corrigir="Use DECIMAL(12,2) para valores monetários.",
                    sql=f"ALTER TABLE {tid} MODIFY {cid} DECIMAL(12,2) {'NULL' if c['nulo'] == 'YES' else 'NOT NULL'};",
                    aplicavel=True)

            if RE_DATA.search(cn) and tipo in ("varchar", "char", "text", "tinytext"):
                add(categoria="Tipos de dados", severidade="Média", objeto=ref,
                    problema=f"Data guardada como texto ({c['tipo_completo']}).",
                    impacto="O banco não valida a data e não consegue ordenar/filtrar por período corretamente.",
                    previsao="Datas inválidas ('31/02/2025'), formatos misturados e relatórios por mês errados.",
                    onde_agir="Banco de dados + código da aplicação",
                    como_corrigir="Converta para DATE ou DATETIME depois de padronizar os valores existentes "
                                  "(teste em uma cópia primeiro — valores fora do padrão viram NULL).",
                    sql=f"-- revise os valores antes!\nALTER TABLE {tid} MODIFY {cid} DATETIME NULL;")

            if RE_SENHA.match(cn):
                tam = c["tamanho"] or 0
                try:
                    r = _q(con, f"SELECT COUNT(*) total, SUM({cid} LIKE '$2y$%%' OR {cid} LIKE '$2a$%%' OR {cid} LIKE '$2b$%%' "
                                f"OR {cid} LIKE '$argon2%%') hash_forte, SUM(CHAR_LENGTH({cid})=32 AND {cid} REGEXP '^[0-9a-f]+$') md5 "
                                f"FROM {_ident(banco)}.{tid}")[0]
                except Exception:
                    r = {"total": 0, "hash_forte": 0, "md5": 0}
                total, forte, md5 = int(r["total"] or 0), int(r["hash_forte"] or 0), int(r["md5"] or 0)
                if total and forte < total:
                    fracos = total - forte
                    add(categoria="Segurança", severidade="Crítica", objeto=ref,
                        problema=f"{fracos} de {total} senha(s) sem hash seguro"
                                 + (f" ({md5} parecem MD5)" if md5 else " (possivelmente em texto puro)") + ".",
                        impacto="Se o banco vazar, as senhas dos usuários ficam expostas (e muitos repetem a senha em outros sites).",
                        previsao="Vazamento de contas e problemas com a LGPD.",
                        onde_agir="Código da aplicação + banco de dados",
                        como_corrigir="No PHP use password_hash() ao salvar e password_verify() no login; peça troca de "
                                      "senha aos usuários antigos. A coluna precisa ter VARCHAR(255).",
                        sql=f"ALTER TABLE {tid} MODIFY {cid} VARCHAR(255) NOT NULL;" if tam < 255 else "")
                elif tam and tam < 60:
                    add(categoria="Segurança", severidade="Alta", objeto=ref,
                        problema=f"Coluna de senha muito curta ({c['tipo_completo']}) para um hash moderno.",
                        impacto="Não cabe um hash bcrypt/argon2 (60+ caracteres).",
                        previsao="A aplicação pode acabar salvando senhas fracas ou cortadas.",
                        onde_agir="Banco de dados", como_corrigir="Aumente para VARCHAR(255).",
                        sql=f"ALTER TABLE {tid} MODIFY {cid} VARCHAR(255) NOT NULL;", aplicavel=True)

            if RE_UNICO.match(cn) and "PRIMARY" not in [k for k, i in idx.items() if i["colunas"] == [cn]] and not unica(nome, cn):
                try:
                    dup = _q(con, f"SELECT COUNT(*) n FROM (SELECT {cid} FROM {_ident(banco)}.{tid} WHERE {cid} IS NOT NULL "
                                  f"AND {cid}<>'' GROUP BY {cid} HAVING COUNT(*)>1) d")[0]["n"]
                except Exception:
                    dup = 0
                add(categoria="Integridade", severidade="Alta" if dup else "Média", objeto=ref,
                    problema=f"'{cn}' não tem índice UNIQUE" + (f" e já existem {dup} valor(es) duplicado(s)." if dup else "."),
                    impacto="O banco aceita dois cadastros com o mesmo valor (ex.: mesmo CPF ou e-mail).",
                    previsao="Clientes duplicados, login ambíguo e relatórios com números inflados.",
                    onde_agir="Banco de dados" + (" (limpe as duplicatas antes)" if dup else ""),
                    como_corrigir="Crie um índice único" + (" depois de resolver as duplicatas." if dup else "."),
                    sql=f"ALTER TABLE {tid} ADD UNIQUE INDEX {_ident('uk_' + cn)} ({cid});", aplicavel=not dup)

            if RE_OBRIGATORIO.match(cn) and c["nulo"] == "YES":
                add(categoria="Integridade", severidade="Baixa", objeto=ref,
                    problema=f"'{cn}' aceita NULL, mas parece ser um campo obrigatório.",
                    impacto="Registros podem ficar sem informação essencial.",
                    previsao="Telas e relatórios quebrando ou mostrando campos vazios.",
                    onde_agir="Banco de dados + validação na aplicação",
                    como_corrigir="Preencha os vazios e torne a coluna NOT NULL.",
                    sql=f"-- preencha os NULL antes\nALTER TABLE {tid} MODIFY {cid} {c['tipo_completo']} NOT NULL;")

            if tipo in ("blob", "mediumblob", "longblob") and re.search(r"(foto|imagem|image|arquivo|anexo|logo)", cn, re.I):
                add(categoria="Desempenho", severidade="Baixa", objeto=ref,
                    problema="Arquivos/imagens guardados dentro do banco (BLOB).",
                    impacto="O banco e os backups ficam enormes e lentos.",
                    previsao="Backups demorando horas e consultas lentas.",
                    onde_agir="Código da aplicação",
                    como_corrigir="Salve o arquivo em disco/serviço de arquivos e guarde só o caminho no banco.")

            # possíveis chaves estrangeiras (colunas *_id / id_*)
            alvo = None
            mfk = re.match(r"^(id_(\w+)|(\w+)_id)$", cn, re.I)
            if mfk and cn != "id":
                base = (mfk.group(2) or mfk.group(3)).lower()
                for cand in (base, base + "s", base + "es", base[:-1] if base.endswith("s") else None):
                    if cand and cand in tabelas and cand != nome:
                        alvo = cand
                        break
            if mfk and cn != "id" and not indexada(nome, cn):
                add(categoria="Desempenho", severidade="Alta" if (t["linhas"] or 0) > 10000 else "Média", objeto=ref,
                    problema=f"Coluna de relacionamento '{cn}' sem índice.",
                    impacto="Todo JOIN ou filtro por essa coluna lê a tabela inteira.",
                    previsao="O sistema fica cada vez mais lento conforme a tabela cresce (telas de listagem e relatórios).",
                    onde_agir="Banco de dados", como_corrigir="Crie um índice na coluna.",
                    sql=f"ALTER TABLE {tid} ADD INDEX {_ident('idx_' + cn)} ({cid});", aplicavel=True)
            if alvo and (nome, cn) not in fk_cols:
                try:
                    orfaos = _q(con, f"SELECT COUNT(*) n FROM {_ident(banco)}.{tid} f LEFT JOIN {_ident(banco)}.{_ident(alvo)} p "
                                     f"ON p.id = f.{cid} WHERE f.{cid} IS NOT NULL AND p.id IS NULL")[0]["n"] \
                        if "id" in {x["nome"] for x in cols_por_tab.get(alvo, [])} else 0
                except Exception:
                    orfaos = 0
                motor_ok = (t["engine"] or "").lower() == "innodb" and (tabelas[alvo]["engine"] or "").lower() == "innodb"
                add(categoria="Integridade", severidade="Alta" if orfaos else "Média", objeto=ref,
                    problema=f"'{cn}' aponta para '{alvo}', mas não há chave estrangeira"
                             + (f" — já existem {orfaos} registro(s) órfão(s)." if orfaos else "."),
                    impacto="O banco permite apagar o registro pai e deixar filhos apontando para o nada.",
                    previsao="Telas com erro ao abrir itens sem dono e totais que não batem.",
                    onde_agir="Banco de dados" + (" (corrija os órfãos antes)" if orfaos else ""),
                    como_corrigir="Crie a FOREIGN KEY" + ("" if motor_ok else " (converta as tabelas para InnoDB antes)") + ".",
                    sql=f"ALTER TABLE {tid} ADD CONSTRAINT {_ident('fk_' + nome + '_' + cn)} FOREIGN KEY ({cid}) "
                        f"REFERENCES {_ident(alvo)} (`id`) ON UPDATE CASCADE ON DELETE RESTRICT;",
                    aplicavel=motor_ok and not orfaos)

    # FKs sem regra de exclusão pensada
    for f in dados["fks"]:
        if (f["ao_excluir"] or "") == "CASCADE":
            add(categoria="Integridade", severidade="Info", objeto=f"{f['tabela']}.{f['coluna']}",
                problema=f"A FK para '{f['ref_tabela']}' apaga em cascata (ON DELETE CASCADE).",
                impacto="Excluir um registro pai apaga todos os filhos automaticamente.",
                previsao="Uma exclusão acidental pode apagar muito mais do que o esperado (ex.: vendas de um cliente).",
                onde_agir="Banco de dados", como_corrigir="Confirme se é intencional; para dados históricos prefira RESTRICT.")

    if not tabelas:
        add(categoria="Estrutura", severidade="Info", objeto=banco, problema="O banco não tem tabelas.",
            impacto="-", previsao="-", onde_agir="—", como_corrigir="Nada a fazer.")
    return ach


# ====================================================================== previsões de crescimento
def prever(dados: dict) -> list[dict]:
    """Estimativa simples de crescimento a partir da data de criação de cada tabela."""
    saida = []
    agora = datetime.now()
    for t in dados["tabelas"]:
        criada, linhas = t["criada"], int(t["linhas"] or 0)
        tamanho_mb = ((t["dados"] or 0) + (t["indices"] or 0)) / 1024 / 1024
        if not criada or linhas == 0:
            continue
        dias = max((agora - criada).days, 1)
        por_dia = linhas / dias
        saida.append({"tabela": t["nome"], "linhas": linhas, "tamanho_mb": round(tamanho_mb, 2),
                      "linhas_por_dia": round(por_dia, 1), "linhas_em_1_ano": int(linhas + por_dia * 365),
                      "mb_em_1_ano": round(tamanho_mb * (1 + por_dia * 365 / linhas), 1)})
    return sorted(saida, key=lambda x: -x["linhas_em_1_ano"])


# ====================================================================== auditoria completa
def auditar(banco: str, host="127.0.0.1", porta=3306, usuario="root", senha="", usar_ia=False, log=print) -> Auditoria:
    con = conectar(host, porta, usuario, senha)
    try:
        if banco not in listar_bancos(con):
            raise ErroBanco(f"O banco '{banco}' não existe ou o usuário não tem acesso.")
        log(f"Lendo a estrutura de '{banco}' em {host}:{porta}...")
        dados = coletar(con, banco)
        achados = analisar(con, banco, dados)
    finally:
        con.close()

    cols_por_tab: dict[str, list] = {}
    for c in dados["colunas"]:
        cols_por_tab.setdefault(c["tabela"], []).append(c)
    tabelas = [{
        "nome": t["nome"], "engine": t["engine"], "linhas": int(t["linhas"] or 0),
        "tamanho_kb": round(((t["dados"] or 0) + (t["indices"] or 0)) / 1024, 1), "collation": t["collation"],
        "colunas": [{"nome": c["nome"], "tipo": c["tipo_completo"], "nulo": c["nulo"] == "YES",
                     "chave": c["chave"], "extra": c["extra"]} for c in cols_por_tab.get(t["nome"], [])],
    } for t in dados["tabelas"]]

    pontos = sum(SEV_PESO.get(a.severidade, 0) for a in achados)
    contagem = {}
    for a in achados:
        contagem[a.severidade] = contagem.get(a.severidade, 0) + 1
    aud = Auditoria(
        host=f"{host}:{porta}", banco=banco, versao=dados["variaveis"].get("version", "?"),
        quando=datetime.now().strftime("%d/%m/%Y %H:%M"), tabelas=tabelas,
        relacoes=[{"de": f["tabela"], "coluna": f["coluna"], "para": f["ref_tabela"]} for f in dados["fks"]],
        achados=[asdict(a) for a in achados], previsoes=prever(dados),
        # Nota decresce suavemente com a soma dos pesos (nunca chega a zero só por muitos itens leves)
        resumo={"nota": round(100 * math.exp(-pontos / 120)), "tabelas": len(tabelas), "achados": len(achados),
                "por_severidade": contagem, "aplicaveis": sum(a.aplicavel for a in achados),
                "linhas": sum(t["linhas"] for t in tabelas),
                "tamanho_mb": round(sum(t["tamanho_kb"] for t in tabelas) / 1024, 2)},
    )
    log(f"{len(achados)} achado(s) — nota de saúde {aud.resumo['nota']}/100")
    if usar_ia:
        _analise_ia(aud, log)
    return aud


def _analise_ia(aud: Auditoria, log):
    """Envia SÓ a estrutura (nomes de tabelas/colunas/tipos e os achados) para a IA — nunca os dados."""
    chave = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not chave:
        aud.avisos.append("Sem chave de IA: análise extra da IA não executada.")
        return
    try:
        from google import genai
        from google.genai import types
        estrutura = {t["nome"]: [f"{c['nome']} {c['tipo']}{' NULL' if c['nulo'] else ''}" for c in t["colunas"]]
                     for t in aud.tabelas}
        prompt = ("Você é um DBA sênior. Analise a ESTRUTURA deste banco MySQL/MariaDB (não há dados) e os achados "
                  "automáticos. Aponte riscos FUTUROS que as regras automáticas não pegaram (modelagem, normalização, "
                  "escalabilidade, consultas que tendem a ficar lentas, regras de negócio frágeis). Responda só JSON: "
                  '{"sugestoes":[{"titulo":"","descricao":"","onde_agir":"Banco de dados|Código da aplicação|Servidor",'
                  '"prioridade":"Alta|Média|Baixa"}]} com 3 a 6 itens, em português do Brasil.\n\n'
                  f"Banco: {aud.banco}\nEstrutura: {json.dumps(estrutura, ensure_ascii=False)}\n"
                  f"Achados: {json.dumps([a['problema'] for a in aud.achados][:40], ensure_ascii=False)}")
        cliente = genai.Client(api_key=chave, http_options=types.HttpOptions(timeout=90_000))
        modelo = os.getenv("SENTINELA_MODELO_IA", "gemini-3.5-flash")
        log(f"🤖 Pedindo análise da estrutura à IA ({modelo})...")
        r = cliente.models.generate_content(model=modelo, contents=prompt,
                                            config=types.GenerateContentConfig(response_mime_type="application/json"))
        aud.sugestoes_ia = json.loads(r.text).get("sugestoes", [])
    except Exception as e:
        aud.avisos.append(f"Análise da IA falhou e foi ignorada: {str(e)[:150]}")


# ====================================================================== script SQL e aplicação
def script_sql(aud: Auditoria) -> str:
    linhas = [f"-- Correções sugeridas pelo Sentinela QA para o banco `{aud.banco}` ({aud.quando})",
              "-- FAÇA BACKUP ANTES (o Sentinela faz sozinho quando você aplica pelo painel).",
              "-- Revise cada comando: alguns exigem limpeza de dados antes (indicado nos comentários).", "",
              f"USE {_ident(aud.banco)};", ""]
    for a in aud.achados:
        if a["sql"]:
            linhas += [f"-- [{a['id']}] {a['severidade']} · {a['objeto']}: {a['problema']}",
                       a["sql"] if a["aplicavel"] else "-- " + a["sql"].replace("\n", "\n-- "), ""]
    return "\n".join(linhas)


def achar_mysqldump() -> str | None:
    for c in (os.getenv("SENTINELA_MYSQLDUMP"), shutil.which("mysqldump"), r"C:\xampp\mysql\bin\mysqldump.exe"):
        if c and os.path.isfile(c):
            return c
    return None


def fazer_backup(banco, pasta, host="127.0.0.1", porta=3306, usuario="root", senha="") -> str:
    exe = achar_mysqldump()
    if not exe:
        raise ErroBanco("mysqldump não encontrado (configure SENTINELA_MYSQLDUMP no .env).")
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"{banco}_{datetime.now():%Y%m%d_%H%M%S}.sql")
    cmd = [exe, f"--host={host}", f"--port={porta}", f"--user={usuario}", "--single-transaction",
           "--routines", "--triggers", "--default-character-set=utf8mb4", banco]
    env = dict(os.environ, MYSQL_PWD=senha) if senha else None   # senha fora da linha de comando
    with open(destino, "wb") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env, timeout=600)
    if r.returncode != 0:
        os.remove(destino)
        raise ErroBanco(f"Backup falhou: {r.stderr.decode(errors='replace')[:200]}")
    return destino


def aplicar(aud: Auditoria, ids: list[str], pasta_backup: str, host="127.0.0.1", porta=3306,
            usuario="root", senha="", log=print) -> dict:
    """Aplica as correções escolhidas. Só as marcadas como 'aplicáveis'; backup antes, sempre."""
    escolhidos = [a for a in aud.achados if a["id"] in ids]
    nao = [a["id"] for a in escolhidos if not a["aplicavel"]]
    if nao:
        raise ErroBanco(f"Estas correções precisam de revisão manual e não são aplicadas automaticamente: {', '.join(nao)}")
    if not escolhidos:
        raise ErroBanco("Nenhuma correção escolhida.")
    backup = fazer_backup(aud.banco, pasta_backup, host, porta, usuario, senha)
    log(f"Backup salvo em {backup}")
    con = conectar(host, porta, usuario, senha, aud.banco)
    resultados = []
    try:
        for a in escolhidos:
            try:
                with con.cursor() as c:
                    for comando in [s.strip() for s in a["sql"].split(";\n") if s.strip() and not s.strip().startswith("--")]:
                        c.execute(comando.rstrip(";"))
                resultados.append({"id": a["id"], "ok": True, "msg": "aplicado"})
                log(f"  ✔ {a['id']} {a['objeto']}")
            except Exception as e:
                resultados.append({"id": a["id"], "ok": False, "msg": str(e)[:200]})
                log(f"  ✘ {a['id']} {a['objeto']}: {e}")
    finally:
        con.close()
    return {"backup": backup, "resultados": resultados}


def restaurar(backup: str, banco: str, host="127.0.0.1", porta=3306, usuario="root", senha=""):
    exe = (achar_mysqldump() or "").replace("mysqldump", "mysql")
    if not os.path.isfile(exe):
        raise ErroBanco("Cliente mysql não encontrado para restaurar o backup.")
    env = dict(os.environ, MYSQL_PWD=senha) if senha else None
    with open(backup, "rb") as f:
        r = subprocess.run([exe, f"--host={host}", f"--port={porta}", f"--user={usuario}", banco],
                           stdin=f, stderr=subprocess.PIPE, env=env, timeout=600)
    if r.returncode != 0:
        raise ErroBanco(f"Restauração falhou: {r.stderr.decode(errors='replace')[:200]}")


# ====================================================================== relatório
def gerar_relatorio(aud: Auditoria, pasta: str) -> dict:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from sentinela import __version__
    from sentinela.relatorio import pasta_templates
    os.makedirs(pasta, exist_ok=True)
    dados = asdict(aud)
    with open(os.path.join(pasta, "auditoria.json"), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(pasta, "correcoes_sugeridas.sql"), "w", encoding="utf-8") as f:
        f.write(script_sql(aud))
    env = Environment(loader=FileSystemLoader(pasta_templates()), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("auditoria_banco.html.j2").render(a=dados, versao_robo=__version__, sql=script_sql(aud),
                                                              mermaid=diagrama_mermaid(aud))
    caminho = os.path.join(pasta, "auditoria.html")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return {"html": caminho, "json": os.path.join(pasta, "auditoria.json"),
            "sql": os.path.join(pasta, "correcoes_sugeridas.sql")}


def diagrama_mermaid(aud: Auditoria) -> str:
    """Diagrama entidade-relacionamento em Mermaid (renderizado no relatório)."""
    def limpo(texto):
        return re.sub(r"\W", "_", str(texto))

    linhas = ["erDiagram"]
    for t in aud.tabelas[:40]:
        linhas.append(f"  {limpo(t['nome'])} {{")
        for c in t["colunas"][:14]:
            tipo = re.sub(r"[^A-Za-z0-9]", "_", c["tipo"].split("(")[0])
            chave = " PK" if c["chave"] == "PRI" else (" FK" if c["chave"] == "MUL" else "")
            linhas.append(f"    {tipo} {limpo(c['nome'])}{chave}")
        linhas.append("  }")
    for r in aud.relacoes:
        linhas.append(f"  {limpo(r['para'])} ||--o{{ {limpo(r['de'])} : \"{limpo(r['coluna'])}\"")
    # Relacionamentos que existem só no código (sem FK): linha tracejada
    for a in aud.achados:
        m = re.match(r"'(\w+)' aponta para '(\w+)'", a.get("problema", ""))
        if m and "." in a.get("objeto", ""):
            tabela = a["objeto"].split(".")[0]
            linhas.append(f"  {limpo(m[2])} ||..o{{ {limpo(tabela)} : \"{limpo(m[1])} sem FK\"")
    return "\n".join(linhas)
