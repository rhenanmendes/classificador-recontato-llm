/**
 * Painel de recontato no Google Sheets (Apps Script)
 * ---------------------------------------------------
 * Transforma o CSV exportado pelo pipeline (outputs/<fonte>/classificacoes_<execucao>.csv)
 * em um painel tático para a rotina da operação:
 *   1. Pareto de motivos (quantidade, %, % acumulado, área responsável)
 *   2. Comparação semana contra semana por motivo, com ALERTA quando um motivo
 *      ganha participação acima do limite definido (gatilho para war room)
 *   3. (Opcional) e-mail automático com os alertas
 *
 * Como usar:
 *   1. Crie uma planilha e importe o CSV numa aba chamada "classificacoes"
 *      (Arquivo > Importar > Upload > Substituir página atual).
 *   2. Extensões > Apps Script, cole este arquivo e salve.
 *   3. Recarregue a planilha: aparece o menu "Recontato" > "Atualizar painel".
 *   4. Para rodar todo dia sozinho: no editor do Apps Script, Acionadores (ícone de relógio)
 *      > Adicionar acionador > função atualizarPainel > baseado em tempo > diário.
 */

const CONFIG = {
  abaDados: 'classificacoes',
  abaPainel: 'painel',
  limiteAlertaPP: 5,      // alerta se o motivo ganhar 5 p.p. ou mais de participação na semana
  volumeMinimoAlerta: 10, // e só se tiver pelo menos 10 casos na semana atual
  emailAlerta: '',        // preencha para receber os alertas por e-mail (vazio = desligado)
};

const DONOS = {
  'Problema não resolvido': 'Processos / Base de conhecimento',
  'Informação incompleta ou confusa': 'Treinamento / Qualidade',
  'Promessa ou prazo não cumprido': 'Processos / Áreas de backoffice',
  'Direcionado para outro canal sem resolução': 'Processos / Roteamento',
  'Demora ou ausência de retorno': 'Planejamento / WFM',
  'Discorda da solução ou da política': 'Produto / Política comercial',
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Recontato')
    .addItem('Atualizar painel', 'atualizarPainel')
    .addToUi();
}

function atualizarPainel() {
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
  const dados = planilha.getSheetByName(CONFIG.abaDados);
  if (!dados) throw new Error('Aba "' + CONFIG.abaDados + '" não encontrada. Importe o CSV nela.');

  const valores = dados.getDataRange().getValues();
  const cabecalho = valores.shift().map(String);
  const col = (nome) => {
    const i = cabecalho.indexOf(nome);
    if (i < 0) throw new Error('Coluna "' + nome + '" não encontrada no CSV.');
    return i;
  };
  const iMotivo = col('nome_motivo');
  const iAcionavel = col('acionavel');
  const iInicio = col('inicio');

  const linhas = valores
    .filter((l) => l[iMotivo] !== '')
    .map((l) => ({
      motivo: String(l[iMotivo]),
      acionavel: String(l[iAcionavel]).toLowerCase() === 'true',
      data: paraData_(l[iInicio]),
    }));
  if (linhas.length === 0) throw new Error('A aba de dados está vazia.');

  const pareto = montarPareto_(linhas);
  const semanas = compararSemanas_(linhas);

  let painel = planilha.getSheetByName(CONFIG.abaPainel);
  if (!painel) painel = planilha.insertSheet(CONFIG.abaPainel);
  painel.clear();

  painel.getRange(1, 1).setValue('Painel de recontato').setFontSize(14).setFontWeight('bold');
  painel.getRange(2, 1).setValue('Atualizado em ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm') +
    ' · ' + linhas.length + ' recontatos classificados');

  // Bloco 1: Pareto
  const tabelaPareto = [['Motivo', 'Qtd.', '%', '% acumulado', 'Acionável', 'Área responsável']].concat(pareto);
  painel.getRange(4, 1, tabelaPareto.length, 6).setValues(tabelaPareto);
  painel.getRange(4, 1, 1, 6).setFontWeight('bold').setBackground('#e8f0fb');
  painel.getRange(5, 3, pareto.length, 2).setNumberFormat('0.0%');

  // Bloco 2: semana contra semana
  const inicioBloco = 6 + tabelaPareto.length;
  painel.getRange(inicioBloco - 1, 1).setValue(semanas.titulo).setFontWeight('bold');
  const tabelaSemanas = [['Motivo', 'Qtd. semana anterior', '% semana anterior', 'Qtd. semana atual', '% semana atual', 'Variação (p.p.)', 'Status']]
    .concat(semanas.linhas);
  painel.getRange(inicioBloco, 1, tabelaSemanas.length, 7).setValues(tabelaSemanas);
  painel.getRange(inicioBloco, 1, 1, 7).setFontWeight('bold').setBackground('#e8f0fb');
  if (semanas.linhas.length) {
    painel.getRange(inicioBloco + 1, 3, semanas.linhas.length, 1).setNumberFormat('0.0%');
    painel.getRange(inicioBloco + 1, 5, semanas.linhas.length, 1).setNumberFormat('0.0%');
    painel.getRange(inicioBloco + 1, 6, semanas.linhas.length, 1).setNumberFormat('+0.0;-0.0;0.0');
  }
  semanas.linhas.forEach((l, i) => {
    if (l[6].indexOf('ALERTA') === 0) {
      painel.getRange(inicioBloco + 1 + i, 1, 1, 7).setBackground('#fde8e7');
    }
  });
  painel.autoResizeColumns(1, 7);

  const alertas = semanas.linhas.filter((l) => l[6].indexOf('ALERTA') === 0);
  if (alertas.length && CONFIG.emailAlerta) enviarAlerta_(alertas, semanas.titulo);
}

function montarPareto_(linhas) {
  const contagem = {};
  const acionavel = {};
  linhas.forEach((l) => {
    contagem[l.motivo] = (contagem[l.motivo] || 0) + 1;
    acionavel[l.motivo] = l.acionavel;
  });
  const total = linhas.length;
  let acumulado = 0;
  return Object.keys(contagem)
    .sort((a, b) => contagem[b] - contagem[a])
    .map((motivo) => {
      const pct = contagem[motivo] / total;
      acumulado += pct;
      return [motivo, contagem[motivo], pct, acumulado, acionavel[motivo] ? 'Sim' : 'Não', DONOS[motivo] || '-'];
    });
}

/** Compara as duas últimas semanas completas (segunda a domingo) presentes nos dados. */
function compararSemanas_(linhas) {
  const comData = linhas.filter((l) => l.data);
  if (comData.length === 0) return { titulo: 'Semana contra semana: sem datas válidas', linhas: [] };

  const ultima = new Date(Math.max.apply(null, comData.map((l) => l.data.getTime())));
  const inicioAtual = inicioDaSemana_(ultima);
  // Se a última semana ainda não terminou, compara as duas anteriores (completas).
  if (ultima.getDay() !== 0) inicioAtual.setDate(inicioAtual.getDate() - 7);
  const inicioAnterior = new Date(inicioAtual);
  inicioAnterior.setDate(inicioAnterior.getDate() - 7);
  const fimAtual = new Date(inicioAtual);
  fimAtual.setDate(fimAtual.getDate() + 7);

  const anterior = comData.filter((l) => l.data >= inicioAnterior && l.data < inicioAtual);
  const atual = comData.filter((l) => l.data >= inicioAtual && l.data < fimAtual);
  const contar = (lista) => lista.reduce((acc, l) => { acc[l.motivo] = (acc[l.motivo] || 0) + 1; return acc; }, {});
  const cAnt = contar(anterior);
  const cAtu = contar(atual);
  const motivos = Array.from(new Set(Object.keys(cAnt).concat(Object.keys(cAtu))));

  const fmt = (d) => Utilities.formatDate(d, Session.getScriptTimeZone(), 'dd/MM');
  const fimExibicao = new Date(fimAtual);
  fimExibicao.setDate(fimExibicao.getDate() - 1);
  const titulo = 'Semana contra semana: ' + fmt(inicioAnterior) + ' a ' + fmt(new Date(inicioAtual.getTime() - 864e5)) +
    ' vs ' + fmt(inicioAtual) + ' a ' + fmt(fimExibicao);

  const resultado = motivos.map((m) => {
    const qAnt = cAnt[m] || 0;
    const qAtu = cAtu[m] || 0;
    const pAnt = anterior.length ? qAnt / anterior.length : 0;
    const pAtu = atual.length ? qAtu / atual.length : 0;
    const variacao = (pAtu - pAnt) * 100;
    let status = 'Estável';
    if (variacao >= CONFIG.limiteAlertaPP && qAtu >= CONFIG.volumeMinimoAlerta) status = 'ALERTA: investigar causa raiz';
    else if (variacao >= CONFIG.limiteAlertaPP) status = 'Subindo (volume baixo)';
    else if (variacao <= -CONFIG.limiteAlertaPP) status = 'Caindo';
    return [m, qAnt, pAnt, qAtu, pAtu, variacao, status];
  });
  resultado.sort((a, b) => b[5] - a[5]);
  return { titulo: titulo, linhas: resultado };
}

function enviarAlerta_(alertas, titulo) {
  const corpo = alertas
    .map((l) => '• ' + l[0] + ': ' + (l[2] * 100).toFixed(1) + '% → ' + (l[4] * 100).toFixed(1) +
      '% (' + (l[5] >= 0 ? '+' : '') + l[5].toFixed(1) + ' p.p., ' + l[3] + ' casos)')
    .join('\n');
  MailApp.sendEmail(
    CONFIG.emailAlerta,
    'Alerta de recontato: ' + alertas.length + ' motivo(s) em alta',
    titulo + '\n\n' + corpo + '\n\nPainel: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl()
  );
}

function inicioDaSemana_(data) {
  const d = new Date(data.getFullYear(), data.getMonth(), data.getDate());
  const dia = d.getDay(); // 0 = domingo
  d.setDate(d.getDate() - (dia === 0 ? 6 : dia - 1));
  return d;
}

function paraData_(valor) {
  if (valor instanceof Date) return valor;
  if (!valor) return null;
  // Formato exportado pelo pandas: "2026-05-03 10:00:00"
  const partes = String(valor).match(/(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  if (!partes) return null;
  return new Date(+partes[1], +partes[2] - 1, +partes[3], +(partes[4] || 0), +(partes[5] || 0));
}
