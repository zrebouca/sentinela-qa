// Carrinho de compras — código de exemplo para TESTES UNITÁRIOS com Jest.
// Valores em centavos (inteiros) para não sofrer com arredondamento de ponto flutuante.
// BUG PLANTADO: cupons vencidos ainda são aceitos. O teste "cupom vencido é recusado" encontra.

const CUPONS = {
  BEMVINDO10: { tipo: 'percentual', valor: 10, validoAte: '2099-12-31' },
  FRETE0: { tipo: 'frete', valor: 0, validoAte: '2099-12-31' },
  BLACK50: { tipo: 'percentual', valor: 50, validoAte: '2020-11-30' }, // já venceu
};

function totalItens(itens) {
  return itens.reduce((soma, item) => {
    if (!Number.isInteger(item.qtd) || item.qtd <= 0) throw new Error('Quantidade inválida');
    return soma + item.precoCentavos * item.qtd;
  }, 0);
}

function aplicarCupom(totalCentavos, codigo, hoje = new Date()) {
  const cupom = CUPONS[String(codigo || '').toUpperCase()];
  if (!cupom) throw new Error('Cupom inexistente');
  // (falta conferir: if (new Date(cupom.validoAte) < hoje) throw new Error('Cupom vencido'))  <- bug plantado
  if (cupom.tipo === 'percentual') return Math.round(totalCentavos * (100 - cupom.valor) / 100);
  return totalCentavos;
}

function formatarReais(centavos) {
  return (centavos / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

module.exports = { totalItens, aplicarCupom, formatarReais };
