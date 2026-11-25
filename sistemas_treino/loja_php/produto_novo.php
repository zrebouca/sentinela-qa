<?php
require __DIR__ . '/config.php';
require __DIR__ . '/validacao.php';
exigir_login();

$erros = [];
$dados = ['nome' => '', 'preco' => '', 'estoque' => '', 'categoria_id' => ''];
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $dados = array_merge($dados, array_map('trim', $_POST));
    $erros = validar_produto($dados);
    if (!$erros) {
        salvar_produto($dados);
        header('Location: produtos.php?ok=1');
        exit;
    }
}
$categorias = db()->query('SELECT id, nome FROM categorias ORDER BY nome')->fetchAll();
topo('Novo produto');
?>
<h1>Novo produto</h1>
<form method="post" class="card" novalidate>
  <label for="nome">Nome do produto</label>
  <input id="nome" name="nome" value="<?= e($dados['nome']) ?>">
  <div class="erro-campo" id="erro-nome"><?= e($erros['nome'] ?? '') ?></div>

  <label for="preco">Preço (R$)</label>
  <input id="preco" name="preco" value="<?= e($dados['preco']) ?>" placeholder="0,00">
  <div class="erro-campo" id="erro-preco"><?= e($erros['preco'] ?? '') ?></div>

  <label for="estoque">Estoque</label>
  <input id="estoque" name="estoque" value="<?= e($dados['estoque']) ?>">
  <div class="erro-campo" id="erro-estoque"><?= e($erros['estoque'] ?? '') ?></div>

  <label for="categoria_id">Categoria</label>
  <select id="categoria_id" name="categoria_id">
    <option value="">Selecione</option>
    <?php foreach ($categorias as $c): ?>
      <option value="<?= (int)$c['id'] ?>" <?= $dados['categoria_id'] == $c['id'] ? 'selected' : '' ?>><?= e($c['nome']) ?></option>
    <?php endforeach; ?>
  </select>
  <button type="submit" id="salvar">Salvar produto</button>
</form>
<?php if ($erros): ?><div class="alerta erro" role="alert">Corrija <?= count($erros) ?> campo(s) antes de salvar.</div><?php endif; ?>
<?php rodape();
