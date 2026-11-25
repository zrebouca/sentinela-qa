-- Correções sugeridas pelo Sentinela QA para o banco `sentinela_loja` (20/11/2026 22:13)
-- FAÇA BACKUP ANTES (o Sentinela faz sozinho quando você aplica pelo painel).
-- Revise cada comando: alguns exigem limpeza de dados antes (indicado nos comentários).

USE `sentinela_loja`;

-- [C002] Média · servidor: O sql_mode não está em modo estrito (STRICT_TRANS_TABLES).
-- SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- [C003] Baixa · servidor: O log de consultas lentas (slow_query_log) está desligado.
-- SET GLOBAL slow_query_log = 'ON';
-- SET GLOBAL long_query_time = 1;

-- [C004] Crítica · servidor: O usuário 'root' não tem senha (hosts: localhost, 127.0.0.1, ::1).
-- -- troque SENHA_FORTE antes de rodar; atualize também o PHP/aplicação
-- ALTER USER 'root'@'localhost' IDENTIFIED BY 'SENHA_FORTE';
-- ALTER USER 'root'@'127.0.0.1' IDENTIFIED BY 'SENHA_FORTE';
-- ALTER USER 'root'@'::1' IDENTIFIED BY 'SENHA_FORTE';
-- CREATE USER IF NOT EXISTS 'app_sentinela_loja'@'localhost' IDENTIFIED BY 'OUTRA_SENHA_FORTE';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON `sentinela_loja`.* TO 'app_sentinela_loja'@'localhost';

-- [C005] Alta · servidor: O usuário 'pma' não tem senha (hosts: localhost).
-- -- troque SENHA_FORTE antes de rodar; atualize também o PHP/aplicação
-- ALTER USER 'pma'@'localhost' IDENTIFIED BY 'SENHA_FORTE';
-- CREATE USER IF NOT EXISTS 'app_sentinela_loja'@'localhost' IDENTIFIED BY 'OUTRA_SENHA_FORTE';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON `sentinela_loja`.* TO 'app_sentinela_loja'@'localhost';

-- [C006] Média · categorias: Tabela usa o engine MyISAM.
ALTER TABLE `categorias` ENGINE=InnoDB;

-- [C007] Média · categorias: Tabela com collation latin1_swedish_ci (não é utf8mb4).
ALTER TABLE `categorias` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- [C008] Baixa · categorias: Tabela sem coluna de data de criação (auditoria).
ALTER TABLE `categorias` ADD COLUMN criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- [C009] Alta · log_acessos: Tabela sem chave primária (PRIMARY KEY).
ALTER TABLE `log_acessos` ADD COLUMN id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST;

-- [C010] Baixa · log_acessos: Tabela sem coluna de data de criação (auditoria).
ALTER TABLE `log_acessos` ADD COLUMN criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- [C011] Média · log_acessos.usuario_id: Coluna de relacionamento 'usuario_id' sem índice.
ALTER TABLE `log_acessos` ADD INDEX `idx_usuario_id` (`usuario_id`);

-- [C012] Média · log_acessos.usuario_id: 'usuario_id' aponta para 'usuarios', mas não há chave estrangeira.
ALTER TABLE `log_acessos` ADD CONSTRAINT `fk_log_acessos_usuario_id` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON UPDATE CASCADE ON DELETE RESTRICT;

-- [C013] Alta · produtos.preco: Valor em dinheiro guardado como FLOAT.
ALTER TABLE `produtos` MODIFY `preco` DECIMAL(12,2) NOT NULL;

-- [C014] Média · produtos.categoria_id: Coluna de relacionamento 'categoria_id' sem índice.
ALTER TABLE `produtos` ADD INDEX `idx_categoria_id` (`categoria_id`);

-- [C015] Média · produtos.categoria_id: 'categoria_id' aponta para 'categorias', mas não há chave estrangeira.
-- ALTER TABLE `produtos` ADD CONSTRAINT `fk_produtos_categoria_id` FOREIGN KEY (`categoria_id`) REFERENCES `categorias` (`id`) ON UPDATE CASCADE ON DELETE RESTRICT;

-- [C016] Baixa · usuarios.nome: 'nome' aceita NULL, mas parece ser um campo obrigatório.
-- -- preencha os NULL antes
-- ALTER TABLE `usuarios` MODIFY `nome` varchar(100) NOT NULL;

-- [C017] Média · usuarios.email: 'email' não tem índice UNIQUE.
ALTER TABLE `usuarios` ADD UNIQUE INDEX `uk_email` (`email`);

-- [C019] Baixa · vendas: Tabela sem coluna de data de criação (auditoria).
ALTER TABLE `vendas` ADD COLUMN criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- [C020] Média · vendas.produto_id: Coluna de relacionamento 'produto_id' sem índice.
ALTER TABLE `vendas` ADD INDEX `idx_produto_id` (`produto_id`);

-- [C021] Alta · vendas.produto_id: 'produto_id' aponta para 'produtos', mas não há chave estrangeira — já existem 1 registro(s) órfão(s).
-- ALTER TABLE `vendas` ADD CONSTRAINT `fk_vendas_produto_id` FOREIGN KEY (`produto_id`) REFERENCES `produtos` (`id`) ON UPDATE CASCADE ON DELETE RESTRICT;

-- [C022] Média · vendas.usuario_id: Coluna de relacionamento 'usuario_id' sem índice.
ALTER TABLE `vendas` ADD INDEX `idx_usuario_id` (`usuario_id`);

-- [C023] Média · vendas.usuario_id: 'usuario_id' aponta para 'usuarios', mas não há chave estrangeira.
ALTER TABLE `vendas` ADD CONSTRAINT `fk_vendas_usuario_id` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON UPDATE CASCADE ON DELETE RESTRICT;

-- [C024] Alta · vendas.total: Valor em dinheiro guardado como FLOAT.
ALTER TABLE `vendas` MODIFY `total` DECIMAL(12,2) NOT NULL;

-- [C025] Média · vendas.data_venda: Data guardada como texto (varchar(20)).
-- -- revise os valores antes!
-- ALTER TABLE `vendas` MODIFY `data_venda` DATETIME NULL;
