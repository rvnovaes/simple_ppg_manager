"""Dá à Secretaria `change_recordsignature` — o reenvio do token do externo.

A `0006` deu a ela só `view_recordsignature`: na época, assinatura era coisa
da banca inteira. O que falta é o atendimento — o examinador externo liga
dizendo que o link não chegou, caiu no spam ou expirou, e quem reemite é a
secretaria, não a banca.

O poder é estreito de propósito. `resend_signature_token` manda outro link
para **o mesmo e-mail** do signatário e invalida o anterior; não muda
conteúdo, não muda signatário e não assina por ninguém. Assinar continua
sendo `sign_examinationrecord`, que só o Docente tem.
"""

from django.db import migrations

PAPEL = "Secretaria"
PERMISSAO = "change_recordsignature"


def criar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    group = Group.objects.filter(name=PAPEL).first()
    if group is None:  # pragma: no cover - o papel nasce em programs.0002
        return
    content_type, _ = ContentType.objects.get_or_create(
        app_label="selection", model="recordsignature"
    )
    permission, _ = Permission.objects.get_or_create(
        codename=PERMISSAO,
        content_type=content_type,
        defaults={"name": "Can change recordsignature"},
    )
    group.permissions.add(permission)


def desfazer(apps, schema_editor):
    Group = apps.get_model("auth", "Group")

    group = Group.objects.filter(name=PAPEL).first()
    if group is None:  # pragma: no cover
        return
    group.permissions.remove(
        *group.permissions.filter(
            codename=PERMISSAO, content_type__app_label="selection"
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("selection", "0006_papeis_da_selecao"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
