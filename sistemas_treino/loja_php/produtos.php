<?php
require __DIR__ . '/config.php';
exigir_login();

$q = trim($_GET['q'] ?? '');
$sql = 'SELECT p.id, p.nome, p.preco, p.estoque, c.nome AS categoria
        FROM produtos p LEFT JOIN categorias c ON c.id = p.categoria_id';
$params = [];
if ($q !== '') {
    $sql .= ' WHERE p.nome LIKE ?';
    $params[] = "%$q%";
}
$sql .= ' ORDER BY p.id DESC';
$st = db()->prepare($sql);
$st->execute($params);
$produtos = $st->fetchAll();

topo('Produtos');
?>
<h1>Produtos</h1>
<?php if (isset($_GET['ok'])): ?><div class="alerta sucesso" role="status">Produto cadastrado com sucesso!</div><?php endif; ?>
<form method="get" class="busca">
  <label for="q">Buscar produto</label>
  <input id="q" name="q" type="search" placeholder="Buscar produto" value="<?= e($q) ?>">
  <button type="submit">Buscar</button>
</form>
<table id="tabela-produtos">
  <thead><tr><th>ID</th><th>Nome</th><th>Preço</th><th>Estoque</th><th>Categoria</th></tr></thead>
  <tbody>
  <?php foreach ($produtos as $p): ?>
    <tr><td><?= (int)$p['id'] ?></td><td><?= e($p['nome']) ?></td>
      <td>R$ <?= number_format((float)$p['preco'], 2, ',', '.') ?></td>
      <td><?= (int)$p['estoque'] ?></td><td><?= e($p['categoria']) ?></td></tr>
  <?php endforeach; ?>
  </tbody>
</table>
<p id="total"><?= count($produtos) ?> produto(s)</p>
<?php if (!$produtos): ?><p id="sem-resultado">Nenhum produto encontrado.</p><?php endif; ?>
<?php rodape();
