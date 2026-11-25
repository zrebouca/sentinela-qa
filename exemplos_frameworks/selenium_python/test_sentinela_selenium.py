"""Gerado pelo Sentinela QA a partir do roteiro web_site_treino.yaml.
Rodar: pip install -r requirements.txt && pytest -q
"""
import os
import time

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


def esperar(condicao, segundos=10):
    """Espera uma condição ficar verdadeira (sem sleep fixo)."""
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            if condicao():
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError("Condição não atendida em %ss" % segundos)


def achar(driver, por, valor):
    """Espera aparecer o primeiro elemento VISÍVEL que combina com o seletor."""
    def visivel(d):
        return next((e for e in d.find_elements(por, valor) if e.is_displayed()), False)
    return WebDriverWait(driver, 10).until(visivel)


def por_rotulo(driver, texto):
    label = achar(driver, By.XPATH, f"//label[normalize-space()='{texto}']")
    return driver.find_element(By.ID, label.get_attribute("for"))


def por_texto(driver, texto):
    """Rótulo, placeholder, botão, link ou texto — como uma pessoa procuraria."""
    for por, valor in [(By.XPATH, f"//label[normalize-space()='{texto}']"), (By.CSS_SELECTOR, f'[placeholder="{texto}"]'),
                       (By.XPATH, f"//button[normalize-space()='{texto}'] | //a[normalize-space()='{texto}']"),
                       (By.XPATH, f"//*[normalize-space(text())='{texto}']")]:
        achados = [e for e in driver.find_elements(por, valor) if e.is_displayed()]
        if achados:
            el = achados[0]
            return driver.find_element(By.ID, el.get_attribute("for")) if el.tag_name == "label" else el
    return achar(driver, By.XPATH, f"//*[contains(normalize-space(), '{texto}')]")


def esperar_texto(driver, texto):
    esperar(lambda: texto in driver.find_element(By.TAG_NAME, "body").text)


@pytest.fixture
def driver():
    opcoes = webdriver.ChromeOptions()
    opcoes.add_argument('--headless=new')
    d = webdriver.Chrome(options=opcoes)   # o Selenium Manager baixa o chromedriver sozinho
    d.set_window_size(1280, 800)
    yield d
    d.quit()

def test_ct01_login_com_usuário_válido(driver):
    """Login com usuário válido"""
    driver.get("http://127.0.0.1:8000/index.html")
    el = por_rotulo(driver, "Usuário")
    el.clear()
    el.send_keys("qa")
    el = por_rotulo(driver, "Senha")
    el.clear()
    el.send_keys(os.getenv("TREINO_SENHA", "treino123"))
    por_texto(driver, "Entrar").click()
    esperar(lambda: "painel.html" in driver.current_url)
    esperar_texto(driver, "Bem-vindo, qa!")

def test_ct02_login_com_senha_errada(driver):
    """Login com senha errada"""
    driver.get("http://127.0.0.1:8000/index.html")
    el = por_rotulo(driver, "Usuário")
    el.clear()
    el.send_keys("qa")
    el = por_rotulo(driver, "Senha")
    el.clear()
    el.send_keys("errada")
    por_rotulo(driver, "Senha").send_keys(Keys.ENTER)
    esperar_texto(driver, "Usuário ou senha inválidos.")
    esperar(lambda: "index.html" in driver.current_url)

def test_ct03_login_com_campos_vazios(driver):
    """Login com campos vazios"""
    driver.get("http://127.0.0.1:8000/index.html")
    por_texto(driver, "Entrar").click()
    esperar_texto(driver, "Preencha usuário e senha.")

def test_ct04_buscar_produto_e_carregar_ofertas(driver):
    """Buscar produto e carregar ofertas"""
    driver.get("http://127.0.0.1:8000/index.html")
    el = achar(driver, By.CSS_SELECTOR, "#usuario")
    el.clear()
    el.send_keys("qa")
    el = achar(driver, By.CSS_SELECTOR, "#senha")
    el.clear()
    el.send_keys(os.getenv("TREINO_SENHA", "treino123"))
    achar(driver, By.CSS_SELECTOR, "#entrar").click()
    el = achar(driver, By.CSS_SELECTOR, '[placeholder="' + "Buscar produto" + '"]')
    el.clear()
    el.send_keys("mochila", Keys.ENTER)
    esperar_texto(driver, "Mochila escolar")
    assert achar(driver, By.CSS_SELECTOR, "#lista li").is_displayed()
    por_texto(driver, "Carregar ofertas").click()
    esperar_texto(driver, "3 ofertas disponíveis hoje!")
    assert "Carregando..." not in driver.find_element(By.TAG_NAME, 'body').text

def test_ct05_cadastro_com_dados_válidos_faker_pt_br(driver):
    """Cadastro com dados válidos (Faker pt_BR)"""
    driver.get("http://127.0.0.1:8000/cadastro.html")
    el = por_rotulo(driver, "Nome completo")
    el.clear()
    el.send_keys("Davi Caldeira")
    el = por_rotulo(driver, "E-mail")
    el.clear()
    el.send_keys("pmonteiro@example.net")
    el = por_rotulo(driver, "CPF")
    el.clear()
    el.send_keys("370.668.969-39")
    el = por_rotulo(driver, "CEP")
    el.clear()
    el.send_keys("63837628")
    el = por_rotulo(driver, "Telefone")
    el.clear()
    el.send_keys("+55 33 98444-9136")
    por_texto(driver, "Salvar cadastro").click()
    esperar(lambda: "sucesso.html" in driver.current_url)
    esperar_texto(driver, "Cadastro realizado com sucesso!")

def test_ct06_cadastro_com_cpf_inválido(driver):
    """Cadastro com CPF inválido"""
    driver.get("http://127.0.0.1:8000/cadastro.html")
    el = achar(driver, By.CSS_SELECTOR, "#nome")
    el.clear()
    el.send_keys("Anthony Gabriel Pimenta")
    el = achar(driver, By.CSS_SELECTOR, "#email")
    el.clear()
    el.send_keys("joao-pedro43@example.com")
    el = achar(driver, By.CSS_SELECTOR, "#cpf")
    el.clear()
    el.send_keys("111.111.111-11")
    el = achar(driver, By.CSS_SELECTOR, "#cep")
    el.clear()
    el.send_keys("29721-866")
    achar(driver, By.CSS_SELECTOR, "#salvar").click()
    esperar(lambda: "CPF inválido." in achar(driver, By.CSS_SELECTOR, "#erro-cpf").text)
    esperar(lambda: "cadastro.html" in driver.current_url)
