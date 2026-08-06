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
        contas = [
            ("Secretaria", "secretaria@ppgd.test"),
            ("Coordenação", "coordenacao@ppgd.test"),
            ("Docente / orientador", "ana.matos@ppgd.test"),
            ("Docente de oferta", "bruno.rocha@ppgd.test"),
            ("Discente com acerto aberto", "daniel.prado@ppgd.test"),
            ("Candidato em rascunho", "isabela.fontes@externo.test"),
            ("Candidato deferido", "karina.belo@externo.test"),
        ]
        for papel, email in contas:
            self.stdout.write(f"  {self._email(email):<32} {papel}")
        self.stdout.write("")
        self.stdout.write("Entre por http://localhost:8080 — nunca por :5173.")
