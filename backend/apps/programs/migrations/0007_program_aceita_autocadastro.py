"""Interruptor de autocadastro por programa, com backfill dos ativos.

O default do campo é False — é o certo para programa novo, que só abre o
cadastro público quando alguém decide abrir. Mas aplicar só o AddField num
banco que já roda derruba, em silêncio, o autocadastro que hoje funciona
por edital aberto: a lista pública nasceria vazia e ninguém veria erro
nenhum. Por isso o RunPython liga o flag em todo programa já ativo,
preservando o estado de antes da migração.
"""

from django.db import migrations, models


def ligar_nos_ativos(apps, schema_editor):
    Program = apps.get_model("programs", "Program")
    Program.objects.filter(is_active=True).update(accepts_self_signup=True)


def desfazer(apps, schema_editor):
    """No-op: o AddField reverso derruba a coluna inteira, então não há
    estado anterior a restaurar. Existe para que a migração seja
    reversível sem `elidable`/`RunPython.noop` mudo.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("programs", "0006_discipline"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="accepts_self_signup",
            field=models.BooleanField(default=False, verbose_name="aceita autocadastro"),
        ),
        migrations.RunPython(ligar_nos_ativos, desfazer),
    ]
