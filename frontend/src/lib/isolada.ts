import type { components } from './api/schema';

/**
 * Vocabulário do edital de disciplina isolada, num lugar só.
 *
 * Rótulo não é regra de negócio: QUAIS documentos o edital exige e QUAL a
 * situação do requerimento continuam sendo resposta do servidor
 * (`missing_documents`, `status`, `payment_status`). O que mora aqui é
 * como escrever esses valores em português e em que ordem exibi-los — e
 * mora fora das telas porque a inscrição (US-016), o acompanhamento
 * (US-017) e a análise da secretaria (US-019) precisam dizer o mesmo.
 */

export type TipoDeDocumento = components['schemas']['RequestDocumentKind'];

export const ROTULO_DO_DOCUMENTO: Record<string, string> = {
	identity: 'Identidade e CPF',
	diploma: 'Diploma de graduação ou certidão de conclusão',
	lattes: 'Currículo Lattes em PDF',
	address: 'Comprovante de endereço',
	payslip: 'Contracheque de servidor da UFMG',
	supervisor_auth: 'Autorização da chefia',
	payment_receipt: 'Comprovante de pagamento da GRU'
};

/** Documentação da inscrição, na ordem em que o edital a lista. */
export const ORDEM_DO_EDITAL: TipoDeDocumento[] = [
	'identity',
	'diploma',
	'lattes',
	'address',
	'payslip',
	'supervisor_auth'
];

/** As mesmas palavras do edital — nada de "aprovado" ou "pendente". */
export const ROTULO_DA_SITUACAO: Record<string, string> = {
	draft: 'Rascunho',
	submitted: 'Inscrito',
	deferred: 'Deferido',
	rejected: 'Indeferido',
	cancelled: 'Cancelado',
	enrolled: 'Matriculado'
};

export const ROTULO_DO_PAGAMENTO: Record<string, string> = {
	pending: 'Pendente',
	paid: 'Pago',
	exempt: 'Isento'
};

/** Data e hora de prazo, como o edital as publica. */
export function formatarPrazo(iso: string | null): string {
	if (iso === null) return '—';
	return new Date(iso).toLocaleString('pt-BR', {
		dateStyle: 'short',
		timeStyle: 'short'
	});
}

export function formatarTamanho(bytes: number): string {
	return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
