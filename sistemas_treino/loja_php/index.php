<?php
require __DIR__ . '/config.php';

$erro = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $email = trim($_POST['email'] ?? '');
    $senha = $_POST['senha'] ?? '';
    if ($email === '' || $senha === '') {
        $erro = 'Informe e-mail e senha.';
    } else {
        $st = db()->prepare('SELECT id, nome, senha FROM usuarios WHERE email = ? LIMIT 1');
        $st->execute([$email]);
        $u = $st->fetch();
        if ($u && password_verify($senha, $u['senha'])) {
            session_regenerate_id(true);
            $_SESSION['usuario'] = ['id' => $u['id'], 'nome' => $u['nome']];
            db()->prepare("INSERT INTO log_acessos (usuario_id, acao, quando) VALUES (?, 'login', NOW())")->execute([$u['id']]);
            header('Location: produtos.php');
            exit;
        }
        $erro = 'E-mail ou senha incorretos.';
    }
}
topo('Entrar');
?>
<h1>Entrar</h1>
<p class="dica">Usuário de treino: <code>qa@loja.test</code> · senha <code>treino123</code> (fictícios).</p>
<form method="post" class="card" novalidate>
  <label for="email">E-mail</label>
  <input id="email" name="email" type="email" value="<?= e($_POST['email'] ?? '') ?>">
  <label for="senha">Senha</label>
  <input id="senha" name="senha" type="password">
  <button type="submit">Entrar</button>
</form>
<?php if ($erro): ?><div class="alerta erro" role="alert"><?= e($erro) ?></div><?php endif; ?>
<?php rodape();
