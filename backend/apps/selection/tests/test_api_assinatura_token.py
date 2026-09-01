"""A assinatura do examinador externo, pelo link que ele recebeu por e-mail.

Nível (b) da pirâmide (Seção 9). O que este arquivo guarda, e nenhum
outro guarda:

- **o token é a sessão que não existe** — o externo não tem conta, então
  o link identifica, autoriza e expira. Aqui se prova que ele vale uma
  vez só, que o prazo é respeitado e que a reemissão mata o anterior;
- **o 404 genérico da leitura** — token inexistente, expirado ou já usado
  respondem a mesma coisa: a rota é pública, e diferenciar diria a quem
  chuta link se ele existiu algum dia. Na escrita, ao contrário, o código
  é específico (`token_expired`, `token_already_used`), porque é o que a
  tela precisa dizer ao examinador;
- **o fechamento da etapa disparado de fora da sessão** — quando o
  externo é o terceiro a assinar, quem fecha a etapa é uma requisição sem
  usuário logado, e a auditoria precisa levar o programa explícito.
"""

import re
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.test import Client
from django.utils import timezone

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ExaminationRecord,
    RecordSignature,
    RecordStatus,
    SelectionProcess,
    SignatureMethod,
    StageScore,
)
from apps.selection.services import freeze_record

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"
PUBLICO = "/api/v1/selection/public/signatures"


def leitura_de(token: str) -> str:
    return f"{PUBLICO}/{token}"


def assinatura_de(token: str) -> str:
    return f"{PUBLICO}/{token}/sign"


def reenvio_de(record_id: int, signature_id: int) -> str:
    return (
        f"/api/v1/selection/records/{record_id}/signatures/{signature_id}/resend-token"
    )


def assinar(client: Client, token: str, **corpo):
    """POST da assinatura pública. O corpo vai sempre, mesmo vazio:
    `RecordSignIn` é schema de corpo e o Ninja recusa a requisição sem ele."""
    return client.post(
        assinatura_de(token), data=corpo, content_type="application/json"
    )


def token_do_email() -> str:
    """O token em texto só existe no e-mail — no banco fica o sha256."""
    assert mail.outbox, "nenhum e-mail de assinatura foi enviado"
    # `EmailMessage.body` é tipado como texto preguiçoso; aqui é str.
    corpo = str(mail.outbox[-1].body)
    achado = re.search(r"/selecao/assinatura/(\S+)", corpo)
    assert achado is not None, corpo
    return achado.group(1)


def dar_conta(program: Program, teacher: Teacher, papel: str, username: str) -> User:
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    pessoa = teacher.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    return user


@pytest.fixture
def etapa(edital_regular: SelectionProcess):
    return edital_regular.stages.get(order=1)


@pytest.fixture
def banca_com_externo(banca_regular: Board, professores: list[Teacher]) -> Board:
    """A mesma banca, com o externo como membro titular.

    Na `banca_regular` o externo é o suplente e não assina — trocá-lo com
    o membro 2 é o caminho mais curto para uma ata com token."""
    banca_regular.member_2, banca_regular.alternate = professores[3], professores[2]
    banca_regular.clean()
    banca_regular.save()
    return banca_regular


@pytest.fixture
def ata_congelada(
    banca_com_externo: Board,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    django_capture_on_commit_callbacks,
    settings,
) -> ExaminationRecord:
    """Ata aguardando as três assinaturas, com o token do externo já enviado."""
    settings.SITE_URL = "https://ppgd.exemplo.br"
    with django_capture_on_commit_callbacks(execute=True):
        freeze_record(record=ata_regular)
    ata_regular.refresh_from_db()
    return ata_regular


@pytest.fixture
def token(ata_congelada: ExaminationRecord) -> str:
    return token_do_email()


@pytest.fixture
def assinatura_externa(
    ata_congelada: ExaminationRecord, externo: Teacher
) -> RecordSignature:
    return ata_congelada.signatures.get(signer=externo)


@pytest.fixture
def client_da_secretaria(client: Client, secretaria: User, program: Program) -> Client:
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client.force_login(secretaria)
    return client


def expirar(assinatura: RecordSignature) -> None:
    """Empurra o prazo para trás sem tocar no hash — é o que o relógio faz."""
    RecordSignature.objects.filter(pk=assinatura.pk).update(
        token_expires_at=timezone.now() - timedelta(minutes=1)
    )


# --- GET public/signatures/{token} -----------------------------------------


def test_leitura_com_token_valido_mostra_cabecalho_conteudo_e_hash(
    client: Client,
    token: str,
    ata_congelada: ExaminationRecord,
    inscricao: Application,
    externo: Teacher,
    etapa,
):
    resposta = client.get(leitura_de(token))

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["signer_name"] == externo.person.full_name
    assert corpo["signer_institution"] == externo.home_institution
    assert corpo["stage_name"] == etapa.name
    assert corpo["process_title"] == str(ata_congelada.process)
    assert corpo["version"] == 1
    assert corpo["content_hash"] == ata_congelada.content_hash
    assert corpo["hash_ok"] is True
    assert corpo["pending_signatures"] == 3
    assert corpo["content"] == [
        {
            "application_id": inscricao.pk,
            "protocol": inscricao.protocol,
            "full_name": "Ana Lima",
            "quota_category": inscricao.quota_category,
            "score": "85.50",
            "absent": False,
            "passed": True,
        }
    ]


def test_leitura_nao_devolve_o_hash_do_token_nem_id_de_banca(
    client: Client, token: str, assinatura_externa: RecordSignature
):
    """O link abre uma ata para conferência, não uma conta no sistema."""
    corpo = client.get(leitura_de(token)).content.decode()

    assert assinatura_externa.token_hash not in corpo
    assert "board_id" not in corpo
    assert "program_id" not in corpo


def test_leitura_com_token_inexistente_e_404_generico(client: Client, token: str):
    resposta = client.get(leitura_de("token-que-nunca-existiu"))

    assert resposta.status_code == 404
    assert "token-que-nunca-existiu" not in resposta.content.decode()


def test_leitura_com_token_expirado_e_404(
    client: Client, token: str, assinatura_externa: RecordSignature
):
    expirar(assinatura_externa)

    assert client.get(leitura_de(token)).status_code == 404


def test_leitura_depois_de_assinar_e_404(client: Client, token: str):
    """Uso único: a mesma URL que abriu a conferência deixa de abrir."""
    assert assinar(client, token).status_code == 200

    assert client.get(leitura_de(token)).status_code == 404


def test_limite_de_leitura_por_ip_dispara(client: Client, token: str):
    for _ in range(20):
        assert client.get(leitura_de(token)).status_code == 200

    excedente = client.get(leitura_de(token))

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"


# --- POST public/signatures/{token}/sign ------------------------------------


def test_assinatura_por_token_registra_consome_e_audita_com_programa(
    client: Client,
    token: str,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
    program: Program,
):
    resposta = assinar(client, token, content_hash=ata_congelada.content_hash)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["signer_name"] == assinatura_externa.signer.person.full_name
    assert corpo["signed_hash"] == ata_congelada.content_hash
    assert corpo["record_status"] == RecordStatus.AWAITING_SIGNATURES
    assert corpo["pending_signatures"] == 2
    assinatura_externa.refresh_from_db()
    assert assinatura_externa.method == SignatureMethod.TOKEN
    assert assinatura_externa.is_signed
    assert assinatura_externa.token_used_at is not None
    assert assinatura_externa.signed_by_user is None
    # Armadilha 12: sem sessão não há de onde inferir tenant depois; o
    # service passa `program=` explícito.
    evento = AuditLog.objects.filter(event="selection.record.sign").get()
    assert evento.program_id == program.pk
    assert evento.actor_id is None
    assert evento.payload["method"] == SignatureMethod.TOKEN


def test_externo_como_terceira_assinatura_fecha_a_etapa(
    client: Client,
    token: str,
    ata_congelada: ExaminationRecord,
    banca_com_externo: Board,
    program: Program,
    professores: list[Teacher],
    etapa,
    inscricao: Application,
):
    """Os dois professores do programa assinam logados; o externo fecha."""
    rota = (
        f"/api/v1/selection/boards/{banca_com_externo.pk}/stages/{etapa.pk}/record/sign"
    )
    for indice, apelido in ((0, "presidente"), (1, "membro")):
        logado = Client()
        logado.force_login(dar_conta(program, professores[indice], "Docente", apelido))
        resposta = logado.post(rota, data={}, content_type="application/json")
        assert resposta.status_code == 200, resposta.content

    resposta = assinar(client, token)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["record_status"] == RecordStatus.SIGNED
    assert corpo["pending_signatures"] == 0
    ata_congelada.refresh_from_db()
    assert ata_congelada.status == RecordStatus.SIGNED
    assert ata_congelada.pdf
    fechamento = AuditLog.objects.filter(event="selection.stage.close").get()
    assert fechamento.program_id == program.pk
    assert fechamento.payload["promoted"] == [inscricao.pk]
    inscricao.refresh_from_db()
    # Etapa intermediária: seguir vivo é a promoção.
    assert inscricao.status == ApplicationStatus.HOMOLOGATED


def test_assinar_com_token_expirado_e_409_com_codigo(
    client: Client, token: str, assinatura_externa: RecordSignature
):
    expirar(assinatura_externa)

    resposta = assinar(client, token)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "token_expired"
    assinatura_externa.refresh_from_db()
    assert not assinatura_externa.is_signed


def test_assinar_duas_vezes_com_o_mesmo_token_e_409(client: Client, token: str):
    assert assinar(client, token).status_code == 200

    resposta = assinar(client, token)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "token_already_used"


def test_assinar_com_hash_velho_e_409_record_changed(
    client: Client,
    token: str,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
):
    """O hash do corpo é o que a tela mostrou: se a ata mudou entre a
    conferência e o clique, a assinatura não vale."""
    resposta = assinar(client, token, content_hash="0" * 64)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_changed"
    assinatura_externa.refresh_from_db()
    assert not assinatura_externa.is_signed
    # O token não queima numa tentativa recusada.
    assert assinatura_externa.token_used_at is None


def test_assinar_com_token_inexistente_e_404(client: Client, token: str):
    resposta = assinar(client, "token-que-nunca-existiu")

    assert resposta.status_code == 404


def test_assinatura_sem_token_csrf_e_recusada(token: str):
    """auth=None desliga o CSRF do SessionAuth; o `csrf_protect` explícito
    da rota é o que segura."""
    sem_csrf = Client(enforce_csrf_checks=True)

    resposta = assinar(sem_csrf, token)

    assert resposta.status_code == 403
    assert not RecordSignature.objects.filter(signed_at__isnull=False).exists()


def test_limite_de_assinaturas_por_ip_dispara(client: Client, token: str):
    for _ in range(10):
        assert assinar(client, "token-que-nunca-existiu").status_code == 404

    excedente = assinar(client, token)

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"
    assert not RecordSignature.objects.filter(signed_at__isnull=False).exists()


# --- POST records/{id}/signatures/{sid}/resend-token ------------------------


def test_reenvio_emite_token_novo_e_invalida_o_anterior(
    client_da_secretaria: Client,
    token: str,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
    externo: Teacher,
    django_capture_on_commit_callbacks,
):
    hash_anterior = assinatura_externa.token_hash

    with django_capture_on_commit_callbacks(execute=True):
        resposta = client_da_secretaria.post(
            reenvio_de(ata_congelada.pk, assinatura_externa.pk),
            data={},
            content_type="application/json",
        )

    assert resposta.status_code == 200, resposta.content
    # A resposta é montada ANTES do commit, e o carimbo do envio é de
    # depois dele: o que a secretaria vê na hora é o prazo novo.
    assert resposta.json()["token_sent_at"] is None
    assert resposta.json()["token_expires_at"] is not None
    assinatura_externa.refresh_from_db()
    assert assinatura_externa.token_sent_at is not None
    assert assinatura_externa.token_hash != hash_anterior
    assert len(mail.outbox) == 2
    assert mail.outbox[-1].to == [externo.person.primary_email]
    assert AuditLog.objects.filter(event="selection.record.token_reissued").count() == 1

    # O link velho morreu; o novo assina. Client próprio: o `client` do
    # pytest-django é o mesmo objeto em que a secretaria fez login.
    externo_sem_conta = Client()
    assert externo_sem_conta.get(leitura_de(token)).status_code == 404
    novo = token_do_email()
    assert assinar(externo_sem_conta, novo).status_code == 200


def test_reenvio_para_quem_ja_assinou_e_409(
    client_da_secretaria: Client,
    token: str,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
):
    assert assinar(Client(), token).status_code == 200

    resposta = client_da_secretaria.post(
        reenvio_de(ata_congelada.pk, assinatura_externa.pk),
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "already_signed"


def test_reenvio_de_assinatura_por_login_e_400(
    client_da_secretaria: Client,
    ata_congelada: ExaminationRecord,
    professores: list[Teacher],
):
    """Professor do programa assina logado: não há token para reenviar."""
    do_presidente = ata_congelada.signatures.get(signer=professores[0])

    resposta = client_da_secretaria.post(
        reenvio_de(ata_congelada.pk, do_presidente.pk),
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "token_not_applicable"


def test_reenvio_de_ata_de_outro_programa_e_404(
    client: Client,
    secretaria: User,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
):
    """A secretaria de outro programa não alcança esta ata — e o 404 não
    conta a ela que o id existe."""
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    Person.objects.create(
        program=outro,
        user=secretaria,
        full_name="Dora Reis",
        primary_email="dora@exemplo.br",
    )
    client.force_login(secretaria)

    resposta = client.post(
        reenvio_de(ata_congelada.pk, assinatura_externa.pk),
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 404
    assinatura_externa.refresh_from_db()
    assert assinatura_externa.token_sent_at is not None


def test_reenvio_sem_permissao_e_403(
    client_sem_permissao: Client,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
):
    resposta = client_sem_permissao.post(
        reenvio_de(ata_congelada.pk, assinatura_externa.pk),
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 403


def test_reenvio_sem_sessao_e_401(
    client: Client,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
):
    resposta = client.post(
        reenvio_de(ata_congelada.pk, assinatura_externa.pk),
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 401


def test_reenvio_sem_token_csrf_e_recusado(
    secretaria: User,
    program: Program,
    ata_congelada: ExaminationRecord,
    assinatura_externa: RecordSignature,
):
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    sem_csrf = Client(enforce_csrf_checks=True)
    sem_csrf.force_login(secretaria)
    hash_anterior = assinatura_externa.token_hash

    resposta = sem_csrf.post(
        reenvio_de(ata_congelada.pk, assinatura_externa.pk),
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 403
    assinatura_externa.refresh_from_db()
    assert assinatura_externa.token_hash == hash_anterior
