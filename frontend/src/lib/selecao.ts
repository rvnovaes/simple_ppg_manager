import type { components } from './api/schema';

/**
 * Vocabulário do processo seletivo, num lugar só.
 *
 * Molde de `lib/isolada.ts`, e pela mesma razão: rótulo não é regra de
 * negócio, mas precisa ser escrito igual no edital (US f1), na banca, na
 * inscrição e no resultado. QUAIS categorias de cota cada tipo de edital
 * aceita é resposta do servidor (`quota_category_not_allowed`); o que mora
 * aqui é a cópia usada para montar a grade antes de mandar o POST.
 */

export type Tipo = components['schemas']['SelectionKind'];
export type SituacaoDoEdital = components['schemas']['SelectionProcessStatus'];
export type Nivel = components['schemas']['SelectionLevel'];
export type Cota = components['schemas']['QuotaCategory'];

export const ROTULO_DO_TIPO: Record<Tipo, string> = {
	regular: 'Regular',
	supplementary: 'Suplementar'
};

export const ROTULO_DA_SITUACAO_DO_EDITAL: Record<SituacaoDoEdital, string> = {
	draft: 'Rascunho',
	published: 'Publicado',
	closed: 'Encerrado'
};

export const ROTULO_DO_NIVEL: Record<Nivel, string> = {
	masters: 'Mestrado',
	doctorate: 'Doutorado'
};

/** Na ordem em que a grade de vagas mostra as colunas. */
export const NIVEIS: Nivel[] = ['masters', 'doctorate'];

export const ROTULO_DA_COTA: Record<Cota, string> = {
	open: 'Ampla concorrência',
	racial: 'Cota racial',
	disability: 'Pessoa com deficiência',
	quilombola: 'Quilombola',
	trans: 'Pessoa trans',
	indigenous: 'Indígena'
};

/**
 * Espelho de `CATEGORIAS_POR_TIPO` (`apps/selection/models.py`).
 *
 * Cópia deliberada: a tela precisa saber quais colunas desenhar antes de
 * existir uma vaga sequer. Quem recusa a combinação errada continua sendo o
 * backend (`ensure_quota_category`).
 */
export const COTAS_POR_TIPO: Record<Tipo, Cota[]> = {
	regular: ['open', 'racial'],
	supplementary: ['disability', 'quilombola', 'trans', 'indigenous']
};

/** O Regular chaveia por projeto coletivo; o Suplementar, por linha (P4). */
export function alvoDoTipo(tipo: Tipo): 'projeto' | 'linha' {
	return tipo === 'regular' ? 'projeto' : 'linha';
}

/**
 * Espelho de `PLACEHOLDERS_DE_CONVOCACAO` (`apps/selection/models.py`).
 *
 * A lista existe para a tela dizer à secretaria o que ela pode escrever no
 * template — quem renderiza (e tolera placeholder desconhecido) é o
 * servidor.
 */
export const PLACEHOLDERS_DE_CONVOCACAO: { chave: string; explicacao: string }[] = [
	{ chave: 'nome', explicacao: 'nome completo do candidato' },
	{ chave: 'protocolo', explicacao: 'protocolo da inscrição' },
	{ chave: 'etapa', explicacao: 'nome da etapa' },
	{ chave: 'data_hora', explicacao: 'data e hora da sessão' },
	{ chave: 'local', explicacao: 'local da sessão' },
	{ chave: 'edital', explicacao: 'título do edital' }
];

/** Data e hora como o edital as publica. */
export function formatarMomento(iso: string | null): string {
	if (iso === null || iso === '') return '—';
	return new Date(iso).toLocaleString('pt-BR', {
		dateStyle: 'short',
		timeStyle: 'short'
	});
}

/**
 * ISO do servidor -> valor de `<input type="datetime-local">`.
 *
 * O input não aceita fuso: ele fala no relógio de quem preenche. A conversão
 * nos dois sentidos mora aqui para o formulário mandar sempre ISO com fuso,
 * que é o que o schema Ninja recebe (mesmo par de `(app)/editais`).
 */
export function isoParaLocal(iso: string): string {
	const data = new Date(iso);
	const deslocado = new Date(data.getTime() - data.getTimezoneOffset() * 60_000);
	return deslocado.toISOString().slice(0, 16);
}

export function localParaIso(local: string): string {
	return new Date(local).toISOString();
}

/**
 * Os quatro lugares da banca, na ordem em que a ata os lista.
 *
 * Espelho de `Board.PAPEIS` (`apps/selection/models.py`). O nome do campo é
 * o mesmo do schema — `BoardOut` expande `president`/`member_1`/`member_2`/
 * `alternate`, e `BoardIn` recebe os `*_id` correspondentes —, então a tela
 * percorre esta lista em vez de repetir os quatro nomes em cada lugar.
 */
export type PapelDaBanca = 'president' | 'member_1' | 'member_2' | 'alternate';

export const PAPEIS_DA_BANCA: { campo: PapelDaBanca; rotulo: string }[] = [
	{ campo: 'president', rotulo: 'Presidente' },
	{ campo: 'member_1', rotulo: 'Titular 1' },
	{ campo: 'member_2', rotulo: 'Titular 2' },
	{ campo: 'alternate', rotulo: 'Suplente' }
];

/**
 * Como o examinador aparece num `<option>` ou na linha da banca.
 *
 * A instituição só entra quando ele é externo: é a única categoria em que
 * `home_institution` é obrigatória (`Teacher.clean`), e é justamente ali que
 * quem monta a banca precisa saber de onde a pessoa vem.
 */
export function rotuloDoExaminador(examinador: {
	full_name: string;
	category: string;
	home_institution: string;
}): string {
	const externo = examinador.category === 'external' && examinador.home_institution !== '';
	return externo
		? `${examinador.full_name} · ${examinador.home_institution}`
		: examinador.full_name;
}
