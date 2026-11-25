// Estoque Desktop — sistema de TREINO do Sentinela QA (Windows Forms, .NET Framework 4).
// Compilado automaticamente pelo Sentinela com o csc.exe que já vem no Windows:
//   csc /target:winexe /out:EstoqueDesktop.exe EstoqueDesktop.cs
// Cada controle tem um Name (vira o AutomationId no UI Automation), então os testes não dependem de posição.
// BUG PLANTADO: a quantidade aceita número NEGATIVO (deveria recusar). O roteiro desktop_estoque.yaml encontra.
using System;
using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Estoque Desktop (treino Sentinela QA)")]

public class EstoqueDesktop : Form
{
    static readonly CultureInfo BR = new CultureInfo("pt-BR");
    Panel painelLogin, painelPrincipal;
    TextBox txtUsuario, txtSenha, txtNome, txtPreco, txtQuantidade, txtBusca;
    ComboBox cmbCategoria;
    Button btnEntrar, btnAdicionar, btnBuscar, btnExcluir, btnLimparBusca;
    Label lblMensagemLogin, lblStatus, lblTotal;
    ListView lstProdutos;

    [STAThread]
    public static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new EstoqueDesktop());
    }

    public EstoqueDesktop()
    {
        Text = "Estoque Desktop";
        Name = "janelaPrincipal";
        ClientSize = new Size(760, 560);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI", 10f);
        BackColor = Color.FromArgb(244, 245, 248);
        MinimumSize = new Size(700, 520);
        MontarLogin();
        MontarPrincipal();
        painelPrincipal.Visible = false;
    }

    Label Rotulo(string texto, int x, int y, Control pai)
    {
        var l = new Label { Text = texto, Location = new Point(x, y), AutoSize = true };
        pai.Controls.Add(l);
        return l;
    }

    TextBox Campo(string nome, string acessivel, int x, int y, int largura, Control pai)
    {
        var t = new TextBox { Name = nome, AccessibleName = acessivel, Location = new Point(x, y), Width = largura };
        pai.Controls.Add(t);
        return t;
    }

    Button Botao(string nome, string texto, int x, int y, Control pai, EventHandler acao)
    {
        var b = new Button { Name = nome, Text = texto, Location = new Point(x, y), AutoSize = true,
                             BackColor = Color.FromArgb(37, 84, 212), ForeColor = Color.White, FlatStyle = FlatStyle.Flat };
        b.Click += acao;
        pai.Controls.Add(b);
        return b;
    }

    void MontarLogin()
    {
        painelLogin = new Panel { Name = "painelLogin", Dock = DockStyle.Fill };
        Controls.Add(painelLogin);
        var titulo = Rotulo("Entrar no Estoque Desktop", 230, 120, painelLogin);
        titulo.Font = new Font("Segoe UI", 16f, FontStyle.Bold);
        Rotulo("Usuário de treino: qa  ·  senha: treino123 (fictícios)", 230, 160, painelLogin).ForeColor = Color.DimGray;
        Rotulo("Usuário", 230, 200, painelLogin);
        txtUsuario = Campo("txtUsuario", "Usuário", 230, 222, 300, painelLogin);
        Rotulo("Senha", 230, 258, painelLogin);
        txtSenha = Campo("txtSenha", "Senha", 230, 280, 300, painelLogin);
        txtSenha.UseSystemPasswordChar = true;
        btnEntrar = Botao("btnEntrar", "Entrar", 230, 322, painelLogin, Entrar);
        lblMensagemLogin = new Label { Name = "lblMensagemLogin", Location = new Point(230, 368), AutoSize = true, ForeColor = Color.Firebrick };
        painelLogin.Controls.Add(lblMensagemLogin);
        AcceptButton = btnEntrar;
    }

    void MontarPrincipal()
    {
        painelPrincipal = new Panel { Name = "painelPrincipal", Dock = DockStyle.Fill, Padding = new Padding(16) };
        Controls.Add(painelPrincipal);
        var titulo = Rotulo("Cadastro de produtos", 16, 12, painelPrincipal);
        titulo.Font = new Font("Segoe UI", 14f, FontStyle.Bold);

        Rotulo("Nome do produto", 16, 52, painelPrincipal);
        txtNome = Campo("txtNome", "Nome do produto", 16, 74, 250, painelPrincipal);
        Rotulo("Preço (R$)", 280, 52, painelPrincipal);
        txtPreco = Campo("txtPreco", "Preço", 280, 74, 100, painelPrincipal);
        Rotulo("Quantidade", 394, 52, painelPrincipal);
        txtQuantidade = Campo("txtQuantidade", "Quantidade", 394, 74, 90, painelPrincipal);
        Rotulo("Categoria", 498, 52, painelPrincipal);
        cmbCategoria = new ComboBox { Name = "cmbCategoria", AccessibleName = "Categoria", Location = new Point(498, 74),
                                      Width = 140, DropDownStyle = ComboBoxStyle.DropDownList };
        cmbCategoria.Items.AddRange(new object[] { "Papelaria", "Informática", "Utilidades" });
        cmbCategoria.SelectedIndex = 0;
        painelPrincipal.Controls.Add(cmbCategoria);
        btnAdicionar = Botao("btnAdicionar", "Adicionar", 652, 72, painelPrincipal, Adicionar);

        lblStatus = new Label { Name = "lblStatus", Location = new Point(16, 110), AutoSize = true, Text = "Pronto." };
        painelPrincipal.Controls.Add(lblStatus);

        Rotulo("Buscar", 16, 140, painelPrincipal);
        txtBusca = Campo("txtBusca", "Buscar produto", 70, 137, 250, painelPrincipal);
        btnBuscar = Botao("btnBuscar", "Buscar", 330, 134, painelPrincipal, (s, e) => Filtrar());
        btnLimparBusca = Botao("btnLimparBusca", "Limpar", 410, 134, painelPrincipal, (s, e) => { txtBusca.Text = ""; Filtrar(); });
        btnExcluir = Botao("btnExcluir", "Excluir selecionado", 560, 134, painelPrincipal, Excluir);
        btnExcluir.BackColor = Color.Firebrick;

        lstProdutos = new ListView { Name = "lstProdutos", AccessibleName = "Lista de produtos", View = View.Details,
                                     FullRowSelect = true, Location = new Point(16, 176), Size = new Size(728, 330),
                                     Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom,
                                     MultiSelect = false, HideSelection = false };
        lstProdutos.Columns.Add("Nome", 280);
        lstProdutos.Columns.Add("Preço", 120);
        lstProdutos.Columns.Add("Quantidade", 120);
        lstProdutos.Columns.Add("Categoria", 180);
        painelPrincipal.Controls.Add(lstProdutos);

        lblTotal = new Label { Name = "lblTotal", Location = new Point(16, 516), AutoSize = true,
                               Anchor = AnchorStyles.Left | AnchorStyles.Bottom };
        painelPrincipal.Controls.Add(lblTotal);

        Inserir("Caderno universitário", 24.90m, 50, "Papelaria");
        Inserir("Mouse sem fio", 79.90m, 15, "Informática");
        Inserir("Garrafa térmica", 59.90m, 20, "Utilidades");
        AtualizarTotal();
    }

    void Entrar(object s, EventArgs e)
    {
        if (txtUsuario.Text.Trim() == "" || txtSenha.Text == "")
        {
            lblMensagemLogin.Text = "Preencha usuário e senha.";
            return;
        }
        if (txtUsuario.Text.Trim() == "qa" && txtSenha.Text == "treino123")
        {
            painelLogin.Visible = false;
            painelPrincipal.Visible = true;
            AcceptButton = btnAdicionar;
            Text = "Estoque Desktop — qa";
            txtNome.Focus();
            return;
        }
        lblMensagemLogin.Text = "Usuário ou senha inválidos.";
    }

    void Adicionar(object s, EventArgs e)
    {
        string nome = txtNome.Text.Trim();
        if (nome.Length < 3) { Status("Informe o nome do produto (mínimo 3 letras).", true); return; }
        decimal preco;
        if (!decimal.TryParse(txtPreco.Text.Trim(), NumberStyles.Number, BR, out preco) || preco <= 0)
        { Status("Preço inválido: use um valor maior que zero (ex.: 19,90).", true); return; }
        int quantidade;
        if (!int.TryParse(txtQuantidade.Text.Trim(), out quantidade))
        { Status("Quantidade inválida: use um número inteiro.", true); return; }
        // BUG PLANTADO: faltou "|| quantidade < 0" — quantidade negativa é aceita.
        foreach (ListViewItem it in lstProdutos.Items)
            if (string.Equals(it.Text, nome, StringComparison.CurrentCultureIgnoreCase))
            { Status("Já existe um produto com esse nome.", true); return; }
        Inserir(nome, preco, quantidade, cmbCategoria.SelectedItem.ToString());
        AtualizarTotal();
        Status("Produto adicionado com sucesso!", false);
        txtNome.Text = txtPreco.Text = txtQuantidade.Text = "";
        txtNome.Focus();
    }

    void Inserir(string nome, decimal preco, int quantidade, string categoria)
    {
        var item = new ListViewItem(nome);
        item.SubItems.Add(preco.ToString("C", BR));
        item.SubItems.Add(quantidade.ToString());
        item.SubItems.Add(categoria);
        item.Tag = new object[] { preco, quantidade };
        lstProdutos.Items.Add(item);
    }

    void Excluir(object s, EventArgs e)
    {
        if (lstProdutos.SelectedItems.Count == 0) { Status("Selecione um produto para excluir.", true); return; }
        string nome = lstProdutos.SelectedItems[0].Text;
        lstProdutos.Items.Remove(lstProdutos.SelectedItems[0]);
        AtualizarTotal();
        Status("Produto excluído: " + nome, false);
    }

    void Filtrar()
    {
        string termo = txtBusca.Text.Trim().ToLower();
        int visiveis = 0;
        foreach (ListViewItem it in lstProdutos.Items)
        {
            bool ok = termo == "" || it.Text.ToLower().Contains(termo);
            it.ForeColor = ok ? SystemColors.WindowText : Color.Silver;
            if (ok) visiveis++;
        }
        Status(visiveis + " produto(s) encontrado(s) para \"" + txtBusca.Text.Trim() + "\".", false);
    }

    void AtualizarTotal()
    {
        decimal valor = 0; int unidades = 0;
        foreach (ListViewItem it in lstProdutos.Items)
        {
            var d = (object[])it.Tag;
            valor += (decimal)d[0] * (int)d[1];
            unidades += (int)d[1];
        }
        lblTotal.Text = lstProdutos.Items.Count + " produto(s) · " + unidades + " unidade(s) · Valor em estoque: " + valor.ToString("C", BR);
    }

    void Status(string texto, bool erro)
    {
        lblStatus.Text = texto;
        lblStatus.ForeColor = erro ? Color.Firebrick : Color.ForestGreen;
    }
}
