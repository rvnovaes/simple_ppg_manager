"""Invariantes de nota, ata e assinatura.

Nível (a) da pirâmide: objetos em memória, pks à mão, nada salvo — salvo
o bloco final, marcado com `django_db`, que prova as constraints e os
espelhos do `clean()` contra o banco.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.academic.models import Teacher
from apps.core.exceptions import DomainError, InvalidStateTransition, NotAllowed
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program
from apps.selection.models import (
    Application,
    Board,
    ExaminationRecord,
    RecordSignature,
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    SignatureMethod,
    StageScore,
    caminho_da_ata,
    hash_canonico,
    hash_do_token,
)

AGORA = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)


def _professor(pk: int, category: str = Teacher.Category.PERMANENT) -> Teacher:
    return Teacher(pk=pk, program_id=1, category=category, accredited_since=AGORA)


def _edital(kind: str = SelectionKind.REGULAR, pk: int = 1) -> SelectionProcess:
    return SelectionProcess(pk=pk, program_id=1, kind=kind, year=2027)


def _banca(edital: SelectionProcess | None = None) -> Board:
    edital = edital or _edital()
    return Board(
        pk=1,
        program_id=1,
        process=edital,
        level=SelectionLevel.MASTERS,
        project=CollectiveProject(pk=1),
        president=_professor(1),
        member_1=_professor(2),
        member_2=_professor(3),
        alternate=_professor(4, Teacher.Category.EXTERNAL),
    )


def _ata(banca: Board | None = None, **kwargs) -> ExaminationRecord:
    banca = banca or _banca()
    campos = {
        "program": Program(pk=1),
        "process": banca.process,
        "stage": SelectionStage(pk=1, process=banca.process, order=1),
        "level": banca.level,
        "project": banca.project,
        "board": banca,
    }
    return ExaminationRecord(**{**campos, **kwargs})


def _linha(nome: str, protocolo: str, score, absent: bool = False) -> dict:
    return {
        "application_id": 1,
        "protocol": protocolo,
        "full_name": nome,
        "quota_category": "open",
        "score": score,
        "absent": absent,
        "passed": bool(score is not None and Decimal(str(score)) >= 70),
    }


def _ata_congelada(**kwargs) -> ExaminationRecord:
    ata = _ata(**kwargs)
    ata.freeze([_linha("Ana", "PS2027R-1", "85.50")], at=AGORA)
    return ata


# --- StageScore ------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "absent"),
    [(Decimal("70.00"), True), (None, False)],
    ids=["nota e ausente", "nem nota nem ausente"],
)
def test_nota_exige_score_xor_ausente(score, absent):
    with pytest.raises(DomainError) as exc:
        StageScore(score=score, absent=absent).clean()

    assert exc.value.code == "absent_xor_score"


@pytest.mark.parametrize("score", [Decimal("-0.01"), Decimal("100.01")])
def test_nota_fora_do_intervalo_falha(score):
    with pytest.raises(DomainError) as exc:
        StageScore(score=score).clean()

    assert exc.value.code == "invalid_score"


@pytest.mark.parametrize(
    ("score", "absent", "esperado"),
    [
        (Decimal("70.00"), False, True),
        (Decimal("69.99"), False, False),
        (Decimal("100.00"), False, True),
        (None, True, False),
    ],
)
def test_passed_usa_o_corte_exato(score, absent, esperado):
    assert StageScore(score=score, absent=absent).passed is esperado


def test_nota_de_etapa_de_outro_edital_falha():
    linha = StageScore(
        application=Application(pk=1, process=_edital(pk=1)),
        stage=SelectionStage(pk=1, process=_edital(pk=2)),
        score=Decimal("80"),
    )
    with pytest.raises(DomainError) as exc:
        linha.clean()

    assert exc.value.code == "stage_mismatch"


def test_linha_da_ata_leva_a_nota_como_texto():
    inscricao = Application(
        pk=7, protocol="PS2027R-ABCDEF01", full_name="Ana", quota_category="open"
    )
    linha = StageScore(application=inscricao, score=Decimal("85.50")).as_record_row()

    assert linha == {
        "application_id": 7,
        "protocol": "PS2027R-ABCDEF01",
        "full_name": "Ana",
        "quota_category": "open",
        "score": "85.50",
        "absent": False,
        "passed": True,
    }


# --- ExaminationRecord: hash -------------------------------------------------


def test_hash_canonico_ignora_ordem_das_chaves():
    a = hash_canonico({"b": 1, "a": [{"y": "é", "x": None}]})
    b = hash_canonico({"a": [{"x": None, "y": "é"}], "b": 1})

    assert a == b
    assert len(a) == 64


def test_hash_da_ata_e_estavel_entre_instancias():
    ata_1 = _ata_congelada()
    ata_2 = _ata_congelada()

    assert ata_1.content_hash == ata_2.content_hash
    assert ata_1.verify_hash()


def test_hash_muda_com_o_cabecalho():
    """Mesmo conteúdo em outra versão (ou outra etapa) não reaproveita a
    assinatura."""
    ata_1 = _ata_congelada()
    ata_2 = _ata_congelada(version=2, supersedes=ExaminationRecord(pk=9, version=1))

    assert ata_1.content_hash != ata_2.content_hash


def test_verify_hash_detecta_alteracao_do_conteudo():
    ata = _ata_congelada()
    ata.content[0]["score"] = "95.00"

    assert not ata.verify_hash()


def test_verify_hash_falha_sem_hash_gravado():
    assert not _ata().verify_hash()


# --- ExaminationRecord: freeze e transições ---------------------------------


def test_freeze_ordena_por_nome_e_grava_nota_como_texto():
    ata = _ata()
    ata.freeze(
        [
            _linha("Zé", "PS2027R-2", Decimal("70.00")),
            _linha("Ana", "PS2027R-1", None, absent=True),
        ],
        at=AGORA,
    )

    assert [r["full_name"] for r in ata.content] == ["Ana", "Zé"]
    assert ata.content[1]["score"] == "70.00"
    assert ata.content[0]["score"] is None
    assert ata.status == RecordStatus.AWAITING_SIGNATURES
    assert ata.frozen_at == AGORA
    assert ata.content_hash == ata.compute_hash()
    assert ata.is_frozen and ata.is_current


def test_freeze_sem_candidato_falha():
    with pytest.raises(DomainError) as exc:
        _ata().freeze([], at=AGORA)

    assert exc.value.code == "no_candidates"


def test_freeze_fora_do_rascunho_falha():
    ata = _ata_congelada()
    with pytest.raises(InvalidStateTransition) as exc:
        ata.freeze(ata.content, at=AGORA)

    assert exc.value.code == "record_not_draft"


def test_reopen_volta_ao_rascunho_e_limpa_o_hash():
    ata = _ata_congelada()
    ata.reopen()

    assert ata.status == RecordStatus.DRAFT
    assert ata.content_hash == ""
    assert ata.frozen_at is None
    assert not ata.is_frozen


def test_mark_signed_e_supersede_seguem_a_maquina():
    ata = _ata_congelada()
    ata.mark_signed(at=AGORA)
    assert ata.status == RecordStatus.SIGNED
    assert ata.signed_at == AGORA
    assert ata.is_frozen

    ata.supersede()
    assert ata.status == RecordStatus.SUPERSEDED
    assert not ata.is_current


@pytest.mark.parametrize(
    ("status", "metodo", "codigo"),
    [
        (RecordStatus.DRAFT, "reopen", "record_not_awaiting_signatures"),
        (RecordStatus.DRAFT, "mark_signed", "record_not_awaiting_signatures"),
        (RecordStatus.DRAFT, "supersede", "record_not_signed"),
        (RecordStatus.SIGNED, "reopen", "record_not_awaiting_signatures"),
    ],
)
def test_transicoes_fora_de_ordem_falham(status, metodo, codigo):
    ata = _ata(status=status)
    chamada = getattr(ata, metodo)
    with pytest.raises(InvalidStateTransition) as exc:
        chamada(at=AGORA) if metodo == "mark_signed" else chamada()

    assert exc.value.code == codigo
    assert exc.value.status_code == 409


# --- ExaminationRecord: versão, banca e signatários -------------------------


def test_versao_2_exige_supersedes():
    with pytest.raises(DomainError) as exc:
        _ata(version=2).clean()

    assert exc.value.code == "invalid_version"


def test_versao_1_nao_pode_substituir():
    with pytest.raises(DomainError) as exc:
        _ata(supersedes=ExaminationRecord(pk=9, version=1)).clean()

    assert exc.value.code == "invalid_version"


def test_versao_nova_e_a_seguinte_a_substituida():
    with pytest.raises(DomainError) as exc:
        _ata(version=3, supersedes=ExaminationRecord(pk=9, version=1)).clean()

    assert exc.value.code == "invalid_version"


def test_banca_de_outro_alvo_falha():
    banca = _banca()
    with pytest.raises(DomainError) as exc:
        _ata(banca, project=CollectiveProject(pk=2)).clean()

    assert exc.value.code == "board_mismatch"


def test_etapa_de_outro_edital_falha():
    ata = _ata(stage=SelectionStage(pk=1, process=_edital(pk=2), order=1))
    with pytest.raises(DomainError) as exc:
        ata.clean()

    assert exc.value.code == "stage_mismatch"


def test_titular_impedido_precisa_ser_titular():
    banca = _banca()
    with pytest.raises(DomainError) as exc:
        _ata(banca, replaced_member=banca.alternate).clean()

    assert exc.value.code == "not_a_titular_member"


def test_expected_signers_troca_o_impedido_pelo_suplente():
    banca = _banca()
    ata = _ata(banca, replaced_member=banca.member_1)

    assert [s.pk for s in ata.expected_signers()] == [1, 4, 3]
    assert [s.pk for s in _ata(banca).expected_signers()] == [1, 2, 3]


# --- RecordSignature: método e login ------------------------------------------


def test_metodo_vem_da_categoria_do_signatario():
    assert RecordSignature.method_for(_professor(1)) == SignatureMethod.LOGIN
    externo = _professor(4, Teacher.Category.EXTERNAL)
    assert RecordSignature.for_signer(_ata(), externo).method == SignatureMethod.TOKEN


def test_metodo_incoerente_com_a_categoria_falha():
    assinatura = RecordSignature(
        record=_ata(), signer=_professor(1), method=SignatureMethod.TOKEN
    )
    with pytest.raises(DomainError) as exc:
        assinatura.clean()

    assert exc.value.code == "signature_method_mismatch"


def test_signatario_fora_da_banca_falha():
    assinatura = RecordSignature.for_signer(_ata(), _professor(99))
    with pytest.raises(DomainError) as exc:
        assinatura.clean()

    assert exc.value.code == "signer_not_expected"


def test_ensure_can_sign_by_login_aceita_so_o_proprio_signatario():
    usuario = get_user_model()
    dono = usuario(pk=5)
    outro = usuario(pk=6)
    professor = _professor(1)
    professor.person = Person(pk=1, program_id=1, user_id=5)
    assinatura = RecordSignature.for_signer(_ata(), professor)

    assinatura.ensure_can_sign_by_login(dono)
    for usuario in (outro, None):
        with pytest.raises(NotAllowed) as exc:
            assinatura.ensure_can_sign_by_login(usuario)
        assert exc.value.code == "not_the_signer"
        assert exc.value.status_code == 403


def test_externo_nao_assina_por_login():
    externo = _professor(4, Teacher.Category.EXTERNAL)
    externo.person = Person(pk=4, program_id=1, user_id=5)
    assinatura = RecordSignature.for_signer(_ata(), externo)
    with pytest.raises(NotAllowed):
        assinatura.ensure_can_sign_by_login(get_user_model()(pk=5))


# --- RecordSignature: sign ---------------------------------------------------


def test_sign_grava_instante_hash_usuario_e_ip():
    ata = _ata_congelada()
    usuario = get_user_model()(pk=5)
    assinatura = RecordSignature.for_signer(ata, _professor(1))
    assinatura.sign(AGORA, ata.content_hash, user=usuario, ip="10.0.0.1")

    assert assinatura.is_signed
    assert assinatura.signed_at == AGORA
    assert assinatura.signed_hash == ata.content_hash
    assert assinatura.signed_by_user is usuario
    assert assinatura.ip_address == "10.0.0.1"


def test_sign_com_hash_divergente_falha():
    ata = _ata_congelada()
    assinatura = RecordSignature.for_signer(ata, _professor(1))
    with pytest.raises(InvalidStateTransition) as exc:
        assinatura.sign(AGORA, "0" * 64)

    assert exc.value.code == "record_changed"
    assert not assinatura.is_signed


def test_sign_com_conteudo_alterado_depois_do_congelamento_falha():
    ata = _ata_congelada()
    hash_visto = ata.content_hash
    ata.content[0]["score"] = "10.00"
    assinatura = RecordSignature.for_signer(ata, _professor(1))
    with pytest.raises(InvalidStateTransition) as exc:
        assinatura.sign(AGORA, hash_visto)

    assert exc.value.code == "record_changed"


def test_sign_duas_vezes_falha():
    ata = _ata_congelada()
    assinatura = RecordSignature.for_signer(ata, _professor(1))
    assinatura.sign(AGORA, ata.content_hash)
    with pytest.raises(InvalidStateTransition) as exc:
        assinatura.sign(AGORA, ata.content_hash)

    assert exc.value.code == "already_signed"


def test_sign_em_ata_que_nao_aguarda_assinatura_falha():
    ata = _ata()
    assinatura = RecordSignature.for_signer(ata, _professor(1))
    with pytest.raises(InvalidStateTransition) as exc:
        assinatura.sign(AGORA, "")

    assert exc.value.code == "record_not_awaiting_signatures"


# --- RecordSignature: token ----------------------------------------------------


def _assinatura_por_token() -> RecordSignature:
    return RecordSignature.for_signer(
        _ata_congelada(), _professor(4, Teacher.Category.EXTERNAL)
    )


def test_issue_token_devolve_texto_e_persiste_so_o_hash():
    assinatura = _assinatura_por_token()
    raw = assinatura.issue_token(at=AGORA)

    assert len(raw) >= 40
    assert raw not in assinatura.token_hash
    assert assinatura.token_hash == hash_do_token(raw)
    assert assinatura.token_expires_at == AGORA + timedelta(days=7)
    assert assinatura.token_sent_at is None
    assert assinatura.token_valid_at(AGORA)


def test_reemitir_token_invalida_o_anterior():
    assinatura = _assinatura_por_token()
    primeiro = assinatura.issue_token(at=AGORA)
    assinatura.consume_token(at=AGORA)
    segundo = assinatura.issue_token(at=AGORA + timedelta(days=1))

    assert primeiro != segundo
    assert assinatura.token_hash != hash_do_token(primeiro)
    assert assinatura.token_used_at is None
    assert assinatura.token_expires_at == AGORA + timedelta(days=8)


def test_issue_token_para_quem_assina_logado_falha():
    assinatura = RecordSignature.for_signer(_ata_congelada(), _professor(1))
    with pytest.raises(DomainError) as exc:
        assinatura.issue_token(at=AGORA)

    assert exc.value.code == "token_not_applicable"


def test_consume_token_marca_o_uso():
    assinatura = _assinatura_por_token()
    assinatura.issue_token(at=AGORA)
    assinatura.consume_token(at=AGORA + timedelta(days=6, hours=23))

    assert assinatura.token_used_at == AGORA + timedelta(days=6, hours=23)
    assert not assinatura.token_valid_at(AGORA + timedelta(days=6, hours=23))


@pytest.mark.parametrize(
    "atraso", [timedelta(days=7), timedelta(days=30)], ids=["no limite", "depois"]
)
def test_consume_token_expirado_falha(atraso):
    assinatura = _assinatura_por_token()
    assinatura.issue_token(at=AGORA)
    with pytest.raises(InvalidStateTransition) as exc:
        assinatura.consume_token(at=AGORA + atraso)

    assert exc.value.code == "token_expired"
    assert assinatura.token_used_at is None


def test_consume_token_reusado_falha():
    assinatura = _assinatura_por_token()
    assinatura.issue_token(at=AGORA)
    assinatura.consume_token(at=AGORA)
    with pytest.raises(InvalidStateTransition) as exc:
        assinatura.consume_token(at=AGORA + timedelta(minutes=1))

    assert exc.value.code == "token_already_used"


def test_consume_token_sem_token_emitido_falha():
    with pytest.raises(DomainError) as exc:
        _assinatura_por_token().consume_token(at=AGORA)

    assert exc.value.code == "token_not_applicable"


def test_assinatura_por_login_nao_carrega_token():
    assinatura = RecordSignature.for_signer(_ata(), _professor(1))
    assinatura.token_hash = "a" * 64
    with pytest.raises(DomainError) as exc:
        assinatura.clean()

    assert exc.value.code == "token_not_applicable"


# --- com banco: constraints e espelhos ----------------------------------------


@pytest.mark.django_db
def test_nota_duplicada_e_espelhada_no_clean(nota: StageScore):
    repetida = StageScore(
        program=nota.program,
        application=nota.application,
        stage=nota.stage,
        score=Decimal("50"),
    )
    with pytest.raises(DomainError) as exc:
        repetida.clean()
    assert exc.value.code == "duplicate_score"

    with pytest.raises(IntegrityError), transaction.atomic():
        repetida.save()


@pytest.mark.django_db
def test_constraint_de_xor_da_nota_vale_sem_clean(nota: StageScore):
    nota.absent = True
    with pytest.raises(IntegrityError), transaction.atomic():
        nota.save()


@pytest.mark.django_db
def test_for_target_recorta_as_notas_do_alvo(nota: StageScore):
    inscricao = nota.application
    alvo = StageScore.objects.for_stage(nota.stage).for_target(
        inscricao.level, inscricao.project, inscricao.research_line
    )
    assert list(alvo) == [nota]
    assert not StageScore.objects.for_target(
        SelectionLevel.DOCTORATE, inscricao.project, None
    ).exists()


@pytest.mark.django_db
def test_uma_ata_corrente_por_chave(ata_regular: ExaminationRecord):
    segunda = ExaminationRecord(
        program=ata_regular.program,
        process=ata_regular.process,
        stage=ata_regular.stage,
        level=ata_regular.level,
        project=ata_regular.project,
        board=ata_regular.board,
    )
    with pytest.raises(DomainError) as exc:
        segunda.clean()
    assert exc.value.code == "record_already_exists"

    with pytest.raises(IntegrityError), transaction.atomic():
        segunda.save()


@pytest.mark.django_db
def test_versao_nova_convive_com_a_substituida(ata_regular: ExaminationRecord):
    ata_regular.freeze([_linha("Ana", "PS2027R-1", "85.50")], at=AGORA)
    ata_regular.mark_signed(at=AGORA)
    ata_regular.supersede()
    ata_regular.save()

    nova = ExaminationRecord(
        program=ata_regular.program,
        process=ata_regular.process,
        stage=ata_regular.stage,
        level=ata_regular.level,
        project=ata_regular.project,
        board=ata_regular.board,
        version=2,
        supersedes=ata_regular,
        rectification_reason="Erro de soma na prova oral.",
    )
    nova.clean()
    nova.save()

    assert list(ExaminationRecord.objects.current()) == [nova]
    assert ata_regular.superseded_by == nova

    repetida = ExaminationRecord(
        program=ata_regular.program,
        process=ata_regular.process,
        stage=ata_regular.stage,
        level=ata_regular.level,
        project=ata_regular.project,
        board=ata_regular.board,
        version=1,
        status=RecordStatus.SUPERSEDED,
    )
    with pytest.raises(DomainError) as exc:
        repetida.clean()
    assert exc.value.code == "duplicate_record"


@pytest.mark.django_db
def test_constraint_de_versao_vale_sem_clean(ata_regular: ExaminationRecord):
    ata_regular.version = 2
    with pytest.raises(IntegrityError), transaction.atomic():
        ata_regular.save()


@pytest.mark.django_db
def test_caminho_do_pdf_da_ata(ata_regular: ExaminationRecord):
    assert caminho_da_ata(ata_regular, "x.pdf") == (
        f"selecao/edital-{ata_regular.process_id}/atas/ata-{ata_regular.pk}-v1.pdf"
    )


@pytest.mark.django_db
def test_assinaturas_por_token_sao_achadas_pelo_texto(
    ata_regular: ExaminationRecord, nota: StageScore
):
    """Titular impedido antes do congelamento (o cabeçalho hasheado leva
    `replaced_member_id`); o suplente externo assina por token."""
    ata_regular.replaced_member = ata_regular.board.member_1
    ata_regular.freeze([nota.as_record_row()], at=AGORA)
    ata_regular.save()
    assinaturas = [
        RecordSignature.for_signer(ata_regular, s)
        for s in ata_regular.expected_signers()
    ]
    externa = assinaturas[1]
    assert externa.signer == ata_regular.board.alternate
    raw = externa.issue_token(at=AGORA)
    for assinatura in assinaturas:
        assinatura.clean()
        assinatura.save()

    assert RecordSignature.objects.by_token(raw).get() == externa
    assert not RecordSignature.objects.by_token("outro-token").exists()
    assert RecordSignature.objects.pending().count() == 3

    assinaturas[0].sign(AGORA, ata_regular.content_hash)
    assinaturas[0].save()
    assert RecordSignature.objects.pending().count() == 2

    fora = RecordSignature.for_signer(ata_regular, ata_regular.board.member_1)
    with pytest.raises(DomainError) as exc:
        fora.clean()
    assert exc.value.code == "signer_not_expected"

    repetida = RecordSignature.for_signer(ata_regular, assinaturas[0].signer)
    with pytest.raises(DomainError) as exc:
        repetida.clean()
    assert exc.value.code == "duplicate_signature"
    with pytest.raises(IntegrityError), transaction.atomic():
        repetida.save()


@pytest.mark.django_db
def test_constraint_de_token_so_no_metodo_token(ata_regular: ExaminationRecord):
    assinatura = RecordSignature.for_signer(ata_regular, ata_regular.board.president)
    assinatura.token_hash = "a" * 64
    with pytest.raises(IntegrityError), transaction.atomic():
        assinatura.save()
