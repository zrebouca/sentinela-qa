"""Chat, chamada, push, segundo plano e aparelhos diferentes, no chat de treino do Sentinela.

Limite: os aparelhos são EMULADOS no Chrome (tela, toque e user agent). Não substitui
teste em Android e iPhone de verdade nem em app nativo.
"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).parents[2] / "sistemas_treino" / "chat_tempo_real"))
import servidor as chat_treino  # noqa: E402


@pytest.fixture
def servidor():
    s = chat_treino.criar()
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.encerrando = True
    s.shutdown()
    s.server_close()


@pytest.fixture
def site(servidor):
    return f"http://127.0.0.1:{servidor.server_port}"


@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def navegador(pw):
    args = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]  # câmera e microfone de mentira
    try:
        b = pw.chromium.launch(channel="chrome", args=args)
    except Exception:
        b = pw.chromium.launch(channel="msedge", args=args)
    yield b
    b.close()


@pytest.fixture
def abrir(navegador, site):
    contextos = []

    def _abrir(usuario, permissoes=(), **opcoes):
        ctx = navegador.new_context(**opcoes)
        contextos.append(ctx)
        if permissoes:
            ctx.grant_permissions(list(permissoes), origin=site)
        pagina = ctx.new_page()
        pagina.goto(f"{site}/?usuario={usuario}")
        expect(pagina.locator("#estado")).to_have_text("online")
        return pagina

    yield _abrir
    for c in contextos:
        c.close()


def enviar(pagina, texto):
    pagina.locator("#texto").fill(texto)
    pagina.locator("#enviar").click()


def esperar(pagina, condicao, segundos=10):
    """Repete a condição até dar verdadeiro (sem sleep fixo)."""
    fim = time.time() + segundos
    while time.time() < fim:
        if condicao():
            return
        pagina.wait_for_timeout(100)
    raise AssertionError(f"Condição não atendida em {segundos}s")


# ---------- chat em tempo real ----------
def test_ct01_mensagem_chega_na_outra_tela(abrir):
    ana, bia = abrir("Ana"), abrir("Bia")
    inicio = time.perf_counter()
    enviar(ana, "Oi, Bia!")
    expect(bia.locator("#lista li")).to_have_text(["Ana: Oi, Bia!"])
    assert time.perf_counter() - inicio < 2


def test_ct02_ordem_e_sem_duplicar(abrir):
    ana, bia = abrir("Ana"), abrir("Bia")
    for i in range(5):
        enviar(ana, f"msg {i}")
        expect(ana.locator("#texto")).to_have_value("")
    expect(bia.locator("#lista li")).to_have_text([f"Ana: msg {i}" for i in range(5)])


def test_ct03_html_vira_texto(abrir):
    ana, bia = abrir("Ana"), abrir("Bia")
    enviar(ana, "<img src=x onerror=alert(1)>")
    expect(bia.locator("#lista li")).to_have_text(["Ana: <img src=x onerror=alert(1)>"])
    assert bia.locator("#lista img").count() == 0


@pytest.mark.parametrize("corpo, status", [
    ({"autor": "Ana", "texto": "   "}, 422),
    ({"autor": "Ana", "texto": "x" * 201}, 422),
    ({"autor": "Ana", "texto": "x" * 200}, 201),
    ({"autor": "Ana"}, 400),
])
def test_ct04_api_valida_limites(pw, site, corpo, status):
    api = pw.request.new_context(base_url=site)
    assert api.post("/mensagens", data=json.dumps(corpo)).status == status
    api.dispose()


# ---------- segundo plano e rede ----------
def test_ct05_volta_do_segundo_plano_sem_perder_nem_duplicar(abrir, servidor):
    bia = abrir("Bia")
    servidor.chat.publicar("Ana", "antes")
    expect(bia.locator("#lista li")).to_have_text(["Ana: antes"])
    servidor.fora_do_ar = True  # o sistema corta a conexão do app parado em segundo plano
    expect(bia.locator("#estado")).to_have_text("reconectando")
    servidor.chat.publicar("Ana", "durante")
    servidor.fora_do_ar = False
    expect(bia.locator("#estado")).to_have_text("online", timeout=10000)
    expect(bia.locator("#lista li")).to_have_text(["Ana: antes", "Ana: durante"])


def test_ct06_sem_internet_avisa_e_nao_perde_o_texto(abrir):
    ana = abrir("Ana")
    ana.context.set_offline(True)
    enviar(ana, "não pode se perder")
    expect(ana.locator("#estado")).to_contain_text("não enviada")
    expect(ana.locator("#texto")).to_have_value("não pode se perder")
    ana.context.set_offline(False)
    ana.locator("#enviar").click()
    expect(ana.locator("#lista li")).to_have_text(["Ana: não pode se perder"])


# ---------- push ----------
def test_ct07_push_mostra_notificacao(abrir, site):
    ana = abrir("Ana", permissoes=["notifications"])
    cdp = ana.context.new_cdp_session(ana)
    registros = []
    cdp.on("ServiceWorker.workerRegistrationUpdated", lambda e: registros.extend(e["registrations"]))
    cdp.send("ServiceWorker.enable")
    ana.locator("#avisos").click()
    expect(ana.locator("#estado-avisos")).to_have_text("notificações: granted")
    esperar(ana, lambda: registros)
    cdp.send("ServiceWorker.deliverPushMessage", {
        "origin": site, "registrationId": registros[-1]["registrationId"],
        "data": json.dumps({"titulo": "Bia", "texto": "Você viu?"})})
    ler = """async () => (await (await navigator.serviceWorker.ready).getNotifications())
             .map(n => [n.title, n.body])"""
    esperar(ana, lambda: ana.evaluate(ler) == [["Bia", "Você viu?"]])


# ---------- chamada de áudio e vídeo ----------
def test_ct08_chamada_conecta_com_audio_e_video(abrir):
    ana = abrir("Ana", permissoes=["camera", "microphone"])
    ana.locator("#ligar").click()
    expect(ana.locator("#estado-chamada")).to_have_text("connected", timeout=15000)
    ana.wait_for_function("document.getElementById('remoto').videoWidth > 0")
    recebidos = """async () => [...(await window.ligacao.b.getStats()).values()]
        .filter(s => s.type === 'inbound-rtp' && s.packetsReceived > 0).map(s => s.kind).sort()"""
    esperar(ana, lambda: ana.evaluate(recebidos) == ["audio", "video"])


def test_ct09_camera_negada_avisa_o_usuario(abrir):
    ana = abrir("Ana")
    ana.evaluate("""() => { navigator.mediaDevices.getUserMedia =
        () => Promise.reject(new DOMException('negado', 'NotAllowedError')); }""")
    ana.locator("#ligar").click()
    expect(ana.locator("#estado-chamada")).to_have_text("erro: NotAllowedError")


# ---------- aparelhos e tamanhos diferentes (emulados) ----------
@pytest.mark.parametrize("aparelho", ["Pixel 7", "Galaxy S9+", "iPhone SE", "iPhone 14", "iPad Mini"])
def test_ct10_layout_e_envio_por_aparelho(abrir, pw, aparelho):
    opcoes = {k: v for k, v in pw.devices[aparelho].items() if k != "default_browser_type"}
    ana = abrir("Ana", **opcoes)
    ana.locator("#texto").fill("toque")
    ana.locator("#enviar").tap()
    expect(ana.locator("#lista li")).to_have_text(["Ana: toque"])
    assert ana.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "rolagem lateral"
    assert ana.locator("#enviar").bounding_box()["height"] >= 44, "botão pequeno para toque"
