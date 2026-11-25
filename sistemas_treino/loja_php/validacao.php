<?php
// Regras de validação de produto — usadas pela tela e pela API.
// BUGS PLANTADOS (para a exploração do Sentinela encontrar):
//   1) o preço só precisa ser número: preço NEGATIVO é aceito;
//   2) o estoque é convertido com (int): "abc" vira 0 e é aceito em silêncio.

function validar_produto(array $d): array {
    $erros = [];
    $nome = trim((string)($d['nome'] ?? ''));
    if (mb_strlen($nome) < 3) {
        $erros['nome'] = 'Informe o nome do produto (mínimo 3 letras).';
    } elseif (mb_strlen($nome) > 120) {
        $erros['nome'] = 'Nome muito longo (máximo 120 caracteres).';
    }
    $preco = str_replace(',', '.', (string)($d['preco'] ?? ''));
    if (!is_numeric($preco)) {
        $erros['preco'] = 'Preço inválido.';
    }
    // (falta: if ((float)$preco <= 0) ...)  <- bug plantado
    if (($d['estoque'] ?? '') === '') {
        $erros['estoque'] = 'Informe o estoque.';
    }
    // (falta validar que estoque é inteiro >= 0)  <- bug plantado
    return $erros;
}

function salvar_produto(array $d): int {
    $st = db()->prepare('INSERT INTO produtos (nome, preco, estoque, categoria_id) VALUES (?, ?, ?, ?)');
    $st->execute([
        trim($d['nome']),
        (float)str_replace(',', '.', (string)$d['preco']),
        (int)$d['estoque'],
        ($d['categoria_id'] ?? '') === '' ? null : (int)$d['categoria_id'],
    ]);
    return (int)db()->lastInsertId();
}
