-- Banco de TREINO do Sentinela QA (sistema "Loja PHP" no XAMPP).
-- ATENÇÃO: este banco tem PROBLEMAS PLANTADOS DE PROPÓSITO para o Auditor de Banco encontrar:
--   * categorias em MyISAM e latin1          * preço e total em FLOAT (dinheiro impreciso)
--   * data da venda guardada como texto      * relacionamentos sem índice e sem FOREIGN KEY
--   * e-mail sem UNIQUE                      * tabela de log sem chave primária
--   * um usuário legado com senha em MD5     * vendas apontando para produto inexistente (órfãs)
-- Não use este modelo como exemplo de boas práticas — use o RELATÓRIO da auditoria para ver como corrigir.

DROP DATABASE IF EXISTS sentinela_loja;
CREATE DATABASE sentinela_loja CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sentinela_loja;

CREATE TABLE usuarios (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(100) NULL,
  email VARCHAR(150) NOT NULL,
  senha VARCHAR(255) NOT NULL,
  perfil VARCHAR(20) NOT NULL DEFAULT 'operador',
  criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE categorias (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(80) NOT NULL
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

CREATE TABLE produtos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(120) NOT NULL,
  preco FLOAT NOT NULL,
  estoque INT NOT NULL DEFAULT 0,
  categoria_id INT NULL,
  criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE vendas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  produto_id INT NOT NULL,
  usuario_id INT NOT NULL,
  quantidade INT NOT NULL,
  total FLOAT NOT NULL,
  data_venda VARCHAR(20) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE log_acessos (
  usuario_id INT,
  acao VARCHAR(60),
  quando DATETIME
) ENGINE=InnoDB;

INSERT INTO categorias (nome) VALUES ('Papelaria'), ('Informática'), ('Utilidades');

INSERT INTO produtos (nome, preco, estoque, categoria_id) VALUES
  ('Caderno universitário', 24.90, 50, 1),
  ('Caneta azul', 2.50, 300, 1),
  ('Mouse sem fio', 79.90, 15, 2),
  ('Garrafa térmica', 59.90, 20, 3);

-- usuário legado com senha em MD5 (problema plantado; o login do sistema usa password_verify e não aceita esse)
INSERT INTO usuarios (nome, email, senha, perfil) VALUES
  ('Usuário Antigo', 'antigo@loja.test', MD5('123456'), 'operador');

INSERT INTO vendas (produto_id, usuario_id, quantidade, total, data_venda) VALUES
  (1, 1, 2, 49.80, '05/11/2026'),
  (3, 1, 1, 79.90, '2026-11-06'),
  (999, 1, 1, 10.00, '07/11/2026');

INSERT INTO log_acessos (usuario_id, acao, quando) VALUES (1, 'login', NOW());
