"""Cria o papel marcador Cadastro pendente e dá AccessRequest a quem decide.

Continua `academic.0011_papeis_da_isolada`, que não pode ser editada porque
já está aplicada. Só "Cadastro pendente" nasce aqui; Secretaria e Coordenação
vêm de `programs.0002_programa_inicial_e_papeis`.

Quem faz o quê no autocadastro (Seção 5 do CLAUDE.md):

- "Cadastro pendente" tem lista de permissões VAZIA de propósito. Não é
  papel: é **marcador de estado**. Ele não concede nada — quem o carrega
  sozinho não pode nem ler o próprio `AccessRequest` pelas permissões
  nativas, e é justamente esse o ponto: a conta existe, mas ainda não
  entrou em nenhum papel de domínio. O marcador viaja para o front em
  `UserOut.groups` (`apps/accounts/schemas.py`), que é como a SPA desvia o
  recém-cadastrado para a tela de espera em vez de para uma tela vazia.
- Secretaria decide: lê a fila (`view`) e aprova ou recusa (`change`). Não
  ganha `add_accessrequest` — quem abre a solicitação é a própria pessoa,
  pelo endpoint público de autocadastro, nunca a secretaria por dentro.
- Coordenação só acompanha (`view`).

Trade-off assumido no desenho do marcador: o Group é do **User** (global) e
a `Person` é por **programa**. Quem já é docente no programa A e se
autocadastra no programa B carrega "Cadastro pendente" em toda a sessão,
inclusive enquanto atua em A — o marcador não sabe dizer *onde* a pessoa
está pendente. A mitigação é do front: a tela de espera só captura quem não
tem nenhum papel efetivo (`permissions.length === 0`), então o docente de A
segue usando o sistema normalmente. A alternativa sem furo seria um marcador
por programa, o que obrigaria `accounts` a importar `academic` para montar o
`UserOut` — dependência proibida, e cara demais para o caso.

Nenhum grupo recebe `delete_*` nem `is_staff`/`is_superuser`: apagar é
quebra-vidro de sysadmin no Admin, e papel de domínio nunca abre o Admin.
"""

from django.db import migrations

SOLICITACAO = "academic.{verbo}_accessrequest"

# Papel -> permissões novas, no formato "app_label.codename".
# Lista vazia é entrada válida: cria o Group e não concede nada (ver acima).
NOVAS_PERMISSOES: dict[str, list[str]] = {
    "Cadastro pendente": [],
    "Secretaria": [
        SOLICITACAO.format(verbo="view"),
        SOLICITACAO.format(verbo="change"),
    ],
    "Coordenação": [
        SOLICITACAO.format(verbo="view"),
    ],
}

# Grupos criados por esta migração — só estes somem no desfazer; os demais
# preexistem e apenas perdem o que ganharam aqui.
GRUPOS_NOVOS = ["Cadastro pendente"]


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
        ("academic", "0013_accessrequest"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(criar, desfazer)]
