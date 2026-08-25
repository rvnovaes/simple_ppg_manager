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

/**
 * Espelho de `ApplicationDocumentKind` (`apps/selection/models.py`).
 *
 * O valor é também o **nome do campo** no POST público: `ApplicationIn`
 * recebe um `File(...)` por tipo de documento, com o mesmo identificador.
 * Percorrer esta lista é o que faz a tela montar o `<input type="file">`
 * certo sem repetir os sete nomes em cada lugar.
 */
export type TipoDeDocumentoDaInscricao =
	| 'identity'
	| 'diploma'
	| 'lattes'
	| 'payment_receipt'
	| 'expanded_abstract'
	| 'memorial'
	| 'quota_proof';

export const ROTULO_DO_DOCUMENTO_DA_INSCRICAO: Record<TipoDeDocumentoDaInscricao, string> = {
	identity: 'Documento de identidade',
	diploma: 'Diploma',
	lattes: 'Currículo Lattes',
	payment_receipt: 'Comprovante de pagamento',
	expanded_abstract: 'Resumo expandido',
	memorial: 'Memorial',
	quota_proof: 'Comprovação da cota'
};

/**
 * Espelho de `Application.required_document_kinds()`.
 *
 * Cópia deliberada, como `COTAS_POR_TIPO`: a tela precisa desenhar os
 * campos de anexo antes de existir inscrição alguma. Quem recusa o envio
 * incompleto continua sendo o backend (`missing_documents`) — se as duas
 * listas divergirem, o erro aparece como `missing_documents` no POST, e é
 * aqui que se conserta.
 */
export function documentosExigidos(tipo: Tipo, cota: Cota): TipoDeDocumentoDaInscricao[] {
	const exigidos: TipoDeDocumentoDaInscricao[] = [
		'identity',
		'diploma',
		'lattes',
		'payment_receipt',
		tipo === 'regular' ? 'expanded_abstract' : 'memorial'
	];
	if (cota !== 'open') exigidos.push('quota_proof');
	return exigidos;
}

export type SituacaoDaInscricao = components['schemas']['ApplicationStatus'];

/**
 * O que cada situação significa para quem consulta o protocolo.
 *
 * O rótulo curto vem do servidor (`status_label`) — não se traduz aqui o
 * que ele já traduz. O que mora nesta tabela é a frase que explica o
 * rótulo a quem não conhece o vocabulário do edital.
 */
export const EXPLICACAO_DA_SITUACAO: Record<SituacaoDaInscricao, string> = {
	submitted: 'Recebemos sua inscrição. A secretaria ainda vai conferir a documentação.',
	homologated: 'Documentação conferida: você está apto a participar das etapas do edital.',
	rejected: 'A inscrição não foi homologada. A secretaria informa o motivo pelos canais do edital.',
	eliminated: 'Você não seguiu para a etapa seguinte do processo seletivo.',
	approved: 'Você foi aprovado. Acompanhe a convocação para a matrícula.',
	enrolled: 'Matrícula efetivada: você já consta como aluno do programa.'
};

/**
 * As situações na ordem em que a inscrição as percorre.
 *
 * O rótulo curto continua vindo do servidor (`status_label`) em toda linha
 * que tenha uma inscrição na mão; esta tabela existe para o `<select>` do
 * filtro, que precisa escrever a situação sem ter nenhuma inscrição para
 * perguntar.
 */
export const SITUACOES_DA_INSCRICAO: SituacaoDaInscricao[] = [
	'submitted',
	'homologated',
	'rejected',
	'eliminated',
	'approved',
	'enrolled'
];

export const ROTULO_DA_SITUACAO_DA_INSCRICAO: Record<SituacaoDaInscricao, string> = {
	submitted: 'Inscrita',
	homologated: 'Homologada',
	rejected: 'Indeferida',
	eliminated: 'Eliminada',
	approved: 'Aprovada',
	enrolled: 'Matriculada'
};

/** CPF como o candidato o escreveu no documento: 000.000.000-00. */
export function formatarCpf(cpf: string): string {
	const digitos = cpf.replace(/\D/g, '');
	if (digitos.length !== 11) return cpf;
	return `${digitos.slice(0, 3)}.${digitos.slice(3, 6)}.${digitos.slice(6, 9)}-${digitos.slice(9)}`;
}

export type SituacaoDaAta = components['schemas']['RecordStatus'];

/**
 * As situações da ata na ordem em que ela as percorre.
 *
 * Mesma razão de `SITUACOES_DA_INSCRICAO`: o rótulo curto vem do servidor
 * (`status_label`) em toda linha que tenha uma ata na mão, e esta tabela
 * existe para o `<select>` do filtro, que escreve a situação sem ter ata
 * nenhuma para perguntar.
 */
export const SITUACOES_DA_ATA: SituacaoDaAta[] = [
	'draft',
	'awaiting_signatures',
	'signed',
	'superseded'
];

export const ROTULO_DA_SITUACAO_DA_ATA: Record<SituacaoDaAta, string> = {
	draft: 'Rascunho',
	awaiting_signatures: 'Aguardando assinaturas',
	signed: 'Assinada',
	superseded: 'Substituída'
};

/**
 * O que cada situação da ata significa para quem está na banca.
 *
 * O rótulo curto vem do servidor (`status_label`), como em toda parte deste
 * módulo; o que mora aqui é a frase que diz ao examinador o que ele ainda
 * pode (ou não pode) fazer naquele estado — a diferença entre "rascunho" e
 * "aguardando assinaturas" é justamente essa, e ela não cabe num rótulo.
 */
export const EXPLICACAO_DA_SITUACAO_DA_ATA: Record<SituacaoDaAta, string> = {
	draft:
		'Rascunho: as notas ainda podem mudar, e a ata acompanha. Quem preside congela quando a etapa terminar.',
	awaiting_signatures:
		'Congelada: as notas desta chave viraram só leitura e o texto abaixo é o que cada examinador assina.',
	signed: 'Assinada por todos: os desfechos da etapa foram aplicados e o PDF da ata foi gravado.',
	superseded: 'Substituída por uma versão posterior, guardada como histórico.'
};

/**
 * A nota como a ata a escreve: número, "ausente" ou travessão.
 *
 * A API devolve `score` como **string** (é `Decimal` no banco, e virar
 * `number` no JSON perderia a casa decimal exata que a ata registra). Esta
 * função existe para nenhuma tela ser tentada a fazer `Number(score)` só
 * para exibir.
 */
export function formatarNota(nota: string | null, ausente: boolean): string {
	if (ausente) return 'Ausente';
	if (nota === null || nota === '') return '—';
	return nota;
}

/**
 * Se este examinador da banca é a conta logada.
 *
 * O casamento é pelo nome da pessoa: `BoardMemberOut.full_name` sai de
 * `Teacher.person.full_name`, e `UserOut.people` traz as pessoas da conta —
 * mas nenhuma das duas expõe o id do `Teacher`, então o nome é o que há.
 *
 * Por isso o resultado é **dica de tela, e não autorização**: com dois
 * homônimos na mesma banca ele erraria. Quem decide continua sendo o
 * backend (`not_the_board_president`, `not_the_signer`, `not_a_titular_member`),
 * e a tela mostra o erro dele — nunca esconde a ação a ponto de a pessoa
 * certa não conseguir agir.
 */
export function ehAContaLogada(
	nomeDoExaminador: string,
	pessoasDaConta: { full_name: string }[]
): boolean {
	return pessoasDaConta.some((pessoa) => pessoa.full_name === nomeDoExaminador);
}

export type EspecieDeRealocacao = components['schemas']['ReallocationKind'];

/**
 * Espelho de `ReallocationKind` (`apps/selection/models.py`).
 *
 * O rótulo curto do servidor (`kind_label`) chega em toda realocação já
 * gravada; esta tabela existe para o `<select>` do formulário, que precisa
 * escrever a espécie **antes** de existir a realocação — e para a frase que
 * explica o que cada uma pode mover, que não cabe num rótulo.
 */
export const ESPECIES_DE_REALOCACAO: {
	valor: EspecieDeRealocacao;
	rotulo: string;
	explicacao: string;
}[] = [
	{
		valor: 'level_transfer',
		rotulo: 'Transferência entre níveis',
		explicacao: 'Mesmo alvo e mesma cota, de mestrado para doutorado (ou o contrário).'
	},
	{
		valor: 'notice_rectification',
		rotulo: 'Retificação de edital',
		explicacao: 'Mesmo nível e mesma cota, de um alvo para outro.'
	}
];

/**
 * A vaga como o `<select>` da realocação a escreve.
 *
 * Nível, alvo, cota e o saldo **de agora** — que é o que a comissão precisa
 * ver para não pedir mais do que existe (`insufficient_balance` é do
 * servidor, e continua sendo dele a última palavra).
 */
export function rotuloDaVaga(vaga: {
	level_label: string;
	target_label: string;
	quota_category_label: string;
	quantity: number;
}): string {
	return `${vaga.level_label} · ${vaga.target_label} · ${vaga.quota_category_label} (${vaga.quantity})`;
}
