"""Cria o papel Candidato e estende os demais com as permissões da isolada.

Continua `academic.0005_papeis_do_acerto`, que não pode ser editada porque já
está aplicada. Só Candidato nasce aqui; Secretaria e Coordenação vêm de
`programs.0002_programa_inicial_e_papeis`, Docente e Discente de
`academic.0003_papeis_dos_cadastros`.

Quem faz o quê no fluxo da matrícula em disciplina isolada (ADR-007 e
Seção 5 do CLAUDE.md):

- Candidato ainda não é aluno: existe só enquanto tem um requerimento. Abre
  o requerimento (`add`), acompanha (`view`), monta e envia (`change`), e lê
  a oferta para escolher a disciplina. Nada além disso — nenhuma permissão
  sobre Student, Teacher ou qualquer outro dado de negócio.
- Docente responsável classifica os candidatos da sua oferta
  (`rank_disciplineoffering`) e lê os requerimentos para isso. NÃO baixa
  documento: identidade e comprovante são dados pessoais que a classificação
  não precisa.
- Secretaria monta o edital (ciclo e ofertas), decide os requerimentos
  (`change`) e é o único papel que baixa os anexos
  (`download_requestdocument`).
- Coordenação só acompanha: leitura de requerimento, ciclo e oferta.

Nenhum grupo recebe `delete_*` nem `is_staff`/`is_superuser`: apagar é
quebra-vidro de sysadmin no Admin, e papel de domínio nunca abre o Admin.
"""

from django.db import migrations

REQUERIMENTO = "academic.{verbo}_isolatedenrollmentrequest"
CICLO = "academic.{verbo}_isolatedenrollmentcycle"
OFERTA = "academic.{verbo}_disciplineoffering"

# Papel -> permissões novas, no formato "app_label.codename".
NOVAS_PERMISSOES = {
    "Candidato": [
        REQUERIMENTO.format(verbo="add"),
        REQUERIMENTO.format(verbo="view"),
        REQUERIMENTO.format(verbo="change"),
        OFERTA.format(verbo="view"),
    ],
    "Secretaria": [
        REQUERIMENTO.format(verbo="view"),
        REQUERIMENTO.format(verbo="change"),
        CICLO.format(verbo="view"),
        CICLO.format(verbo="add"),
        CICLO.format(verbo="change"),
        OFERTA.format(verbo="view"),
        OFERTA.format(verbo="add"),
        OFERTA.format(verbo="change"),
        "academic.download_requestdocument",
    ],
    "Docente": [
        REQUERIMENTO.format(verbo="view"),
        OFERTA.format(verbo="view"),
        "academic.rank_disciplineoffering",
    ],
    "Coordenação": [
        REQUERIMENTO.format(verbo="view"),
        CICLO.format(verbo="view"),
        OFERTA.format(verbo="view"),
    ],
}

# Grupos criados por esta migração — só estes somem no desfazer; os demais
# preexistem e apenas perdem o que ganharam aqui.
GRUPOS_NOVOS = ["Candidato"]


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
        ("academic", "0010_requestdocument"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
