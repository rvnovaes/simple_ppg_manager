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

/**
 * Decimal do jeito que o edital o publica.
 *
 * O Ninja manda `Decimal` como **string** (`"0.50"`), e é assim que ele
 * chega ao `schema.d.ts`. Converter para `Number` só para exibir é seguro
 * aqui — são pontuações de duas casas, não dinheiro que soma —, e o
 * `toLocaleString` é quem põe a vírgula. Nada de conta: soma e teto do
 * barema são do servidor.
 */
export function formatarNota(valor: string | number | null | undefined): string {
	if (valor === null || valor === undefined || valor === '') return '—';
	return Number(valor).toLocaleString('pt-BR', {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2
	});
}

/**
 * A linha do barema como o edital a escreve.
 *
 * `1.3 - Docência no ensino superior - 0,50 pts/semestre - Limite: 3,00`.
 * É o cabeçalho sob o qual o candidato lança, e o mesmo texto que a
 * comissão lê na análise — por isso mora aqui, e não dentro de uma tela.
 */
export function rotuloDoItem(item: {
	code: string;
	text: string;
	points_per_unit: string;
	unit_label: string;
	cap: string;
}): string {
	const unidade = item.unit_label.toLocaleLowerCase('pt-BR');
	return `${item.code} - ${item.text} - ${formatarNota(item.points_per_unit)} pts/${unidade} - Limite: ${formatarNota(item.cap)}`;
}

/**
 * O questionário do edital, na ordem em que ele é respondido.
 *
 * São oito afirmações. A primeira é a **chave** (`has_paid_activity`): dela
 * dependem o rendimento e a carga horária, e é ela que joga o candidato do
 * bloco 2.1 para o 2.4. As demais escolhem o inciso — mas quem deriva a
 * faixa é o servidor (`ScholarshipApplication.band()`), e a tela nunca
 * repete essa conta: ela lê `band` já resolvido na resposta.
 *
 * `documento` é o `ApplicationDocumentKind` que aquele "Sim" passa a exigir.
 * O valor é o mesmo texto do campo de propósito — é assim no backend
 * (`RESPOSTA_QUE_EXIGE_DOCUMENTO`) —, e o que diz se o anexo ainda falta
 * continua sendo o `pending_docs` que vem do servidor.
 */
export type CampoDoQuestionario =
	| 'has_paid_activity'
	| 'affirmative_action'
	| 'socioeconomic_vulnerability'
	| 'cadastro_unico'
	| 'substitute_teacher'
	| 'basic_education_or_collective_health'
	| 'public_service'
	| 'private_service'
	| 'other_non_public_scholarship';

export type TipoDeComprovante = components['schemas']['ApplicationDocumentKind'];

export type Pergunta = {
	campo: CampoDoQuestionario;
	rotulo: string;
	ajuda?: string;
	documento?: TipoDeComprovante;
};

export const QUESTIONARIO: Pergunta[] = [
	{
		campo: 'has_paid_activity',
		rotulo: 'Exerço atividade remunerada',
		ajuda:
			'É a chave do questionário: marcando aqui, o rendimento mensal e a carga horária semanal passam a ser obrigatórios.'
	},
	{
		campo: 'affirmative_action',
		rotulo: 'Ingressei no programa por ação afirmativa',
		documento: 'affirmative_action'
	},
	{
		campo: 'socioeconomic_vulnerability',
		rotulo: 'Declaro vulnerabilidade socioeconômica',
		documento: 'socioeconomic_vulnerability'
	},
	{
		campo: 'cadastro_unico',
		rotulo: 'Sou inscrito no CadÚnico',
		ajuda: 'Critério de desempate (item 3.3 do edital). Não pede comprovante.'
	},
	{
		campo: 'substitute_teacher',
		rotulo: 'Sou professor substituto',
		documento: 'substitute_teacher'
	},
	{
		campo: 'basic_education_or_collective_health',
		rotulo: 'Atuo na educação básica ou em saúde coletiva',
		documento: 'basic_education_or_collective_health'
	},
	{
		campo: 'public_service',
		rotulo: 'Tenho vínculo com o serviço público',
		documento: 'public_service'
	},
	{
		campo: 'private_service',
		rotulo: 'Tenho vínculo com o serviço privado',
		documento: 'private_service'
	},
	{
		campo: 'other_non_public_scholarship',
		rotulo: 'Recebo outra bolsa não pública',
		documento: 'other_non_public_scholarship'
	}
];

/**
 * O recurso, nas duas palavras que a fila da análise usa.
 *
 * `EstadoDoRecurso` é derivado no servidor (`appeal_state()`) e não é campo
 * de model nenhum: ele existe porque a comissão trabalha a fila por estado
 * ("quem recorreu e ainda não foi julgado"), e filtrar por `outcome` não
 * distinguiria "sem recurso" de "recurso pendente" — os dois têm `outcome`
 * nulo. `ResultadoDoRecurso` é o julgamento em si.
 *
 * As duas listas moram aqui pela mesma razão das demais: são opções que o
 * filtro e o formulário de julgamento desenham **antes** de existir o
 * objeto. O rótulo do recurso já julgado continua vindo resolvido do
 * servidor (`outcome_label`).
 */
export type EstadoDoRecurso = components['schemas']['AppealState'];
export type ResultadoDoRecurso = components['schemas']['AppealOutcome'];

export const ESTADOS_DO_RECURSO: { valor: EstadoDoRecurso; rotulo: string }[] = [
	{ valor: 'none', rotulo: 'Sem recurso' },
	{ valor: 'pending', rotulo: 'Interposto, não julgado' },
	{ valor: 'judged', rotulo: 'Julgado' }
];

export const RESULTADOS_DO_RECURSO: { valor: ResultadoDoRecurso; rotulo: string }[] = [
	{ valor: 'granted', rotulo: 'Deferido' },
	{ valor: 'partially_granted', rotulo: 'Parcialmente deferido' },
	{ valor: 'denied', rotulo: 'Indeferido' }
];

/** Extensões que o comprovante do questionário aceita (o barema só aceita PDF). */
export const ACEITA_DOCUMENTO = '.pdf,.jpg,.jpeg,.png';
export const ACEITA_COMPROVANTE = '.pdf';
