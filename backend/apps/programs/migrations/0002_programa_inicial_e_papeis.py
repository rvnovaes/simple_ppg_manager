"""Cria o programa inicial e os papéis do domínio.

Papéis são Groups nativos (ADR-003), criados por data migration para que
todo ambiente nasça com o mesmo conjunto — sem cadastro manual e sem
divergência entre dev e produção.
"""

from django.db import migrations

# Papel -> permissões, no formato "app_label.codename".
PAPEIS = {
    "Secretaria": [
        "people.view_person",
        "people.add_person",
        "people.change_person",
        "programs.view_program",
        "audit.view_auditlog",
    ],
    "Coordenação": [
        "people.view_person",
        "programs.view_program",
        "audit.view_auditlog",
    ],
}


def criar(apps, schema_editor):
    Program = apps.get_model("programs", "Program")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    Program.objects.get_or_create(
        acronym="PPGD",
        defaults={"name": "Programa de Pós-Graduação em Direito"},
    )

    for papel, perms in PAPEIS.items():
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
    Program = apps.get_model("programs", "Program")
    Group.objects.filter(name__in=PAPEIS).delete()
    Program.objects.filter(acronym="PPGD").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("programs", "0001_initial"),
        ("people", "0001_initial"),
        ("audit", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
