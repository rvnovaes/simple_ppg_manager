"""Estende os papéis existentes com as permissões do acerto de matrícula.

Continua `academic.0003_papeis_dos_cadastros`, que não pode ser editada
porque já está aplicada. Nenhum grupo nasce aqui: Secretaria e Coordenação
vêm de `programs.0002_programa_inicial_e_papeis`, Docente e Discente de
`academic.0003_papeis_dos_cadastros` — esta migração só acrescenta.

Quem faz o quê no fluxo (ADR-007 e Seção 5 do CLAUDE.md):

- Discente abre a solicitação e acompanha as suas; precisa ler o catálogo
  para escolher a disciplina.
- Docente decide (aprovar/recusar), o que é `change_` sobre a solicitação;
  não pode abrir uma.
- Secretaria mantém o catálogo (a tela da US-008 substitui o Admin, ADR-006)
  e lê as solicitações para replicar a mudança no sistema da UFMG.
- Coordenação só acompanha.

Nenhum grupo recebe `delete_*`: apagar dado de negócio é quebra-vidro de
sysadmin no Admin, não rotina de papel de domínio.
"""

from django.db import migrations

SOLICITACAO = "academic.{verbo}_enrollmentadjustmentrequest"
DISCIPLINA = "programs.{verbo}_discipline"

# Papel -> permissões novas, no formato "app_label.codename".
NOVAS_PERMISSOES = {
    "Discente": [
        SOLICITACAO.format(verbo="add"),
        SOLICITACAO.format(verbo="view"),
        DISCIPLINA.format(verbo="view"),
    ],
    "Docente": [
        SOLICITACAO.format(verbo="view"),
        SOLICITACAO.format(verbo="change"),
        DISCIPLINA.format(verbo="view"),
    ],
    "Secretaria": [
        SOLICITACAO.format(verbo="view"),
        DISCIPLINA.format(verbo="view"),
        DISCIPLINA.format(verbo="add"),
        DISCIPLINA.format(verbo="change"),
    ],
    "Coordenação": [
        SOLICITACAO.format(verbo="view"),
        DISCIPLINA.format(verbo="view"),
    ],
}


def criar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    for papel, perms in NOVAS_PERMISSOES.items():
        group, _ = Group.objects.get_or_create(name=papel)
        for perm in perms:
            app_label, codename = perm.split(".")
            model = codename.split("_", 1)[1]
            # As permissões são criadas por um sinal post_migrate que ainda
            # não rodou neste ponto; garantimos a existência aqui.
            content_type, _ = ContentType.objects.get_or_create(
                app_label=app_label, model=model
            )
            permission, _ = Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={"name": f"Can {codename.split('_')[0]} {model}"},
            )
            group.permissions.add(permission)


def desfazer(apps, schema_editor):
    Group = apps.get_model("auth", "Group")

    # Nenhum grupo é apagado: todos preexistem a esta migração e continuam
    # valendo sem ela. Retira-se apenas o que foi concedido aqui.
    for papel, perms in NOVAS_PERMISSOES.items():
        group = Group.objects.filter(name=papel).first()
        if group is None:
            continue
        codenames = [perm.split(".")[1] for perm in perms]
        group.permissions.remove(*group.permissions.filter(codename__in=codenames))


class Migration(migrations.Migration):
    dependencies = [
        ("academic", "0004_enrollmentadjustmentrequest_enrollmentadjustmentitem"),
        ("programs", "0006_discipline"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
