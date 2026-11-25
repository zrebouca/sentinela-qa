<?php
// API REST de produtos (JSON) — para os testes de API do Sentinela.
//   GET  api/produtos.php            lista (aceita ?q=texto)
//   GET  api/produtos.php?id=1       um produto
//   POST api/produtos.php            cria (corpo JSON: nome, preco, estoque, categoria_id) -> 201
require dirname(__DIR__) . '/config.php';
require dirname(__DIR__) . '/validacao.php';
header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');

function responder(int $status, $dados): void {
    http_response_code($status);
    echo json_encode($dados, JSON_UNESCAPED_UNICODE);
    exit;
}

try {
    if ($_SERVER['REQUEST_METHOD'] === 'GET') {
        if (isset($_GET['id'])) {
            $st = db()->prepare('SELECT id, nome, preco, estoque, categoria_id FROM produtos WHERE id = ?');
            $st->execute([(int)$_GET['id']]);
            $p = $st->fetch();
            $p ? responder(200, $p + ['preco' => (float)$p['preco']]) : responder(404, ['erro' => 'Produto não encontrado']);
        }
        $q = trim($_GET['q'] ?? '');
        $st = db()->prepare('SELECT id, nome, preco, estoque, categoria_id FROM produtos WHERE nome LIKE ? ORDER BY id');
        $st->execute(["%$q%"]);
        $lista = array_map(fn($p) => ['id' => (int)$p['id'], 'nome' => $p['nome'], 'preco' => round((float)$p['preco'], 2),
                                      'estoque' => (int)$p['estoque'], 'categoria_id' => $p['categoria_id'] === null ? null : (int)$p['categoria_id']],
                           $st->fetchAll());
        responder(200, ['total' => count($lista), 'produtos' => $lista]);
    }
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        $corpo = json_decode(file_get_contents('php://input'), true);
        if (!is_array($corpo)) {
            responder(400, ['erro' => 'Corpo deve ser um JSON']);
        }
        $erros = validar_produto($corpo);
        if ($erros) {
            responder(422, ['erro' => 'Dados inválidos', 'campos' => $erros]);
        }
        $id = salvar_produto($corpo);
        responder(201, ['id' => $id, 'mensagem' => 'Produto criado']);
    }
    responder(405, ['erro' => 'Método não permitido']);
} catch (PDOException $e) {
    responder(500, ['erro' => 'Erro no banco de dados']);
}
