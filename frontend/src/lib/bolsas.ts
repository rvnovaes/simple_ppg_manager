import type { components } from './api/schema';

/**
 * Vocabulário do edital de bolsas, num lugar só.
 *
 * Molde de `lib/selecao.ts`, e pela mesma razão: as telas do edital, da
 * inscrição, da análise e do resultado precisam escrever nível, seção e
 * unidade com as mesmas palavras do edital.
 *
 * Rótulo de coisa **já existente** não mora aqui: `ScholarshipEditionOut`,
 * `BaremeItemOut` e companhia viajam com `status_label`, `level_label`,
 * `section_label` e `unit_label` resolvidos pelo servidor, e é esse texto
 * que a tela mostra. O que mora aqui é a lista de opções que o formulário
 * precisa desenhar **antes** de existir o objeto — não dá para pedir ao
 * servidor o rótulo de um item que ainda não foi criado.
 */

export type Nivel = components['schemas']['ScholarshipLevel'];
export type Secao = components['schemas']['BaremeSection'];
export type Unidade = components['schemas']['BaremeUnit'];
export type SituacaoDaEdicao = components['schemas']['ScholarshipEditionStatus'];

/** Mestrado e doutorado correm independentes: dois baremas, duas listas. */
export const NIVEIS: { valor: Nivel; rotulo: string }[] = [
	{ valor: 'masters', rotulo: 'Mestrado' },
	{ valor: 'doctorate', rotulo: 'Doutorado' }
];

/** As seis seções na ordem dos incisos do edital (I..VI). */
export const SECOES: { valor: Secao; rotulo: string }[] = [
	{ valor: 'formation', rotulo: 'I - Formação Acadêmica' },
	{ valor: 'bibliographic', rotulo: 'II - Produção Bibliográfica' },
	{ valor: 'events', rotulo: 'III - Participação em Eventos' },
	{ valor: 'professional', rotulo: 'IV - Atividade Profissional' },
	{ valor: 'boards', rotulo: 'V - Participação em Bancas' },
	{ valor: 'other_titles', rotulo: 'VI - Outros Títulos' }
];

export const UNIDADES: { valor: Unidade; rotulo: string }[] = [
	{ valor: 'semester', rotulo: 'Semestre' },
	{ valor: 'month', rotulo: 'Mês' },
	{ valor: 'hour', rotulo: 'Hora' },
	{ valor: 'unit', rotulo: 'Unidade' }
];

/**
 * O cronograma do edital, na ordem em que o ano acontece.
 *
 * As cinco datas são **informação publicada**, nunca gatilho: nada abre ou
 * fecha por relógio neste módulo (docstring de `apps/scholarships/models.py`).
 * Quem move a edição é a secretaria, botão a botão.
 */
export type CampoDeData =
	| 'submission_starts_on'
	| 'submission_ends_on'
	| 'preliminary_result_on'
	| 'appeal_ends_on'
	| 'final_result_on';

export const CRONOGRAMA: { campo: CampoDeData; rotulo: string }[] = [
	{ campo: 'submission_starts_on', rotulo: 'Inscrições abrem em' },
	{ campo: 'submission_ends_on', rotulo: 'Inscrições encerram em' },
	{ campo: 'preliminary_result_on', rotulo: 'Resultado preliminar em' },
	{ campo: 'appeal_ends_on', rotulo: 'Recursos encerram em' },
	{ campo: 'final_result_on', rotulo: 'Resultado final em' }
];

/**
 * Data pura (`YYYY-MM-DD`) como o edital a publica.
 *
 * O `T00:00:00` não é enfeite: sem ele o `Date` lê a string como UTC e o
 * fuso de Brasília devolve o dia anterior — o cronograma sairia um dia
 * adiantado na tela inteira. Mesmo precedente de `(app)/alunos/[id]`.
 */
export function formatarData(iso: string | null): string {
	if (iso === null || iso === '') return '—';
	return new Date(`${iso}T00:00:00`).toLocaleDateString('pt-BR');
}
