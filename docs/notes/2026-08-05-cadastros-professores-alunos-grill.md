# Cadastros básicos: Professores e Alunos — Grill / Discovery Notes
Date: 2026-08-05 · Goal: extrair do usuário o desenho completo dos cadastros
básicos de Professor (docente) e Aluno (discente) no PPGD Manager, para
virar a base do próximo módulo de negócio sobre a fundação de
Person/Program/User já existente.

## Contexto já lido no código (não perguntar de novo)
- `Program` (app `programs`): tenant, tem `name`, `acronym` (unique), `is_active`.
- `Person` (app `people`): identidade genérica por programa. Tem `full_name`,
  `primary_email`, `phone_number`, `status` (ACTIVE/ARCHIVED), FK opcional
  para `User` (conta de acesso), FK obrigatória para `Program`. Unique
  (program, primary_email) e (program, user).
- `User` (app `accounts`): subclasse vazia de `AbstractUser`, global, sem
  programa.
- Ainda não existe nenhum model de Professor ou Aluno no código.

## Summary / key decisions
- Novo app `academic` com dois models: `Teacher` (docente) e `Student`
  (discente), cada um em relação 1:1 com `Person`.
- Convenção de código: identificadores (model/campo) em INGLÊS, comentários
  e `verbose_name`/`choices` em português — igual ao padrão já usado em
  Person/Program/User. Não criar exceção de idioma para este app.
- Fluxo: terminar o levantamento de campos/regras primeiro, implementar tudo
  de uma vez no final (evita migração retrabalhada).

## Q&A log

### Q1 — onde Professor e Aluon entram na modelagem
- Asked: Person já é a identidade genérica; Teacher/Student deveriam ser
  models próprios em 1:1 com Person, num novo app `academic`?
- Captured: Confirmado. App `academic`, models `Teacher` e `Student`, 1:1
  com `Person`.
- Flags: nenhum.

### Q1b — idioma dos identificadores no código (clarificação)
- Asked: "faça o código em pt br" significa identificadores em português
  ou manter o padrão (inglês nos nomes, português em comentários/labels)?
- Captured: Manter o padrão atual — inglês nos nomes de model/campo,
  português em comentários e verbose_name/choices.
- Flags: nenhum.

### Q2 — categoria do docente (CAPES)
- Asked: Teacher.category como TextChoices PERMANENT/COLLABORATOR/VISITING
  (Permanente/Colaborador/Visitante)?
- Captured: Confirmado, exatamente essas três categorias.
- Flags: nenhum.

### Q3 — credenciamento (datas e histórico)
- Asked: sem tabela de histórico agora — só `accredited_since` (data) e
  `accredited_until` (data, opcional) em Teacher?
- Captured: Confirmado. Sem histórico por enquanto, só os dois campos.
- Flags: se precisar de histórico de mudança de categoria (relatório CAPES
  retroativo), é model novo futuro com ADR -> revisitar quando surgir a
  necessidade.

### Q4 — demais campos de Teacher
- Asked: academic_degree (titulação), lattes_url (opcional), research_area
  (texto livre inicialmente), home_institution (instituição de origem,
  relevante p/ Colaborador/Visitante)?
- Captured: Lista de campos aceita (academic_degree, lattes_url,
  home_institution confirmados). MAS: usuário revelou que o programa se
  divide em "linhas de pesquisa" com vários "projetos coletivos" cada —
  isso invalida `research_area` como texto livre.
- Flags: virou pergunta Q4b.

### Q4b — modelar Linha de Pesquisa como entidade própria?
- Asked: ResearchLine (FK Program) + CollectiveProject (FK ResearchLine),
  Teacher.research_line vira FK em vez de texto?
- Captured: Confirmado. Modelar AGORA: ResearchLine 1 -> N CollectiveProject.
- Flags: falta decidir em qual app (programs vs academic) e se
  Teacher/Student referenciam ResearchLine, CollectiveProject, ou ambos.

### Q4c — app e cardinalidade de ResearchLine/CollectiveProject
- Asked: ResearchLine/CollectiveProject no app `programs`; Teacher -> FK
  ResearchLine, Student -> FK CollectiveProject (linha implícita via projeto)?
- Captured: CORRIGIDO pelo usuário. Cardinalidades reais:
  - `CollectiveProject` sempre pertence a exatamente 1 `ResearchLine` (FK
    obrigatória, projeto -> linha).
  - `Teacher` pode estar em **mais de uma** `ResearchLine` **e** mais de um
    `CollectiveProject` — são relações M2M independentes (não é
    "professor está na linha do projeto que participa", são dois vínculos
    separados: participação em linhas + participação em projetos).
  - `Student` está vinculado a **exatamente um** `CollectiveProject`
    (FK obrigatória, not null). Linha do aluno é implícita via
    `student.project.research_line`.
- Flags: app de moradia (programs vs academic) ainda não confirmado
  explicitamente pelo usuário nesta resposta -> assumir `programs` (não
  contestado) e confirmar antes de codar.

### Q4d — confirmação de app
- Asked: ResearchLine/CollectiveProject no app `programs`?
- Captured: Confirmado.
- Flags: nenhum.

### Q5 — nível do curso do aluno
- Asked: Student.level como TextChoices MASTERS/DOCTORATE (+ profissional?)?
- Captured: Confirmado só MASTERS e DOCTORATE por enquanto. Sem mestrado
  profissional agora.
- Flags: se mestrado profissional entrar no futuro, é choice novo + revisão
  de prazo regimental — não é mudança estrutural.

### Q6 — matrícula e data de ingresso
- Asked: registration_number (matrícula) texto livre único por programa +
  admission_date obrigatória?
- Captured: CORREÇÃO IMPORTANTE DE ESCOPO pelo usuário.
  - `registration_number` é o número de matrícula GLOBAL da UFMG. A
    universidade cadastra o aluno e atribui esse número — o PPGD Manager
    só ARMAZENA (texto livre, não gera, não valida formato específico).
  - "Matrícula" no jargão interno da secretaria = atribuir/ajustar
    DISCIPLINAS do aluno em cada período. Isso é feito e mantido no
    sistema oficial da UFMG (fora do nosso sistema) — aluno escolhe
    disciplinas lá, orientador aprova lá. NÃO é responsabilidade do PPGD
    Manager reproduzir isso.
  - O que o PPGD Manager PRECISA modelar (futuro módulo, fora de
    "cadastros básicos"): workflow interno de **"acerto de matrícula"** —
    quando o aluno precisa mudar disciplinas (excluir uma, incluir outra)
    depois de já matriculado na UFMG. Fluxo: aluno abre solicitação no
    nosso sistema (informa as alterações) -> orientador aprova no nosso
    sistema -> secretaria, ao ver aprovado, replica manualmente a mudança
    no sistema da UFMG (fora do nosso sistema, ação humana). Se não há
    necessidade de acerto, o fluxo nem existe/nem passa pela secretaria.
- Flags: workflow de "acerto de matrícula" (SolicitacaoAcertoMatricula ou
  similar, com estados: aberta -> aprovada pelo orientador -> replicada
  pela secretaria) É UM MÓDULO DE NEGÓCIO FUTURO, fora do escopo desta
  sessão de cadastros básicos. Mas confirma que Student PRECISA de FK para
  orientador (Teacher) desde já, porque esse workflow depende disso.

### Q7 — orientador
- Asked: Student.advisor FK -> Teacher (PROTECT); só 1 orientador (sem
  coorientador) por agora?; obrigatório na criação ou pode ficar em branco?
- Captured: Confirmado. Só `advisor` (sem co_advisor por enquanto,
  `null=True, blank=True`). Aluno PODE ser cadastrado sem orientador —
  campo opcional na criação, definido depois.
- Flags: coorientador fica como possível campo futuro se a necessidade
  aparecer.

### Q8 — situação do aluno
- Asked: Student.status próprio (REGULAR/LEAVE/DEFENDED/DISCONTINUED) +
  regras de transição bloqueada?
- Captured: CORRIGIDO pelo usuário — valores reais usados no PPGD/UFMG:
  REGULAR, TRANCADO, ISOLADA, ELETIVA, EXCLUÍDO (nomes exatos do usuário,
  em português — usar como `choices` com identificador em inglês/ASCII e
  label em português, ex.: REGULAR/"Regular", LEAVE/"Trancado",
  ISOLATED/"Isolada", ELECTIVE/"Eletiva", EXCLUDED/"Excluído").
- Flags: pergunta sobre regras de transição bloqueada AINDA NÃO
  RESPONDIDA — repetir na próxima pergunta.

### Q9 — regras de transição de status
- Asked: alguma transição bloqueada, ou troca livre?
- Captured: Troca livre por enquanto, sem invariante no model. Só precisa
  ficar em AuditLog (já é o padrão do projeto para toda escrita relevante).
- Flags: se surgir regra de transição no futuro, adiciona método tipo
  Person.archive() na hora — sem antecipar agora.

### Q10 — prazos regimentais
- Asked: expected_deadline / defense_date fazem parte do cadastro básico?
- Captured: Sim, controlar prazo final.

### Q10b — prazo calculado ou editável
- Asked: Student.deadline armazenado e editável, ou calculado on-the-fly?
- Captured: Confirmado — calculável (default automático) MAS editável
  (secretaria pode prorrogar). `defense_date` opcional/nula até a defesa
  ocorrer — não contestado, considerar confirmado por ausência de objeção.

### Q10c — regra do prazo padrão
- Asked: quantos meses de admission_date pro deadline default, por nível?
- Captured: 24 meses mestrado (MASTERS), 48 meses doutorado (DOCTORATE).
  Calcular no `save()`/método do model como default inicial quando
  `deadline` não for informado; depois de criado, é editável livremente
  pela secretaria (prorrogação = editar o campo).

### Q11 — CPF e dados pessoais adicionais
- Asked: CPF/data de nascimento entram no cadastro básico agora?
- Captured: NÃO. CPF fica de fora por enquanto — adicionar quando um
  módulo concreto precisar (ex.: emissão de diploma), evitando dado
  sensível (LGPD) sem uso real hoje.
- Flags: nenhum.

### Q12 — bolsa
- Asked: dado de bolsa (agência/tipo) entra no cadastro básico agora?
- Captured: NÃO. Fora de escopo por enquanto.
- Flags: nenhum.

### Q13 — permissões
- Asked: Secretaria cadastra/edita Teacher e Student; Coordenação só lê?
- Captured: Confirmado exatamente assim. Secretaria = add/change nos dois
  models; Coordenação = view apenas.
- Flags: implementar via Group nativo do Django (padrão já definido no
  CLAUDE.md Seção 5), checagem explícita via `require_perm` no router.

### Q14 — dados legados / origem do cadastro
- Asked: existe import de sistema/planilha anterior, ou começa vazio?
- Captured: Revelou módulo futuro maior — PROCESSO SELETIVO:
  1. Candidato se inscreve no processo seletivo, preenche dados e
     documentos (upload).
  2. Secretaria (FUTURO — ainda não implementado) escolhe aprovados e
     "converte" inscrito em Student.
  3. Secretaria envia os aprovados pra UFMG; UFMG gera o número de
     registro (matrícula global).
  4. Secretaria preenche `registration_number` no sistema interno quando
     a UFMG devolve o número.
  Confirma (por decorrência): `Student.registration_number` PRECISA ser
  opcional (`null=True, blank=True`) — não existe no momento da criação,
  só é preenchido depois que a UFMG responde.
- Flags: "Processo Seletivo" (Candidate/Applicant, documentos, aprovação,
  conversão em Student) é MÓDULO DE NEGÓCIO FUTURO, fora do escopo de
  hoje. Hoje o cadastro básico de Student é feito diretamente pela
  secretaria (entrada manual via tela), sem o fluxo de seleção. Não há
  import de sistema legado a fazer agora — não foi mencionado nenhum
  sistema anterior com dados pra migrar.

## Open flags (pending input)
- Histórico de mudança de categoria docente ao longo do tempo -> não
  implementado agora; revisitar se exigido por relatório CAPES.
- Significado exato de "ISOLADA" e "ELETIVA" como status de aluno (parecem
  termos específicos da UFMG) -> por ora só armazenar o valor, sem regra
  atrelada; sem impacto na implementação de hoje.
- MÓDULO FUTURO (fora do escopo de hoje): workflow de "acerto de
  matrícula" (solicitação do aluno -> aprovação do orientador -> secretaria
  replica no sistema da UFMG). Guardar esta nota para quando for grillar
  esse módulo especificamente.
- Coorientador (Student.co_advisor) -> não implementado agora, campo
  futuro se necessário.
