"""
Comandos de banco de dados dentro dos roteiros (MySQL/MariaDB).

Servem para conferir se uma ação na tela/API realmente gravou no banco
(teste "ponta a ponta" de verdade). Configure a conexão no roteiro:

    banco:
      host: 127.0.0.1
      usuario: root
      senha: "{env.SENTINELA_DB_SENHA|}"
      nome: sentinela_loja

Comandos:
    - verificar_banco: { sql: "SELECT COUNT(*) FROM produtos WHERE nome='{dados.produto}'", valor: 1 }
    - verificar_banco: { sql: "SELECT id FROM usuarios WHERE email='x@y.com'", existe: false }
    - verificar_banco: { sql: "SELECT * FROM produtos", linhas: 3 }
    - consultar_banco: { sql: "SELECT MAX(id) FROM produtos", guardar_como: ultimo_id }
    - preparar_banco: "DELETE FROM produtos WHERE nome LIKE 'TESTE%'"     (único que pode alterar dados)

verificar_banco e consultar_banco só aceitam leitura (SELECT/SHOW/DESCRIBE/EXPLAIN).
"""

import re

from sentinela.erros import ErroPasso

_LEITURA = re.compile(r"^\s*(select|show|describe|desc|explain|with)\b", re.I)


class ComandosBanco:
    _conexao_banco = None

    def _banco(self):
        if self._conexao_banco is not None:
            return self._conexao_banco
        cfg = getattr(self.roteiro, "banco", None)
        if not cfg:
            raise ErroPasso("O roteiro não tem a seção 'banco:' com os dados de conexão.")
        cfg = self.resolver(cfg)
        try:
            from sentinela.banco_auditor import ErroBanco, conectar
            self._conexao_banco = conectar(cfg.get("host", "127.0.0.1"), cfg.get("porta", 3306),
                                           cfg.get("usuario", "root"), str(cfg.get("senha", "") or ""), cfg.get("nome"))
        except ImportError:
            raise ErroPasso("Instale a biblioteca PyMySQL (pip install pymysql) para usar comandos de banco.")
        except ErroBanco as e:
            raise ErroPasso(str(e))
        return self._conexao_banco

    def _consulta(self, sql: str, so_leitura=True):
        if so_leitura and not _LEITURA.match(sql):
            raise ErroPasso("Este comando só aceita consultas de leitura (SELECT). Para alterar dados use 'preparar_banco'.")
        try:
            with self._banco().cursor() as c:
                c.execute(sql)
                return c.fetchall() if c.description else []
        except ErroPasso:
            raise
        except Exception as e:
            raise ErroPasso(f"Erro no SQL: {str(e)[:200]}")

    def cmd_verificar_banco(self, args):
        sql = str(args["sql"] if isinstance(args, dict) else args)
        linhas = self._consulta(sql)
        primeiro = next(iter(linhas[0].values())) if linhas and linhas[0] else None
        if isinstance(args, dict) and "linhas" in args:
            if len(linhas) != int(args["linhas"]):
                raise ErroPasso(f"A consulta trouxe {len(linhas)} linha(s), esperado {args['linhas']}")
            return f"Banco: {len(linhas)} linha(s) (correto)"
        if isinstance(args, dict) and "existe" in args:
            achou = bool(linhas)
            if achou != bool(args["existe"]):
                raise ErroPasso("O registro existe no banco, mas não deveria" if achou else "O registro não foi encontrado no banco")
            return "Banco: registro " + ("encontrado" if achou else "ausente (correto)")
        if isinstance(args, dict) and "valor" in args:
            if str(primeiro).strip().lower() != str(args["valor"]).strip().lower():
                raise ErroPasso(f"Banco retornou {primeiro!r}, esperado {args['valor']!r}")
            return f"Banco: valor {primeiro!r} (correto)"
        if not linhas:
            raise ErroPasso("A consulta não trouxe nenhuma linha")
        return f"Banco: {len(linhas)} linha(s)"

    def cmd_consultar_banco(self, args):
        sql = str(args["sql"] if isinstance(args, dict) else args)
        linhas = self._consulta(sql)
        if isinstance(args, dict) and args.get("guardar_como"):
            valor = next(iter(linhas[0].values())) if linhas else None
            self.dados[str(args["guardar_como"])] = valor
            return f"Guardado {{dados.{args['guardar_como']}}} = {valor!r}"
        return f"Consulta trouxe {len(linhas)} linha(s)"

    def cmd_preparar_banco(self, args):
        sql = str(args["sql"] if isinstance(args, dict) else args)
        with self._banco().cursor() as c:
            try:
                n = c.execute(sql)
            except Exception as e:
                raise ErroPasso(f"Erro no SQL: {str(e)[:200]}")
        return f"Banco preparado ({n} linha(s) afetada(s))"

    def fechar_banco(self):
        if self._conexao_banco is not None:
            try:
                self._conexao_banco.close()
            except Exception:
                pass
            self._conexao_banco = None
