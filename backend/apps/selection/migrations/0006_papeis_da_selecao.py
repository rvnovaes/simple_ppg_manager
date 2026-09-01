"""Cria o papel Comissão de Seleção e estende os demais com as permissões do edital.

Secretaria e Coordenação nascem em `programs.0002_programa_inicial_e_papeis`,
Docente em `academic.0003_papeis_dos_cadastros`; aqui eles só ganham o que o
processo seletivo exige. Só **Comissão de Seleção** nasce nesta migração.

Quem faz o quê no processo seletivo (ADR-006 e Seção 5 do CLAUDE.md):

- Secretaria opera o edital: monta (processo, etapas, vagas, bancas), decide a
  inscrição (`change_application`: homologa ou indefere), é o único papel que
  baixa anexo de inscrição (`download_applicationdocument`) e dispara a
  convocação (`add_convocation`). Não pontua e não assina ata — isso é da banca.
- Docente é quem compõe banca: lança nota (`add/change_stagescore`), monta e
  congela a ata (`add/change_examinationrecord`) e a assina
  (`sign_examinationrecord`). Lê o edital, a banca e a inscrição para isso, mas
  **não** baixa documento: identidade e diploma são dado pessoal que a avaliação
  não precisa.
- Comissão de Seleção decide realocação de vaga (`add_vacancyreallocation`) —
  poder que a secretaria não tem, porque remanejar vaga entre alvos é decisão
  colegiada, não expediente. Lê todo o app para poder decidir.
- Coordenação só acompanha: leitura de tudo.

Nenhum grupo recebe `delete_*` nem `is_staff`/`is_superuser`: apagar é
quebra-vidro de sysadmin no Admin, e papel de domínio nunca abre o Admin.
Ata assinada, aliás, não se apaga em hipótese nenhuma — retifica-se com uma
versão nova (`ExaminationRecord.supersedes`).
"""

from django.db import migrations

# Todos os models do app: quem só acompanha recebe `view_` de cada um.
MODELS = [
    "selectionprocess",
    "selectionstage",
    "vacancy",
    "board",
    "application",
    "applicationdocument",
    "stagescore",
    "examinationrecord",
    "recordsignature",
    "vacancyreallocation",
    "convocation",
    "convocationemail",
]

TUDO_SO_LEITURA = [f"selection.view_{model}" for model in MODELS]


def _verbos(model: str, *verbos: str) -> list[str]:
    return [f"selection.{verbo}_{model}" for verbo in verbos]


# Papel -> permissões novas, no formato "app_label.codename".
NOVAS_PERMISSOES = {
    "Comissão de Seleção": [
        *TUDO_SO_LEITURA,
        "selection.add_vacancyreallocation",
    ],
    "Secretaria": [
        *TUDO_SO_LEITURA,
        *_verbos("selectionprocess", "add", "change"),
        *_verbos("selectionstage", "add", "change"),
        *_verbos("vacancy", "add", "change"),
        *_verbos("board", "add", "change"),
        *_verbos("application", "change"),
        "selection.download_applicationdocument",
        *_verbos("convocation", "add"),
    ],
    "Docente": [
        *_verbos("selectionprocess", "view"),
        *_verbos("board", "view"),
        *_verbos("application", "view"),
        *_verbos("stagescore", "add", "change", "view"),
        *_verbos("examinationrecord", "add", "change", "view"),
        "selection.sign_examinationrecord",
    ],
    "Coordenação": list(TUDO_SO_LEITURA),
}

# Grupos criados por esta migração — só estes somem no desfazer; os demais
# preexistem e apenas perdem o que ganharam aqui.
GRUPOS_NOVOS = ["Comissão de Seleção"]


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
        group.permissions.remove(
            *group.permissions.filter(
                codename__in=codenames, content_type__app_label="selection"
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("selection", "0005_vacancyreallocation_convocation_convocationemail"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
