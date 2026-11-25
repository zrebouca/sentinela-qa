// Testes unitários do carrinho (Jest) — rodados pelo Sentinela com tipo: suite.
const { totalItens, aplicarCupom, formatarReais } = require('./carrinho');

describe('totalItens', () => {
  test('soma preço x quantidade em centavos', () => {
    expect(totalItens([{ precoCentavos: 2490, qtd: 2 }, { precoCentavos: 250, qtd: 4 }])).toBe(5980);
  });

  test.each([0, -1, 1.5])('recusa quantidade inválida (%p)', (qtd) => {
    expect(() => totalItens([{ precoCentavos: 100, qtd }])).toThrow('Quantidade inválida');
  });
});

describe('aplicarCupom', () => {
  test('cupom de 10% reduz o total', () => {
    expect(aplicarCupom(10000, 'bemvindo10')).toBe(9000);
  });

  test('cupom inexistente é recusado', () => {
    expect(() => aplicarCupom(10000, 'NAOEXISTE')).toThrow('Cupom inexistente');
  });

  test('cupom vencido é recusado', () => {
    // Encontra o BUG PLANTADO: o BLACK50 venceu em 2020, mas ainda dá 50% de desconto
    expect(() => aplicarCupom(10000, 'BLACK50', new Date('2026-11-20'))).toThrow('Cupom vencido');
  });
});

describe('formatarReais', () => {
  test('formata no padrão brasileiro', () => {
    expect(formatarReais(123456).replace(/\s/g, ' ')).toBe('R$ 1.234,56');
  });
});
