"""Exceções compartilhadas entre os módulos (evita importação circular)."""


class ErroPasso(Exception):
    """Falha de um passo, com mensagem em português para o relatório."""
