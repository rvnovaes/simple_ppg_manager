import type { components } from './api/schema';

/**
 * Vocabulário do cadastro no programa, num lugar só — espelho de
 * `lib/isolada.ts` para o autocadastro.
 *
 * Rótulo não é regra de negócio: QUEM precisa de confirmação, QUAIS campos
 * cada perfil exige e QUAL a situação da solicitação continuam sendo
 * resposta do servidor (`requires_confirmation`, o 422 do `AccessSignupIn`,
 * `status`). O que mora aqui é como escrever esses valores em português e
 * em que ordem exibi-los — e mora fora das telas porque o cadastro
 * (f6-tela-cadastro) e a fila da secretaria (f6-tela-solicitacoes)
 * precisam dizer o mesmo.
 *
 * A tela de espera (`(auth)/aguardando-confirmacao`) é a exceção de
 * propósito: ela lê `profile_label`/`status_label` prontos do
 * `AccessStatusOut`, porque quem chega lá não tem permissão nenhuma e não
 * deve depender de a tabela do front estar em dia.
 */

export type Perfil = components['schemas']['AccessProfile'];
export type CategoriaDocente = components['schemas']['Category'];
export type Titulacao = components['schemas']['AcademicDegree'];
export type SituacaoDoCadastro = components['schemas']['AccessRequestStatus'];

export const ROTULO_DO_PERFIL: Record<Perfil, string> = {
	candidate: 'Candidato',
	student: 'Discente',
	teacher: 'Docente'
};

/** Ordem do menos comprometido ao mais: quem só concorre, quem cursa, quem ensina. */
export const ORDEM_DOS_PERFIS: Perfil[] = ['candidate', 'student', 'teacher'];

export const ROTULO_DA_CATEGORIA: Record<CategoriaDocente, string> = {
	permanent: 'Permanente',
	collaborator: 'Colaborador',
	visiting: 'Visitante',
	external: 'Colaborador externo'
};

export const ORDEM_DAS_CATEGORIAS: CategoriaDocente[] = [
	'permanent',
	'collaborator',
	'visiting',
	'external'
];

export const ROTULO_DA_TITULACAO: Record<Titulacao, string> = {
	doctorate: 'Doutorado',
	postdoctorate: 'Pós-doutorado',
	habilitation: 'Livre-docência'
};

export const ORDEM_DAS_TITULACOES: Titulacao[] = ['doctorate', 'postdoctorate', 'habilitation'];

/** As palavras da secretaria — a solicitação é "confirmada", não "aprovada". */
export const ROTULO_DA_SITUACAO: Record<SituacaoDoCadastro, string> = {
	pending: 'Aguardando confirmação',
	approved: 'Confirmado',
	rejected: 'Não confirmado'
};

export const ORDEM_DAS_SITUACOES: SituacaoDoCadastro[] = ['pending', 'approved', 'rejected'];

/**
 * A única categoria que exige instituição de origem — mesma regra do
 * `campos_do_perfil` de `AccessSignupIn`, que é quem a cobra de verdade.
 */
export function exigeInstituicaoDeOrigem(categoria: CategoriaDocente | ''): boolean {
	return categoria === 'external';
}
