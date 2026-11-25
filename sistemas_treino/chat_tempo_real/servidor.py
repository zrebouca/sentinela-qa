"""Chat de treino em tempo real, só com a biblioteca padrão do Python.

Como funciona: cada tela aberta escuta /eventos (Server-Sent Events) e manda mensagens por POST /mensagens.
O servidor numera as mensagens: se a tela cai, o navegador reconecta com Last-Event-ID e recebe o que perdeu.

Rodar: python sistemas_treino/chat_tempo_real/servidor.py   (abre em http://127.0.0.1:8790)
"""
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PASTA = Path(__file__).parent


class Chat:
    def __init__(self):
        self.mensagens = []
        self.novidade = threading.Condition()

    def publicar(self, autor, texto):
        with self.novidade:
            msg = {"id": len(self.mensagens) + 1, "autor": autor, "texto": texto}
            self.mensagens.append(msg)
            self.novidade.notify_all()
            return msg


class Tela(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(PASTA), **kw)

    def log_message(self, *args):
        pass  # sem poluir o terminal dos testes

    def _json(self, status, dados):
        corpo = json.dumps(dados).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path == "/mensagens":
            return self._json(200, self.server.chat.mensagens)
        if self.path != "/eventos":
            return super().do_GET()
        if self.server.fora_do_ar:
            self.close_connection = True  # derruba sem responder, como uma queda de rede
            return
        chat = self.server.chat
        ultimo = int(self.headers.get("Last-Event-ID") or 0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 300\n\n")
            self.wfile.flush()
            while not (self.server.encerrando or self.server.fora_do_ar):
                with chat.novidade:
                    chat.novidade.wait_for(lambda: len(chat.mensagens) > ultimo, timeout=1)
                    novas = chat.mensagens[ultimo:]
                if not novas:
                    self.wfile.write(b": vivo\n\n")
                for m in novas:
                    self.wfile.write(f"id: {m['id']}\ndata: {json.dumps(m)}\n\n".encode())
                    ultimo = m["id"]
                self.wfile.flush()
        except OSError:
            pass  # a tela fechou

    def do_POST(self):
        if self.path != "/mensagens":
            return self._json(404, {"erro": "rota não existe"})
        try:
            dados = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            autor, texto = str(dados["autor"]).strip(), str(dados["texto"]).strip()
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"erro": "JSON inválido"})
        if not autor or not texto or len(texto) > 200:
            return self._json(422, {"erro": "autor e texto são obrigatórios (até 200 caracteres)"})
        self._json(201, self.server.chat.publicar(autor, texto))


def criar(porta=0):
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Tela)
    servidor.daemon_threads = True
    servidor.chat = Chat()
    servidor.encerrando = False
    servidor.fora_do_ar = False
    return servidor


if __name__ == "__main__":
    s = criar(int(sys.argv[1]) if len(sys.argv) > 1 else 8790)
    print(f"Chat de treino em http://127.0.0.1:{s.server_port}")
    s.serve_forever()
