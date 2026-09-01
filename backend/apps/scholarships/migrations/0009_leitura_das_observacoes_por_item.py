"""Dá `view_itemreview` a quem escreve e a quem é comentado.

A `0008_papeis_da_bolsa` distribuiu `view_` de todos os models do app à
Coordenação (que só acompanha), mas deixou de fora justamente os dois
lados que a observação por item existe para ligar:

- a **Comissão de Bolsas**, que a escreve (pela permissão
  `review_baremeentry`, a mesma da nota: comentar o item é parte do ato de
  analisar) e precisa reler o que escreveu para retificar;
- o **Discente**, que é quem o comentário tem por destinatário — é dele
  que sai o recurso contra a reclassificação em bloco de um item. O
  `committee_note` do lançamento já chega ao candidato pelo
  `BaremeEntryOut`; esconder a observação do item seria esconder metade
  do fundamento;
- a **Secretaria**, que opera o edital e responde ao candidato.

O recorte de *quais* observações cada um lê continua sendo da rota
(`_garantir_acesso_a_inscricao`): a permissão diz que a pessoa lê
observação, não de quem.

Nenhuma permissão de escrita entra aqui. `add_itemreview`/`change_itemreview`
não são dadas a ninguém de propósito: um papel que comentasse o item sem
poder pontuar não existe no edital, e a rota cobra `review_baremeentry`.
"""

from django.db import migrations

PAPEIS = ["Comissão de Bolsas", "Secretaria", "Discente"]
CODENAME = "view_itemreview"


def criar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="scholarships", model="itemreview"
    )
    permission, _ = Permission.objects.get_or_create(
        codename=CODENAME,
        content_type=content_type,
        defaults={"name": "Can view itemreview"},
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
        ("scholarships", "0008_papeis_da_bolsa"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
