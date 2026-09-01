"""Cria o papel Comissão de Bolsas e estende os demais com as permissões do edital.

Espelho de `selection.0006_papeis_da_selecao` e de
`academic.0011_papeis_da_isolada`. Secretaria e Coordenação nascem em
`programs.0002_programa_inicial_e_papeis`, Discente em
`academic.0003_papeis_dos_cadastros`; aqui eles só ganham o que o edital de
bolsas exige. Só **Comissão de Bolsas** nasce nesta migração — é comissão
diferente da de Seleção, com composição própria por edição
(`CommitteeMember`), e juntar as duas num grupo só daria a quem julga
recurso de bolsa o poder de realocar vaga do processo seletivo.

Quem faz o quê no edital de bolsas (ADR-006 e Seção 5 do CLAUDE.md):

- Discente se inscreve (`add`/`view`/`change_scholarshipapplication`) e lança
  os itens do barema (`add`/`view`/`change_baremeentry`). Lê a edição e o
  barema para saber o que pontua. Interpõe recurso (`add`/`view`) e não o
  julga. **Não** há permissão sobre `ApplicationDocument`: anexar comprovante
  do questionário é editar a própria inscrição, exatamente como no
  requerimento de isolada — a permissão própria existe só para o *download*,
  que é leitura de dado pessoal alheio.
- Comissão de Bolsas avalia lançamento a lançamento (`review_baremeentry`,
  separada de `change_baremeentry` justamente para não confundir a nota do
  candidato com a da comissão), baixa o comprovante para conferir
  (`download_applicationdocument`) e julga o recurso
  (`change_scholarshipappeal`). Lê inscrição, lançamento, edição e barema.
  Não monta edital e não publica.
- Secretaria opera o edital: monta a edição, o barema e a comissão
  (`add`/`change`/`view`), lê inscrição e lançamento, baixa comprovante e tem
  as três permissões próprias — `publish_scholarshipedition` (publicar congela
  o ano), `set_fump_level` e `override_band` (os dois campos que ela escreve
  na inscrição **alheia**, sem receber `change` sobre ela). Não pontua e não
  julga recurso: isso é da comissão.
- Coordenação só acompanha: leitura de todo o app.

Nenhum grupo recebe `delete_*` nem `is_staff`/`is_superuser`: apagar é
quebra-vidro de sysadmin no Admin, e papel de domínio nunca abre o Admin.
"""

from django.db import migrations

# Todos os models do app: quem só acompanha recebe `view_` de cada um.
MODELS = [
    "scholarshipedition",
    "committeemember",
    "baremeitem",
    "scholarshipapplication",
    "applicationdocument",
    "baremeentry",
    "itemreview",
    "scholarshipappeal",
]

TUDO_SO_LEITURA = [f"scholarships.view_{model}" for model in MODELS]

# Permissões próprias (`Meta.permissions`, migration 0007 e as dos models
# anteriores): o codename não deriva do model, então o content type de cada
# uma vai explícito. Sem este mapa, `set_fump_level` procuraria um model
# chamado "fump_level" e criaria um content type fantasma.
MODEL_DA_PERMISSAO = {
    "publish_scholarshipedition": "scholarshipedition",
    "set_fump_level": "scholarshipapplication",
    "override_band": "scholarshipapplication",
    "download_applicationdocument": "applicationdocument",
    "review_baremeentry": "baremeentry",
}


def _verbos(model: str, *verbos: str) -> list[str]:
    return [f"scholarships.{verbo}_{model}" for verbo in verbos]


# Papel -> permissões novas, no formato "app_label.codename".
NOVAS_PERMISSOES = {
    "Comissão de Bolsas": [
        *_verbos("scholarshipedition", "view"),
        *_verbos("baremeitem", "view"),
        *_verbos("scholarshipapplication", "view"),
        *_verbos("baremeentry", "view"),
        "scholarships.review_baremeentry",
        "scholarships.download_applicationdocument",
        *_verbos("scholarshipappeal", "change"),
    ],
    "Secretaria": [
        *_verbos("scholarshipedition", "view", "add", "change"),
        *_verbos("baremeitem", "view", "add", "change"),
        *_verbos("committeemember", "view", "add", "change"),
        *_verbos("scholarshipapplication", "view"),
        *_verbos("baremeentry", "view"),
        "scholarships.download_applicationdocument",
        "scholarships.publish_scholarshipedition",
        "scholarships.set_fump_level",
        "scholarships.override_band",
    ],
    "Discente": [
        *_verbos("scholarshipedition", "view"),
        *_verbos("baremeitem", "view"),
        *_verbos("scholarshipapplication", "add", "view", "change"),
        *_verbos("baremeentry", "add", "view", "change"),
        *_verbos("scholarshipappeal", "add", "view"),
    ],
    "Coordenação": list(TUDO_SO_LEITURA),
}

# Grupos criados por esta migração — só estes somem no desfazer; os demais
# preexistem e apenas perdem o que ganharam aqui.
GRUPOS_NOVOS = ["Comissão de Bolsas"]


def criar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    for papel, perms in NOVAS_PERMISSOES.items():
        group, _ = Group.objects.get_or_create(name=papel)
        for perm in perms:
            app_label, codename = perm.split(".")
            model = MODEL_DA_PERMISSAO.get(codename) or codename.split("_", 1)[1]
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
                codename__in=codenames, content_type__app_label="scholarships"
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("scholarships", "0007_permissoes_proprias"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
