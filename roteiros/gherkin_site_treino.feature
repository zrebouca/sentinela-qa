# language: pt
# Exemplo em Gherkin (BDD) — os mesmos testes do site de treino, escritos como cenários.
# Suba o site antes:  sentinela site-treino
# alvo: http://127.0.0.1:8000
# sistema: Loja Treino (Gherkin)
# responsavel: Mateus

Funcionalidade: Login e cadastro na Loja Treino
  Como cliente da loja
  Quero entrar na minha conta e cadastrar clientes
  Para usar o sistema com segurança

  @CT01 @critica
  Cenário: Login com usuário válido
    Dado que eu acesso "/index.html"
    Quando eu preencho "rotulo=Usuário" com "qa"
    E eu preencho "rotulo=Senha" com "{env.TREINO_SENHA|treino123}"
    E eu clico em "Entrar"
    Então a URL deve conter "painel.html"
    E devo ver "Bem-vindo, qa!"

  @CT02
  Cenário: Login com senha errada
    Dado que eu acesso "/index.html"
    Quando eu preencho "rotulo=Usuário" com "qa"
    E eu preencho "rotulo=Senha" com "errada"
    E eu clico em "Entrar"
    Então devo ver a mensagem de erro "Usuário ou senha inválidos."

  @CT03 @alta
  Cenário: Cadastro bloqueia CPF inválido
    Dado que eu acesso "/cadastro.html"
    Quando eu preencho "#nome" com "{faker.first_name} {faker.last_name}"
    E eu preencho "#email" com "{faker.email}"
    E eu preencho "#cpf" com "123.456.789-00"
    E eu preencho "#cep" com "01001-000"
    E eu clico em "Salvar cadastro"
    Então devo ver "CPF inválido." em "#erro-cpf"
    E a URL deve conter "cadastro.html"
