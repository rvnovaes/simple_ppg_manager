"""Cria Docente e Discente e estende Secretaria e Coordenação.

Continua a data migration `programs.0002_programa_inicial_e_papeis`, que não
pode ser editada porque já está aplicada. Mora em `academic` (e não em
`programs`) porque precisa das permissões de Teacher e Student: uma migração
de `programs` dependendo de `academic` inverteria a direção natural do grafo.

Papel é Group nativo (ADR-003). Nenhum grupo recebe `delete_*`: apagar dado
de negócio é quebra-vidro de sysadmin no Admin, não rotina de secretaria.
Nenhum grupo dá `is_staff`/`is_superuser` — papel de domínio nunca abre o
Admin (Seção 5 do CLAUDE.md).

Docente e Discente nascem aqui, e não na PRD de matrícula, porque o cadastro
de professor e aluno já precisa atribuí-los. Ambos só recebem leitura da
estrutura do programa; as telas próprias de cada papel virão com o módulo
que as justificar, e cada permissão nova entra junto da tela que a usa.
"""

from django.db import migrations

CADASTROS = [
    ("programs", "researchline"),
    ("programs", "collectiveproject"),
    ("programs", "academicterm"),
    ("academic", "teacher"),
    ("academic", "student"),
]

ESTRUTURA = [
    ("programs", "researchline"),
    ("programs", "collectiveproject"),
    ("programs", "academicterm"),
]


def _perms(alvos, verbos):
    return [f"{app}.{verbo}_{model}" for app, model in alvos for verbo in verbos]


# Papel -> permissões novas, no formato "app_label.codename".
NOVAS_PERMISSOES = {
    "Secretaria": [
        *_perms(CADASTROS, ("view", "add", "change")),
        # Necessária para definir a senha de primeiro acesso do professor
        # ou aluno recém-cadastrado.
        "accounts.change_user",
    ],
    "Coordenação": _perms(CADASTROS, ("view",)),
    "Docente": _perms(ESTRUTURA, ("view",))
    + ["academic.view_teacher", "academic.view_student"],
    "Discente": _perms(ESTRUTURA, ("view",)),
}

# Grupos criados por esta migração — só estes somem no desfazer; Secretaria e
# Coordenação pertencem à programs.0002 e apenas perdem o que ganharam aqui.
GRUPOS_NOVOS = ["Docente", "Discente"]


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

    Group.objects.filter(name__in=GRUPOS_NOVOS).delete()
    for papel, perms in NOVAS_PERMISSOES.items():
        if papel in GRUPOS_NOVOS:
            continue
        group = Group.objects.filter(name=papel).first()
        if group is None:
            continue
        codenames = [perm.split(".")[1] for perm in perms]
        group.permissions.remove(*group.permissions.filter(codename__in=codenames))


class Migration(migrations.Migration):
    dependencies = [
        ("academic", "0002_student"),
        ("programs", "0005_academicterm"),
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
