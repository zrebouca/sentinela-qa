<?php
// Configuração do sistema de treino "Loja PHP" (XAMPP).
// As credenciais vêm de variáveis de ambiente; o padrão é o do XAMPP (root sem senha).
// Em um sistema real NUNCA deixe root sem senha — o Auditor de Banco do Sentinela aponta isso.
session_start();

function db(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $host = getenv('LOJA_DB_HOST') ?: '127.0.0.1';
        $user = getenv('LOJA_DB_USUARIO') ?: 'root';
        $pass = getenv('LOJA_DB_SENHA') ?: '';
        $pdo = new PDO("mysql:host=$host;dbname=sentinela_loja;charset=utf8mb4", $user, $pass, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
    }
    return $pdo;
}

function exigir_login(): void {
    if (empty($_SESSION['usuario'])) {
        header('Location: index.php');
        exit;
    }
}

function e(?string $texto): string {
    return htmlspecialchars((string)$texto, ENT_QUOTES, 'UTF-8');
}

function topo(string $titulo): void {
    $u = $_SESSION['usuario'] ?? null;
    echo '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">';
    echo '<title>' . e($titulo) . ' — Loja PHP (treino)</title><link rel="stylesheet" href="estilo.css"></head><body>';
    echo '<header><b>Loja PHP</b><span class="tag">sistema de treino</span>';
    if ($u) {
        echo '<nav><a href="produtos.php">Produtos</a><a href="produto_novo.php">Novo produto</a>';
        echo '<span>Olá, ' . e($u['nome']) . '</span><a href="sair.php" id="sair">Sair</a></nav>';
    }
    echo '</header><main>';
}

function rodape(): void {
    echo '</main></body></html>';
}
