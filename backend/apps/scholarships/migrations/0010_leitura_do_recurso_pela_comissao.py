"""Dá `view_scholarshipappeal` a quem julga o recurso.

A `0008_papeis_da_bolsa` deu à Comissão de Bolsas o `change_scholarshipappeal`
— o julgamento — e ao Discente o `add`/`view_` — a interposição e a leitura
do próprio. Faltou o óbvio do meio: quem julga precisa **ler** o que vai
julgar, e a rota de leitura do recurso
(`GET /applications/{id}/appeal`) cobra `view_scholarshipappeal`. Sem esta
migração a comissão recebe 403 na tela em que decide.

Mesmo caso e mesmo remédio da `0009_leitura_das_observacoes_por_item`: só
leitura, nenhuma escrita nova. A Secretaria entra junto porque a `0008` lhe
deu `view_` de edição, barema, comissão, inscrição e lançamento, mas não de
recurso — e é ela que opera o edital e responde ao candidato que pergunta
pelo andamento. A Coordenação já lê tudo desde a `0008`, e nenhum dos dois
ganha `change_`: julgar continua sendo só da comissão.

O recorte de *quais* recursos cada um lê continua sendo da rota
(`_garantir_acesso_a_inscricao`): a permissão diz que a pessoa lê recurso,
não de quem — o Discente também a tem, e é com ela que lê o próprio.
"""

from django.db import migrations

PAPEIS = ["Comissão de Bolsas", "Secretaria"]
CODENAME = "view_scholarshipappeal"


def criar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="scholarships", model="scholarshipappeal"
    )
    permission, _ = Permission.objects.get_or_create(
        codename=CODENAME,
        content_type=content_type,
        defaults={"name": "Can view scholarshipappeal"},
    )
    for papel in PAPEIS:
        group, _ = Group.objects.get_or_create(name=papel)
        group.permissions.add(permission)


def desfazer(apps, schema_editor):
    Group = apps.get_model("auth", "Group")

    for papel in PAPEIS:
        group = Group.objects.filter(name=papel).first()
        if group is None:
            continue
        group.permissions.remove(
            *group.permissions.filter(
                codename=CODENAME, content_type__app_label="scholarships"
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("scholarships", "0009_leitura_das_observacoes_por_item"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
