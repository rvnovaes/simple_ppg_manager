"""`GET /api/v1/access/me`: o estado do próprio cadastro.

É a rota que alimenta a tela de espera, lida por quem ainda não tem
permissão nenhuma — daí o que a suíte cobre: que ela responde sem
`require_perm`, que continua respondendo depois da recusa (quando a
`Person` está arquivada e `current_program` daria 403) e que nunca mostra
a solicitação de outra pessoa.
"""

import pytest
from django.contrib.auth.models import Group

from apps.academic.models import AccessProfile, AccessRequest, Teacher
from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/access/me"
SENHA = "senha-de-espera-2026"


def _pendente(
    program: Program,
    *,
    email: str = "ana.doc@example.com",
    nome: str = "Ana Docente",
    profile: str = AccessProfile.TEACHER,
) -> AccessRequest:
    """Uma conta com solicitação pendente, gravada pelo ORM.

    Sem passar pelo endpoint de signup de propósito: aqui o que se testa é
    a leitura, e o `force_login` do cliente é do teste, não da fixture."""
    user = User.objects.create_user(username=email, email=email, password=SENHA)
    person = Person.objects.create(
        program=program, user=user, full_name=nome, primary_email=email
    )
    user.groups.add(Group.objects.get(name="Cadastro pendente"))
    campos = (
        {
            "teacher_category": Teacher.Category.PERMANENT,
            "academic_degree": Teacher.AcademicDegree.DOCTORATE,
        }
        if profile == AccessProfile.TEACHER
        else {}
    )
    return AccessRequest.objects.create(
        program=program, person=person, profile=profile, **campos
    )


def test_pendente_ve_a_propria_solicitacao(program, client):
    solicitacao = _pendente(program)
    client.force_login(solicitacao.person.user)

    resposta = client.get(URL)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["id"] == solicitacao.pk
    assert corpo["program_id"] == program.pk
    assert corpo["program_name"] == program.name
    assert corpo["profile"] == AccessProfile.TEACHER.value
    assert corpo["profile_label"] == "Docente"
    assert corpo["status"] == AccessRequest.Status.PENDING.value
    assert corpo["status_label"] == "Pendente"
    assert corpo["decision_note"] == ""
    assert corpo["decided_at"] is None
    assert corpo["created_at"] is not None


def test_recusado_ve_o_motivo_mesmo_com_a_pessoa_arquivada(program, client):
    solicitacao = _pendente(program)
    solicitacao.reject(note="Titulação não comprovada.")
    solicitacao.save()
    pessoa = solicitacao.person
    # É este o estado que quebraria `current_program`: a rota não o usa,
    # e por isso a pessoa recusada continua lendo o próprio motivo.
    pessoa.archive()
    pessoa.save()
    client.force_login(pessoa.user)

    resposta = client.get(URL)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == AccessRequest.Status.REJECTED.value
    assert corpo["status_label"] == "Recusada"
    assert corpo["decision_note"] == "Titulação não comprovada."
    assert corpo["decided_at"] is not None


def test_quem_nunca_pediu_recebe_404(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 404


def test_anonimo_nao_entra(client):
    assert client.get(URL).status_code == 401


def test_ninguem_ve_a_solicitacao_alheia(program, client):
    alheia = _pendente(program)
    outra = _pendente(
        program,
        email="bruno.disc@example.com",
        nome="Bruno Discente",
        profile=AccessProfile.STUDENT,
    )
    client.force_login(outra.person.user)

    corpo = client.get(URL).json()

    assert corpo["id"] == outra.pk != alheia.pk
    assert corpo["profile"] == AccessProfile.STUDENT.value


def test_pendente_vence_a_decisao_antiga(program, client):
    """Quem foi recusado e pediu de novo lê o pedido vivo, não o encerrado.

    O índice parcial permite exatamente isto: uma pendente por pessoa,
    histórico livre. Sem a preferência pela pendente, a tela mostraria
    para sempre o motivo da primeira recusa."""
    recusada = _pendente(program)
    recusada.reject(note="Faltou o Lattes.")
    recusada.save()
    pessoa = recusada.person
    nova = AccessRequest.objects.create(
        program=program,
        person=pessoa,
        profile=AccessProfile.TEACHER,
        teacher_category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
    )
    client.force_login(pessoa.user)

    corpo = client.get(URL).json()

    assert corpo["id"] == nova.pk
    assert corpo["status"] == AccessRequest.Status.PENDING.value
    assert corpo["decision_note"] == ""
