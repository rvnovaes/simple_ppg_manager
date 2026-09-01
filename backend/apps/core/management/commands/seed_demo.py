"""Carga de dados de demonstração — para testar o sistema à mão.

Não é fixture de teste: `pytest` monta o que precisa em cada arquivo, e
depender de uma carga compartilhada tornaria os testes acoplados a ela. O
que este comando resolve é o outro problema — abrir o :8080 e ter o que
olhar em toda tela, com todos os papéis e todos os estados dos dois
fluxos.

É idempotente: roda quantas vezes quiser, sempre em cima do mesmo
programa. Não apaga nada — dado que você criou à mão continua lá.

    make seed

O programa demo é identificado pela sigla (`--acronym`, por padrão PPGD).
Para montar um segundo tenant e conferir o isolamento, troque também o
domínio dos e-mails — o `User` é global, e repetir o e-mail daria à mesma
conta uma `Person` em cada programa, o que faz `current_program` passar a
exigir `program_id` em toda rota:

    uv run python manage.py seed_demo \\
        --acronym PPGA --name "Pós em Administração" --email-domain ppga.test
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academic.models import (
    DisciplineOffering,
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    RequestDocument,
    Student,
    Teacher,
)
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Discipline,
    Program,
    ResearchLine,
)
from apps.selection import services as selecao
from apps.selection.models import (
    Application,
    ApplicationDocument,
    ApplicationStatus,
    Board,
    Convocation,
    ExaminationRecord,
    QuotaCategory,
    RankingOutcome,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    SelectionStage,
    StageScore,
    Vacancy,
    gerar_protocolo,
)

User = get_user_model()

# Senha única para todas as contas da carga. Só existe porque a carga só
# roda com DEBUG=True (ou --force explícito) — em produção este comando
# recusa antes de escrever qualquer coisa.
SENHA_PADRAO = "demo@ppgd2026"

# Um PDF válido mínimo. Anexo de verdade não interessa aqui; o que
# interessa é o requerimento ter documentação completa, porque sem ela
# `submit()` recusa a inscrição.
PDF_MINIMO = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


# Ano do processo seletivo da carga (PS2027) — é o ano do ingresso, e não
# o ano em que o edital saiu. Fixo de propósito: a janela de inscrição é
# que é relativa ao instante da carga, para nunca nascer vencida.
ANO_DA_SELECAO = 2027

# Onde a carga escreve as contas que criou. Fica na raiz do repositório
# (o `BASE_DIR` é `backend/`) e é ignorado pelo git — são senhas conhecidas.
ARQUIVO_DE_CONTAS = "CONTAS-DEMO.txt"


@dataclass(frozen=True)
class InscricaoDemo:
    """Um candidato do processo seletivo e o estado em que ele nasce.

    `alvo` é o índice do projeto coletivo (edital Regular) ou o da linha
    de pesquisa (Suplementar) — quem escolhe entre os dois é o tipo do
    edital, exatamente como `SelectionProcess.ensure_target`.

    `nota` é a da **primeira** etapa: é ela que a ata da carga congela.
    `classificacao`/`desfecho` só existem para quem já nasce aprovado, que
    é o atalho para a tela de resultado ter conteúdo sem percorrer as três
    etapas de todas as chaves.
    """

    nome: str
    email: str
    nivel: str
    cota: str
    situacao: str
    alvo: int
    nota: Decimal | None = None
    motivo: str = ""
    classificacao: int | None = None
    desfecho: str = ""
    matricular: bool = False


@dataclass(frozen=True)
class CandidatoDemo:
    """Um candidato do edital e o estado em que ele deve nascer.

    Dataclass e não tupla porque são oito campos e a leitura da lista de
    definições é o que torna a carga revisável — `escolhas` casa a oferta
    com a posição que o docente deu, que é justamente o par que não pode
    sair de sincronia.
    """

    nome: str
    email: str
    situacao: str
    pagamento: str
    escolhas: list[tuple[DisciplineOffering, int | None]]
    servidor: bool = False
    motivo: str = ""


class Command(BaseCommand):
    help = "Popula o banco com uma carga de demonstração (idempotente)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--acronym",
            default="PPGD",
            help="Sigla do programa da carga (padrão: PPGD).",
        )
        parser.add_argument(
            "--name",
            default="Programa de Pós-Graduação em Direito",
            help="Nome do programa, usado só quando ele ainda não existe.",
        )
        parser.add_argument(
            "--password",
            default=SENHA_PADRAO,
            help=f"Senha das contas criadas (padrão: {SENHA_PADRAO}).",
        )
        parser.add_argument(
            "--email-domain",
            default="",
            help=(
                "Domínio dos e-mails, para carregar um segundo tenant sem "
                "colidir com o primeiro (ex.: ppga.test). O User é global: "
                "repetir o e-mail entre programas dá à mesma conta duas "
                "Person, e aí toda rota passa a exigir program_id."
            ),
        )
        parser.add_argument(
            "--email-backend",
            default="django.core.mail.backends.console.EmailBackend",
            help=(
                "Backend de e-mail durante a carga. O padrão é o console "
                "porque a carga dispara uma convocação de verdade e o SMTP "
                "do canteiro nem sempre está de pé quando o comando roda no "
                "host. Passe uma string vazia para respeitar o EMAIL_BACKEND "
                "do ambiente (é assim que a mensagem cai no Mailpit)."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Roda mesmo com DEBUG=False. Você está por sua conta.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_demo cria contas com senha conhecida e só roda com "
                "DEBUG=True. Use --force se você sabe o que está fazendo."
            )

        self.senha = options["password"]
        self.dominio = options["email_domain"]
        self.criadas: dict[str, int] = {}

        if options["email_backend"]:
            settings.EMAIL_BACKEND = options["email_backend"]

        with transaction.atomic():
            programa = self._programa(options["acronym"], options["name"])
            linhas = self._linhas(programa)
            projetos = self._projetos(programa, linhas)
            disciplinas = self._disciplinas(programa)
            periodos = self._periodos()
            equipe = self._equipe(programa)
            docentes = self._docentes(programa, linhas, projetos)
            alunos = self._alunos(programa, projetos, docentes, periodos)
            self._acertos(programa, alunos, disciplinas, periodos)
            ciclo, ofertas = self._ciclo(programa, disciplinas, docentes, periodos)
            self._requerimentos(programa, ciclo, ofertas, periodos)
            self._selecao(programa, linhas, projetos, docentes)

        self._relatar(programa, equipe)

    # ------------------------------------------------------------------
    # Estrutura do programa
    # ------------------------------------------------------------------

    def _programa(self, acronym: str, name: str) -> Program:
        programa, criado = Program.objects.get_or_create(
            acronym=acronym,
            defaults={"name": name},
        )
        self._contar("programa", criado)
        return programa

    def _linhas(self, programa: Program) -> list[ResearchLine]:
        nomes = [
            "Direito e Instituições Políticas",
            "Direitos Humanos e Estado Democrático",
        ]
        linhas = []
        for nome in nomes:
            linha, criado = ResearchLine.objects.get_or_create(
                program=programa, name=nome
            )
            self._contar("linha de pesquisa", criado)
            linhas.append(linha)
        return linhas

    def _projetos(
        self, programa: Program, linhas: list[ResearchLine]
    ) -> list[CollectiveProject]:
        definicoes = [
            (linhas[0], "Controle de Constitucionalidade e Jurisdição"),
            (linhas[0], "Federalismo e Repartição de Competências"),
            (linhas[1], "Acesso à Justiça e Vulnerabilidades"),
        ]
        projetos = []
        for linha, nome in definicoes:
            projeto, criado = CollectiveProject.objects.get_or_create(
                program=programa,
                research_line=linha,
                name=nome,
            )
            self._contar("projeto coletivo", criado)
            projetos.append(projeto)
        return projetos

    def _disciplinas(self, programa: Program) -> list[Discipline]:
        definicoes = [
            ("DIR801", "Teoria da Constituição"),
            ("DIR802", "Hermenêutica Jurídica"),
            ("DIR803", "Direitos Fundamentais"),
            ("DIR804", "Processo Constitucional"),
            ("DIR805", "Metodologia da Pesquisa em Direito"),
            ("DIR806", "Direito Administrativo Contemporâneo"),
        ]
        disciplinas = []
        for codigo, nome in definicoes:
            disciplina, criado = Discipline.objects.get_or_create(
                program=programa,
                code=codigo,
                defaults={"name": nome},
            )
            self._contar("disciplina", criado)
            disciplinas.append(disciplina)
        return disciplinas

    def _periodos(self) -> dict[str, AcademicTerm]:
        definicoes = {
            "2026/1": (2026, 1, date(2026, 3, 2), date(2026, 7, 18)),
            "2026/2": (2026, 2, date(2026, 8, 3), date(2026, 12, 19)),
        }
        periodos = {}
        for rotulo, (ano, semestre, inicio, fim) in definicoes.items():
            periodo, criado = AcademicTerm.objects.get_or_create(
                year=ano,
                half=semestre,
                defaults={"starts_on": inicio, "ends_on": fim},
            )
            self._contar("período letivo", criado)
            periodos[rotulo] = periodo
        return periodos

    # ------------------------------------------------------------------
    # Pessoas e contas
    # ------------------------------------------------------------------

    def _pessoa(
        self,
        programa: Program,
        *,
        nome: str,
        email: str,
        papel: str | None,
        telefone: str = "",
    ) -> Person:
        """Cria (ou reaproveita) conta + pessoa e põe a conta no papel.

        Não usa `people.services.create_person_with_user` de propósito: lá
        a conta nasce sem senha utilizável, porque o fluxo real é de
        convite. Aqui a senha conhecida é o ponto — é o que deixa você
        entrar como cada papel.
        """
        email = self._email(email)
        user, criado_user = User.objects.get_or_create(
            username=email,
            defaults={"email": email, "first_name": nome[:150]},
        )
        if criado_user or not user.has_usable_password():
            user.set_password(self.senha)
            user.save(update_fields=["password"])
        self._contar("conta de acesso", criado_user)

        if papel is not None:
            grupo = Group.objects.filter(name=papel).first()
            if grupo is None:
                # Os papéis vêm de data migration; sem eles a carga
                # criaria gente sem permissão nenhuma e a tela apareceria
                # vazia sem explicação.
                raise CommandError(
                    f"O papel '{papel}' não existe. Rode `make migrate` antes."
                )
            user.groups.add(grupo)

        pessoa, criada = Person.objects.get_or_create(
            program=programa,
            primary_email=email,
            defaults={"user": user, "full_name": nome, "phone_number": telefone},
        )
        self._contar("pessoa", criada)
        return pessoa

    def _email(self, email: str) -> str:
        """Troca o domínio quando `--email-domain` foi informado.

        Sem a opção, os e-mails da carga saem exatamente como escritos nas
        definições — é o caso de sempre, um programa só.
        """
        if not self.dominio:
            return email
        local = email.split("@", 1)[0]
        return f"{local}@{self.dominio}"

    def _equipe(self, programa: Program) -> dict[str, Person]:
        """Quem opera o programa: secretaria e coordenação."""
        return {
            "secretaria": self._pessoa(
                programa,
                nome="Sônia Barreto",
                email="secretaria@ppgd.test",
                papel="Secretaria",
                telefone="(31) 3409-0001",
            ),
            "coordenacao": self._pessoa(
                programa,
                nome="Cláudio Ferraz",
                email="coordenacao@ppgd.test",
                papel="Coordenação",
                telefone="(31) 3409-0002",
            ),
        }

    def _docentes(
        self,
        programa: Program,
        linhas: list[ResearchLine],
        projetos: list[CollectiveProject],
    ) -> list[Teacher]:
        definicoes = [
            (
                "Ana Matos",
                "ana.matos@ppgd.test",
                Teacher.Category.PERMANENT,
                Teacher.AcademicDegree.DOCTORATE,
                linhas[0],
                [projetos[0], projetos[1]],
            ),
            (
                "Bruno Rocha",
                "bruno.rocha@ppgd.test",
                Teacher.Category.PERMANENT,
                Teacher.AcademicDegree.HABILITATION,
                linhas[1],
                [projetos[2]],
            ),
            (
                "Carla Dias",
                "carla.dias@ppgd.test",
                Teacher.Category.COLLABORATOR,
                Teacher.AcademicDegree.POSTDOCTORATE,
                linhas[0],
                [projetos[0]],
            ),
        ]
        docentes = []
        for nome, email, categoria, titulacao, linha, projetos_do_docente in definicoes:
            pessoa = self._pessoa(programa, nome=nome, email=email, papel="Docente")
            docente, criado = Teacher.objects.get_or_create(
                person=pessoa,
                defaults={
                    "program": programa,
                    "category": categoria,
                    "academic_degree": titulacao,
                    "accredited_since": date(2022, 3, 1),
                },
            )
            self._contar("professor", criado)
            docente.research_lines.add(linha)
            docente.projects.add(*projetos_do_docente)
            docentes.append(docente)
        return docentes

    def _alunos(
        self,
        programa: Program,
        projetos: list[CollectiveProject],
        docentes: list[Teacher],
        periodos: dict[str, AcademicTerm],
    ) -> list[Student]:
        """Quatro regulares e uma isolada do semestre anterior.

        A isolada de 2026/1 existe para a tela de alunos não mostrar só
        regular: é o vínculo que o encerramento do edital (US-020) exclui,
        e ver um exemplar dele ajuda a entender a diferença entre
        modalidade e situação (ADR-007).
        """
        regulares = [
            (
                "Daniel Prado",
                "daniel.prado@ppgd.test",
                Student.Level.MASTERS,
                projetos[0],
                docentes[0],
                date(2025, 3, 3),
                "2025110001",
                Student.Status.ACTIVE,
            ),
            (
                "Elisa Nunes",
                "elisa.nunes@ppgd.test",
                Student.Level.DOCTORATE,
                projetos[1],
                docentes[0],
                date(2024, 3, 4),
                "2024110002",
                Student.Status.ACTIVE,
            ),
            (
                "Felipe Aguiar",
                "felipe.aguiar@ppgd.test",
                Student.Level.MASTERS,
                projetos[2],
                docentes[1],
                date(2025, 8, 4),
                "2025210003",
                Student.Status.ACTIVE,
            ),
            (
                "Gabriela Serra",
                "gabriela.serra@ppgd.test",
                Student.Level.DOCTORATE,
                projetos[0],
                docentes[2],
                date(2023, 3, 6),
                "2023110004",
                # Trancado só existe no regular — é a CheckConstraint
                # `student_leave_only_when_regular`.
                Student.Status.LEAVE,
            ),
        ]
        alunos = []
        for (
            nome,
            email,
            nivel,
            projeto,
            orientador,
            ingresso,
            matricula,
            situacao,
        ) in regulares:
            pessoa = self._pessoa(programa, nome=nome, email=email, papel="Discente")
            aluno, criado = Student.objects.get_or_create(
                person=pessoa,
                modality=Student.Modality.REGULAR,
                defaults={
                    "program": programa,
                    "level": nivel,
                    "project": projeto,
                    "advisor": orientador,
                    "admission_date": ingresso,
                    # `registration_number` é unique GLOBAL, e não por
                    # programa: sem a sigla no prefixo, carregar um
                    # segundo tenant estoura a constraint no primeiro
                    # aluno.
                    "registration_number": f"{programa.acronym}{matricula}",
                    "status": situacao,
                },
            )
            self._contar("aluno", criado)
            alunos.append(aluno)

        pessoa_isolada = self._pessoa(
            programa,
            nome="Heitor Lima",
            email="heitor.lima@ppgd.test",
            papel="Candidato",
        )
        _, criado = Student.objects.get_or_create(
            person=pessoa_isolada,
            modality=Student.Modality.ISOLATED,
            term=periodos["2026/1"],
            defaults={"program": programa, "status": Student.Status.ACTIVE},
        )
        self._contar("aluno", criado)
        return alunos

    # ------------------------------------------------------------------
    # Acerto de matrícula
    # ------------------------------------------------------------------

    def _acertos(
        self,
        programa: Program,
        alunos: list[Student],
        disciplinas: list[Discipline],
        periodos: dict[str, AcademicTerm],
    ) -> None:
        """Um acerto em cada estado, para as três telas terem conteúdo.

        A aberta é a que o orientador (Ana Matos) encontra na fila dele; as
        outras duas mostram como decisão e motivo aparecem para o aluno.
        """
        termo = periodos["2026/2"]
        definicoes = [
            (
                alunos[0],
                EnrollmentAdjustmentRequest.Status.OPEN,
                "Preciso trocar a optativa para conciliar com o estágio docente.",
                "",
                [
                    (disciplinas[2], EnrollmentAdjustmentItem.Action.ADD),
                    (disciplinas[5], EnrollmentAdjustmentItem.Action.DROP),
                ],
            ),
            (
                alunos[1],
                EnrollmentAdjustmentRequest.Status.APPROVED,
                "Metodologia é pré-requisito para a qualificação.",
                "De acordo com o plano de estudos.",
                [(disciplinas[4], EnrollmentAdjustmentItem.Action.ADD)],
            ),
            (
                alunos[2],
                EnrollmentAdjustmentRequest.Status.REJECTED,
                "Gostaria de cursar as duas disciplinas do professor Bruno.",
                "A carga do semestre já está no limite; refaça no próximo período.",
                [
                    (disciplinas[0], EnrollmentAdjustmentItem.Action.ADD),
                    (disciplinas[3], EnrollmentAdjustmentItem.Action.ADD),
                ],
            ),
        ]
        for aluno, situacao, justificativa, motivo, itens in definicoes:
            decidido = (
                timezone.now()
                if situacao != EnrollmentAdjustmentRequest.Status.OPEN
                else None
            )
            acerto, criado = EnrollmentAdjustmentRequest.objects.get_or_create(
                student=aluno,
                term=termo,
                defaults={
                    "program": programa,
                    "status": situacao,
                    "justification": justificativa,
                    "decision_note": motivo,
                    "decided_at": decidido,
                },
            )
            self._contar("acerto de matrícula", criado)
            for disciplina, acao in itens:
                _, criado_item = EnrollmentAdjustmentItem.objects.get_or_create(
                    request=acerto, discipline=disciplina, action=acao
                )
                self._contar("item de acerto", criado_item)

    # ------------------------------------------------------------------
    # Disciplinas isoladas
    # ------------------------------------------------------------------

    def _ciclo(
        self,
        programa: Program,
        disciplinas: list[Discipline],
        docentes: list[Teacher],
        periodos: dict[str, AcademicTerm],
    ) -> tuple[IsolatedEnrollmentCycle, list[DisciplineOffering]]:
        """Edital de 2026/2 com a janela de inscrição ABERTA agora.

        As datas são relativas ao instante da carga, e não fixas: um edital
        com prazo vencido faria `submit()` recusar tudo e a tela de
        inscrição do candidato ficaria inútil no dia seguinte.
        """
        agora = timezone.now()
        ciclo, criado = IsolatedEnrollmentCycle.objects.get_or_create(
            program=programa,
            term=periodos["2026/2"],
            defaults={
                "submission_opens_at": agora - timedelta(days=7),
                "submission_closes_at": agora + timedelta(days=21),
                "result_published_on": (agora + timedelta(days=25)).date(),
                "appeal_opens_at": agora + timedelta(days=25),
                "appeal_closes_at": agora + timedelta(days=32),
                "final_result_on": (agora + timedelta(days=35)).date(),
                "payment_closes_at": agora + timedelta(days=45),
            },
        )
        self._contar("ciclo de isoladas", criado)

        definicoes = [
            (disciplinas[0], docentes[0], 3),
            (disciplinas[2], docentes[1], 2),
            (disciplinas[4], docentes[2], 5),
        ]
        ofertas = []
        for disciplina, docente, vagas in definicoes:
            oferta, criado_oferta = DisciplineOffering.objects.get_or_create(
                cycle=ciclo,
                discipline=disciplina,
                defaults={
                    "program": programa,
                    "teacher": docente,
                    "seats": vagas,
                },
            )
            self._contar("oferta", criado_oferta)
            ofertas.append(oferta)
        return ciclo, ofertas

    def _requerimentos(
        self,
        programa: Program,
        ciclo: IsolatedEnrollmentCycle,
        ofertas: list[DisciplineOffering],
        periodos: dict[str, AcademicTerm],
    ) -> None:
        """Um requerimento em cada estado do edital.

        Os classificados (`rank`) existem porque o deferimento cobra a
        ordenação do docente: sem eles a secretaria abriria a tela de
        análise e só encontraria `offering_not_ranked`.
        """
        agora = timezone.now()
        situacoes = IsolatedEnrollmentRequest.Status
        pagamentos = IsolatedEnrollmentRequest.PaymentStatus
        decididos = (
            situacoes.DEFERRED,
            situacoes.REJECTED,
            situacoes.ENROLLED,
        )

        definicoes = [
            CandidatoDemo(
                nome="Isabela Fontes",
                email="isabela.fontes@externo.test",
                situacao=situacoes.DRAFT,
                pagamento=pagamentos.PENDING,
                # Rascunho não tem classificação: o docente só ordena quem
                # já se inscreveu.
                escolhas=[(ofertas[0], None)],
            ),
            CandidatoDemo(
                nome="João Peixoto",
                email="joao.peixoto@externo.test",
                situacao=situacoes.SUBMITTED,
                pagamento=pagamentos.PENDING,
                escolhas=[(ofertas[0], 1), (ofertas[2], 1)],
            ),
            CandidatoDemo(
                nome="Karina Belo",
                email="karina.belo@externo.test",
                situacao=situacoes.DEFERRED,
                pagamento=pagamentos.PENDING,
                escolhas=[(ofertas[1], 1)],
                motivo="Documentação completa.",
            ),
            CandidatoDemo(
                nome="Lucas Andrade",
                email="lucas.andrade@externo.test",
                situacao=situacoes.REJECTED,
                pagamento=pagamentos.PENDING,
                escolhas=[(ofertas[2], 2)],
                motivo="Diploma ilegível; anexe novamente no recurso.",
            ),
            CandidatoDemo(
                nome="Marina Coelho",
                email="marina.coelho@externo.test",
                situacao=situacoes.ENROLLED,
                pagamento=pagamentos.EXEMPT,
                escolhas=[(ofertas[2], 3)],
                servidor=True,
                motivo="Servidora da UFMG, isenta da taxa.",
            ),
        ]

        for candidato in definicoes:
            pessoa = self._pessoa(
                programa,
                nome=candidato.nome,
                email=candidato.email,
                papel="Candidato",
            )
            requerimento, criado = IsolatedEnrollmentRequest.objects.get_or_create(
                cycle=ciclo,
                person=pessoa,
                defaults={
                    "program": programa,
                    "status": candidato.situacao,
                    "payment_status": candidato.pagamento,
                    "is_ufmg_staff": candidato.servidor,
                    "decision_note": candidato.motivo,
                    "decided_at": agora if candidato.situacao in decididos else None,
                    "submitted_at": (
                        agora - timedelta(days=2)
                        if candidato.situacao != situacoes.DRAFT
                        else None
                    ),
                    "gru_url": (
                        "https://arrecadacao.ufmg.br/gru/exemplo"
                        if candidato.situacao
                        in (situacoes.DEFERRED, situacoes.ENROLLED)
                        else ""
                    ),
                },
            )
            self._contar("requerimento de isolada", criado)

            for oferta, rank in candidato.escolhas:
                _, criado_item = IsolatedEnrollmentItem.objects.get_or_create(
                    request=requerimento,
                    offering=oferta,
                    defaults={"rank": rank},
                )
                self._contar("item de requerimento", criado_item)

            if candidato.situacao != situacoes.DRAFT:
                self._documentos(requerimento)

            if candidato.situacao == situacoes.ENROLLED:
                _, criado_aluno = Student.objects.get_or_create(
                    person=pessoa,
                    modality=Student.Modality.ISOLATED,
                    term=periodos["2026/2"],
                    defaults={"program": programa, "status": Student.Status.ACTIVE},
                )
                self._contar("aluno", criado_aluno)

    def _documentos(self, requerimento: IsolatedEnrollmentRequest) -> None:
        """Anexa o que o edital exige deste requerimento.

        `required_document_kinds()` já sabe que servidor da UFMG junta
        contracheque e autorização da chefia — repetir a lista aqui faria
        a carga divergir da regra no dia em que ela mudar.
        """
        for tipo in requerimento.required_document_kinds():
            if RequestDocument.objects.filter(request=requerimento, kind=tipo).exists():
                continue
            documento = RequestDocument(request=requerimento, kind=tipo)
            documento.file.save(f"{tipo}.pdf", ContentFile(PDF_MINIMO), save=False)
            documento.save()
            self._contar("documento", True)

    # ------------------------------------------------------------------
    # Processo seletivo
    # ------------------------------------------------------------------

    def _selecao(
        self,
        programa: Program,
        linhas: list[ResearchLine],
        projetos: list[CollectiveProject],
        docentes: list[Teacher],
    ) -> None:
        """O módulo de seleção inteiro, do edital publicado à matrícula.

        A ordem aqui é a ordem real do processo, e não é decorativa: a
        ata só congela com as notas lançadas, a convocação da etapa 1 só
        faz sentido antes de a ata eliminar alguém, e a conversão em
        aluno é a última porta — depois dela a chave trava
        (`ranking_locked`).
        """
        examinadores = self._examinadores(programa, linhas, projetos, docentes)
        regular = self._edital(
            programa,
            kind=SelectionKind.REGULAR,
            titulo=(
                f"Edital PS{ANO_DA_SELECAO} — Seleção Regular (Mestrado e Doutorado)"
            ),
            etapas=[
                ("Resumo expandido", 1, 1, 10, "Sala 201 — Faculdade de Direito"),
                ("Prova oral", 2, 2, 17, "Auditório da Faculdade de Direito"),
                ("Entrevista", 3, None, 24, "Sala da Coordenação"),
            ],
            vagas=[
                (SelectionLevel.MASTERS, projetos[0], QuotaCategory.OPEN, 2),
                (SelectionLevel.MASTERS, projetos[0], QuotaCategory.RACIAL, 1),
                (SelectionLevel.DOCTORATE, projetos[1], QuotaCategory.OPEN, 2),
                (SelectionLevel.DOCTORATE, projetos[1], QuotaCategory.RACIAL, 1),
                (SelectionLevel.MASTERS, projetos[2], QuotaCategory.OPEN, 1),
            ],
        )
        suplementar = self._edital(
            programa,
            kind=SelectionKind.SUPPLEMENTARY,
            titulo=(
                f"Edital PS{ANO_DA_SELECAO} — Seleção Suplementar (ações afirmativas)"
            ),
            etapas=[
                ("Memorial", 1, 1, 12, "Sala 305 — Faculdade de Direito"),
                ("Prova oral", 2, 2, 19, "Auditório da Faculdade de Direito"),
                ("Análise documental", 3, None, 26, "Secretaria do programa"),
            ],
            vagas=[
                (SelectionLevel.MASTERS, linhas[0], QuotaCategory.DISABILITY, 1),
                (SelectionLevel.MASTERS, linhas[0], QuotaCategory.INDIGENOUS, 1),
                (SelectionLevel.DOCTORATE, linhas[1], QuotaCategory.QUILOMBOLA, 1),
                (SelectionLevel.DOCTORATE, linhas[1], QuotaCategory.TRANS, 1),
            ],
        )

        self._bancas(regular, suplementar, projetos, linhas, examinadores)
        self._inscricoes(regular, suplementar, projetos, linhas)
        self._convocacao(regular)
        self._ata_assinada(regular, projetos[0])
        self._matricula(regular, projetos[1])

    def _examinadores(
        self,
        programa: Program,
        linhas: list[ResearchLine],
        projetos: list[CollectiveProject],
        docentes: list[Teacher],
    ) -> list[Teacher]:
        """Os três docentes do programa mais dois que só a seleção usa.

        A banca tem quatro nomes distintos (presidente, dois membros e um
        suplente) e o edital tem quatro bancas: com três docentes não dá
        para montar nenhuma. O externo é `Teacher.Category.EXTERNAL` e
        nasce **sem conta** de propósito — é exatamente por não ter login
        que ele assina a ata por token.
        """
        pessoa = self._pessoa(
            programa,
            nome="Núbia Prates",
            email="nubia.prates@ppgd.test",
            papel="Docente",
        )
        presidente, criado = Teacher.objects.get_or_create(
            person=pessoa,
            defaults={
                "program": programa,
                "category": Teacher.Category.PERMANENT,
                "academic_degree": Teacher.AcademicDegree.DOCTORATE,
                "accredited_since": date(2021, 3, 1),
            },
        )
        self._contar("professor", criado)
        presidente.research_lines.add(linhas[0])
        presidente.projects.add(projetos[0])

        email_externo = self._email("otavio.bastos@externo.test")
        pessoa_externa, criada = Person.objects.get_or_create(
            program=programa,
            primary_email=email_externo,
            defaults={"full_name": "Otávio Bastos"},
        )
        self._contar("pessoa", criada)
        externo, criado_externo = Teacher.objects.get_or_create(
            person=pessoa_externa,
            defaults={
                "program": programa,
                "category": Teacher.Category.EXTERNAL,
                "academic_degree": Teacher.AcademicDegree.DOCTORATE,
                "accredited_since": date(2024, 3, 1),
                "home_institution": "PUC Minas",
            },
        )
        self._contar("professor", criado_externo)

        # A Comissão de Seleção é o único papel que realoca vaga; sem uma
        # conta dela, a tela de resultado nasce sem quem aperte o botão.
        self._pessoa(
            programa,
            nome="Regina Sales",
            email="comissao@ppgd.test",
            papel="Comissão de Seleção",
        )
        return [*docentes, presidente, externo]

    def _edital(
        self,
        programa: Program,
        *,
        kind: str,
        titulo: str,
        etapas: list[tuple[str, int, int | None, int, str]],
        vagas: list[tuple[str, Any, str, int]],
    ) -> SelectionProcess:
        """Edital publicado, com etapas e grade de vagas, aceitando inscrição.

        A janela é relativa ao instante da carga (aberta há uma semana,
        fechando em três) pelo mesmo motivo do ciclo de isoladas: janela
        fixa vence, e a tela pública de inscrição fica inútil no dia
        seguinte. Publicar é `publish_process`, e não `status=published`
        na mão — é ele que cobra etapa, vaga e template de convocação.
        """
        agora = timezone.now()
        edital, criado = SelectionProcess.objects.get_or_create(
            program=programa,
            kind=kind,
            year=ANO_DA_SELECAO,
            defaults={
                "title": titulo,
                "submission_opens_at": agora - timedelta(days=7),
                "submission_closes_at": agora + timedelta(days=21),
                "convocation_subject": "[{edital}] Convocação para {etapa}",
                "convocation_body": (
                    "Prezado(a) {nome},\n\n"
                    "A inscrição de protocolo {protocolo} está convocada para "
                    "a etapa {etapa}, em {data_hora}, no local {local}.\n\n"
                    "Compareça com documento de identidade original.\n\n"
                    "Secretaria do programa."
                ),
            },
        )
        self._contar("edital de seleção", criado)

        for nome, ordem, desempate, dias, local in etapas:
            _, criada = SelectionStage.objects.get_or_create(
                process=edital,
                order=ordem,
                defaults={
                    "name": nome,
                    "tiebreak_rank": desempate,
                    "session_at": agora + timedelta(days=dias),
                    "location": local,
                },
            )
            self._contar("etapa da seleção", criada)

        for nivel, alvo, cota, quantidade in vagas:
            chave: dict[str, Any] = {"project": None, "research_line": None}
            chave["project" if kind == SelectionKind.REGULAR else "research_line"] = (
                alvo
            )
            _, criada_vaga = Vacancy.objects.get_or_create(
                process=edital,
                level=nivel,
                quota_category=cota,
                **chave,
                defaults={"program": programa, "quantity": quantidade},
            )
            self._contar("vaga", criada_vaga)

        if edital.status == SelectionProcessStatus.DRAFT:
            selecao.publish_process(process=edital)
        return edital

    def _bancas(
        self,
        regular: SelectionProcess,
        suplementar: SelectionProcess,
        projetos: list[CollectiveProject],
        linhas: list[ResearchLine],
        examinadores: list[Teacher],
    ) -> None:
        """Quatro bancas, uma por chave avaliada, com o externo em duas.

        Na banca do mestrado × primeiro projeto o externo é **suplente**:
        é essa a banca que assina a ata da carga, e todos os titulares
        dela têm conta (assinatura por login, sem token pendente). Na do
        doutorado ele é titular, que é o caso que a tela de bancas
        precisa mostrar — e o que produziria token se aquela ata
        congelasse.
        """
        ana, bruno, carla, presidente, externo = examinadores
        definicoes = [
            (
                regular,
                SelectionLevel.MASTERS,
                projetos[0],
                None,
                presidente,
                ana,
                bruno,
                externo,
            ),
            (
                regular,
                SelectionLevel.DOCTORATE,
                projetos[1],
                None,
                ana,
                bruno,
                externo,
                carla,
            ),
            (
                suplementar,
                SelectionLevel.MASTERS,
                None,
                linhas[0],
                bruno,
                carla,
                presidente,
                ana,
            ),
            (
                suplementar,
                SelectionLevel.DOCTORATE,
                None,
                linhas[1],
                carla,
                presidente,
                ana,
                bruno,
            ),
        ]
        for edital, nivel, projeto, linha, chefe, m1, m2, suplente in definicoes:
            banca, criada = Board.objects.get_or_create(
                process=edital,
                level=nivel,
                project=projeto,
                research_line=linha,
                defaults={
                    "program": edital.program,
                    "president": chefe,
                    "member_1": m1,
                    "member_2": m2,
                    "alternate": suplente,
                },
            )
            self._contar("banca", criada)

    def _inscricoes(
        self,
        regular: SelectionProcess,
        suplementar: SelectionProcess,
        projetos: list[CollectiveProject],
        linhas: list[ResearchLine],
    ) -> None:
        """Uma inscrição em cada situação, com documentação completa.

        `eliminated` não está na lista de propósito: quem elimina é a ata
        assinada (`_close_stage`), e semear o status na mão apagaria
        justamente a prova de que o caminho funciona. Sofia Tavares nasce
        homologada com 62 e cai quando a ata da etapa 1 é assinada.
        """
        situacoes = ApplicationStatus
        regulares = [
            InscricaoDemo(
                nome="Paula Rezende",
                email="paula.rezende@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.OPEN,
                situacao=situacoes.HOMOLOGATED,
                alvo=0,
                nota=Decimal("88.00"),
                motivo="Documentação completa.",
            ),
            InscricaoDemo(
                nome="Rafael Muniz",
                email="rafael.muniz@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.RACIAL,
                situacao=situacoes.HOMOLOGATED,
                alvo=0,
                nota=Decimal("76.50"),
                motivo="Documentação completa.",
            ),
            InscricaoDemo(
                nome="Sofia Tavares",
                email="sofia.tavares@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.OPEN,
                situacao=situacoes.HOMOLOGATED,
                alvo=0,
                nota=Decimal("62.00"),
                motivo="Documentação completa.",
            ),
            InscricaoDemo(
                nome="Tiago Vilela",
                email="tiago.vilela@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.OPEN,
                situacao=situacoes.SUBMITTED,
                alvo=2,
            ),
            InscricaoDemo(
                nome="Úrsula Pinho",
                email="ursula.pinho@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.OPEN,
                situacao=situacoes.REJECTED,
                alvo=2,
                motivo="Diploma ilegível; o prazo de recurso está no edital.",
            ),
            InscricaoDemo(
                nome="Vinícius Assis",
                email="vinicius.assis@externo.test",
                nivel=SelectionLevel.DOCTORATE,
                cota=QuotaCategory.OPEN,
                situacao=situacoes.APPROVED,
                alvo=1,
                nota=Decimal("94.00"),
                classificacao=1,
                desfecho=RankingOutcome.CLASSIFIED_OPEN,
                matricular=True,
            ),
            InscricaoDemo(
                nome="Wanda Coelho",
                email="wanda.coelho@externo.test",
                nivel=SelectionLevel.DOCTORATE,
                cota=QuotaCategory.OPEN,
                situacao=situacoes.APPROVED,
                alvo=1,
                nota=Decimal("81.00"),
                classificacao=2,
                desfecho=RankingOutcome.CLASSIFIED_OPEN,
            ),
        ]
        suplementares = [
            InscricaoDemo(
                nome="Yara Nogueira",
                email="yara.nogueira@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.DISABILITY,
                situacao=situacoes.HOMOLOGATED,
                alvo=0,
                nota=Decimal("84.00"),
                motivo="Documentação completa.",
            ),
            InscricaoDemo(
                nome="Zeca Andrade",
                email="zeca.andrade@externo.test",
                nivel=SelectionLevel.MASTERS,
                cota=QuotaCategory.INDIGENOUS,
                situacao=situacoes.HOMOLOGATED,
                alvo=0,
                nota=Decimal("79.00"),
                motivo="Documentação completa.",
            ),
            InscricaoDemo(
                nome="Alice Bittencourt",
                email="alice.bittencourt@externo.test",
                nivel=SelectionLevel.DOCTORATE,
                cota=QuotaCategory.QUILOMBOLA,
                situacao=situacoes.SUBMITTED,
                alvo=1,
            ),
        ]
        for edital, definicoes, alvos in (
            (regular, regulares, projetos),
            (suplementar, suplementares, linhas),
        ):
            for indice, definicao in enumerate(definicoes):
                self._inscricao(edital, definicao, alvos[definicao.alvo], indice)

    def _inscricao(
        self,
        edital: SelectionProcess,
        definicao: InscricaoDemo,
        alvo: Any,
        indice: int,
    ) -> Application:
        """Grava uma inscrição já no estado final, com anexos e nota.

        Não passa por `submit_application` de propósito: aquele service é
        a borda pública (rate limit, protocolo, janela) e devolveria
        sempre uma inscrição `submitted`. Aqui o que interessa é ter uma
        de cada situação para olhar na tela.
        """
        agora = timezone.now()
        cpf = self._cpf(edital.pk * 100 + indice)
        chave: dict[str, Any] = {"project": None, "research_line": None}
        campo = "project" if edital.kind == SelectionKind.REGULAR else "research_line"
        chave[campo] = alvo
        decidida = definicao.situacao != ApplicationStatus.SUBMITTED

        inscricao, criada = Application.objects.get_or_create(
            process=edital,
            cpf=cpf,
            defaults={
                "program": edital.program,
                "protocol": gerar_protocolo(edital),
                "full_name": definicao.nome,
                "email": self._email(definicao.email),
                "birth_date": date(1990 + indice, 4, 12),
                "phone_number": f"(31) 98800-00{indice:02d}",
                "level": definicao.nivel,
                "quota_category": definicao.cota,
                "status": definicao.situacao,
                "decision_note": definicao.motivo,
                "decided_at": agora - timedelta(days=1) if decidida else None,
                "final_score": (
                    definicao.nota
                    if definicao.situacao == ApplicationStatus.APPROVED
                    else None
                ),
                "final_rank": definicao.classificacao,
                "final_outcome": definicao.desfecho,
                "ranked_at": agora if definicao.desfecho else None,
                "submitted_at": agora - timedelta(days=3),
                **chave,
            },
        )
        self._contar("inscrição", criada)
        self._anexos(inscricao)

        if definicao.nota is not None:
            self._nota(inscricao, definicao.nota)
        return inscricao

    def _cpf(self, semente: int) -> str:
        """Um CPF bem formado e estável para a semente dada.

        `Application.clean()` roda o mod-11 (`cpf_valido`), então número
        inventado à mão faria a carga falhar. A semente entra na base para
        que a mesma inscrição caia sempre no mesmo CPF — é ele, com o
        edital, que identifica a linha no `get_or_create`.
        """
        base = f"{100000000 + semente * 137:09d}"
        digitos = [int(d) for d in base]
        for posicao in (9, 10):
            soma = sum(
                d * peso
                for d, peso in zip(
                    digitos[:posicao], range(posicao + 1, 1, -1), strict=True
                )
            )
            digitos.append((soma * 10 % 11) % 10)
        return "".join(str(d) for d in digitos)

    def _anexos(self, inscricao: Application) -> None:
        """Anexa o que o edital exige desta inscrição.

        Mesmo desenho de `_documentos`: a lista sai de
        `required_document_kinds()` — que já sabe que fora da ampla
        concorrência entra a comprovação da cota — para a carga não
        divergir da regra no dia em que ela mudar.
        """
        for tipo in inscricao.required_document_kinds():
            if ApplicationDocument.objects.filter(
                application=inscricao, kind=tipo
            ).exists():
                continue
            documento = ApplicationDocument(application=inscricao, kind=tipo)
            documento.file.save(f"{tipo}.pdf", ContentFile(PDF_MINIMO), save=False)
            documento.save()
            self._contar("documento de inscrição", True)

    def _nota(self, inscricao: Application, nota: Decimal) -> None:
        """Lança a nota da primeira etapa, com o presidente da banca como autor."""
        etapa = inscricao.process.stages.get(order=1)
        banca = Board.objects.filter(
            process=inscricao.process,
            level=inscricao.level,
            project=inscricao.project,
            research_line=inscricao.research_line,
        ).first()
        _, criada = StageScore.objects.get_or_create(
            application=inscricao,
            stage=etapa,
            defaults={
                "program": inscricao.program,
                "score": nota,
                "entered_by": None if banca is None else banca.president,
            },
        )
        self._contar("nota de etapa", criada)

    def _convocacao(self, edital: SelectionProcess) -> None:
        """Convoca para a primeira etapa quem está vivo no edital regular.

        Antes da ata, e não depois: a convocação chama para a prova, e
        quem a ata elimina só é eliminado quando ela é assinada. O lote é
        criado uma vez — na segunda carga `send_convocations` recusaria
        com `no_convocable_applications`, porque todo mundo já recebeu.
        """
        etapa = edital.stages.get(order=1)
        if Convocation.objects.filter(process=edital, stage=etapa).exists():
            return
        selecao.send_convocations(process=edital, stage=etapa)
        self._contar("convocação", True)

    def _ata_assinada(
        self, edital: SelectionProcess, projeto: CollectiveProject
    ) -> None:
        """A ata da etapa 1 do mestrado × primeiro projeto, assinada e em PDF.

        Percorre o caminho de verdade — gerar, congelar, assinar — porque
        é a última assinatura que fecha a etapa: ela é que elimina quem
        ficou abaixo do corte e que grava o PDF (`_close_stage`). Ata
        montada na mão não teria nem hash nem PDF.
        """
        etapa = edital.stages.get(order=1)
        banca = Board.objects.get(
            process=edital, level=SelectionLevel.MASTERS, project=projeto
        )
        if ExaminationRecord.objects.filter(
            process=edital, stage=etapa, level=banca.level, project=projeto
        ).exists():
            return

        ata = selecao.generate_record(board=banca, stage=etapa)
        selecao.freeze_record(record=ata)
        self._contar("ata de banca", True)
        for assinatura in list(ata.signatures.select_related("signer__person__user")):
            if assinatura.uses_token:
                # Examinador externo: não tem conta, e o token do
                # congelamento saiu por e-mail — o texto dele não fica no
                # banco. A carga reemite o seu (invalidando o anterior) e
                # o consome na hora, que é o caminho do link do e-mail.
                bruto = assinatura.issue_token(timezone.now())
                assinatura.save(
                    update_fields=[
                        "token_hash",
                        "token_expires_at",
                        "token_sent_at",
                        "token_used_at",
                        "updated_at",
                    ]
                )
                selecao.sign_record_with_token(token=bruto)
            else:
                selecao.sign_record(record=ata, user=assinatura.signer.person.user)
            self._contar("assinatura de ata", True)

    def _matricula(self, edital: SelectionProcess, projeto: CollectiveProject) -> None:
        """Converte a primeira classificada do doutorado em aluna regular.

        É a porta final do fluxo, e a que trava a chave: a partir daqui
        recalcular a classificação daquele nível × alvo devolve
        `ranking_locked`. Uma só, de propósito — a segunda classificada
        fica `approved` para a tela de resultado ter o botão de matricular
        com o que trabalhar.
        """
        inscricao = (
            Application.objects.for_process(edital.pk)
            .approved()
            .filter(level=SelectionLevel.DOCTORATE, project=projeto, final_rank=1)
            .first()
        )
        if inscricao is None:
            return
        selecao.convert_to_student(
            application=inscricao,
            registration_number=f"{edital.program.acronym}{ANO_DA_SELECAO}110005",
            admission_date=date(ANO_DA_SELECAO, 3, 1),
            project=projeto,
        )
        self._contar("aluno", True)

    # ------------------------------------------------------------------
    # Relato
    # ------------------------------------------------------------------

    def _contar(self, rotulo: str, criado: bool) -> None:
        if criado:
            self.criadas[rotulo] = self.criadas.get(rotulo, 0) + 1

    def _relatar(self, programa: Program, equipe: dict[str, Person]) -> None:
        if self.criadas:
            self.stdout.write(self.style.SUCCESS(f"Carga aplicada em {programa}:"))
            for rotulo in sorted(self.criadas):
                self.stdout.write(f"  {self.criadas[rotulo]:>3} {rotulo}")
        else:
            self.stdout.write(f"Nada a criar: {programa} já estava carregado.")

        self.stdout.write("")
        self.stdout.write(f"Contas (senha: {self.senha}):")
        for papel, email in self._contas():
            self.stdout.write(f"  {email:<32} {papel}")
        caminho = self._gravar_contas(programa)
        self.stdout.write("")
        self.stdout.write(f"As contas também ficaram em {caminho}.")
        self.stdout.write("Entre por http://localhost:8080 — nunca por :5173.")

    def _contas(self) -> list[tuple[str, str]]:
        """Papel → e-mail das contas que a carga deixa prontas.

        Uma lista só, usada pela saída do comando e pelo `CONTAS-DEMO.txt`:
        duas listas divergiriam na primeira conta nova.
        """
        contas = [
            ("Secretaria", "secretaria@ppgd.test"),
            ("Coordenação", "coordenacao@ppgd.test"),
            ("Comissão de Seleção (realoca vaga)", "comissao@ppgd.test"),
            ("Docente / orientador", "ana.matos@ppgd.test"),
            ("Docente de oferta", "bruno.rocha@ppgd.test"),
            ("Docente presidente de banca", "nubia.prates@ppgd.test"),
            ("Discente com acerto aberto", "daniel.prado@ppgd.test"),
            ("Candidato em rascunho", "isabela.fontes@externo.test"),
            ("Candidato deferido", "karina.belo@externo.test"),
        ]
        return [(papel, self._email(email)) for papel, email in contas]

    def _gravar_contas(self, programa: Program) -> Path:
        """Escreve (ou reescreve) o bloco deste programa no `CONTAS-DEMO.txt`.

        O arquivo é de todos os tenants carregados, e a carga do segundo
        não pode apagar o do primeiro: o bloco é identificado pela sigla e
        só ele é substituído. Fica na raiz do repositório e é ignorado pelo
        git — são senhas conhecidas, e escrevê-las num arquivo versionado
        seria vazá-las.
        """
        caminho = Path(settings.BASE_DIR).parent / ARQUIVO_DE_CONTAS
        cabecalho = (
            "# Contas de demonstração — geradas por `make seed`.\n"
            "# Arquivo ignorado pelo git; some com o banco do canteiro.\n"
        )
        marca = f"## {programa.acronym}"
        bloco = [
            f"{marca} — {programa.name}",
            f"Senha: {self.senha}",
            *(f"  {email:<34} {papel}" for papel, email in self._contas()),
        ]

        anteriores = []
        if caminho.exists():
            atual: list[str] = []
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                if linha.startswith("## "):
                    if atual:
                        anteriores.append(atual)
                    atual = [linha]
                elif atual:
                    atual.append(linha)
            if atual:
                anteriores.append(atual)
        blocos = [b for b in anteriores if not b[0].startswith(f"{marca} ")]
        blocos.append(bloco)

        corpo = "\n\n".join("\n".join(b).rstrip() for b in blocos)
        caminho.write_text(f"{cabecalho}\n{corpo}\n", encoding="utf-8")
        return caminho
