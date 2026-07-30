"""Liga as Person já existentes à conta de mesmo e-mail.

Até a 0002 o vínculo entre Person e User existia só por coincidência de
e-mail, sem nenhuma chave. Esta migração materializa o que estava
implícito. O que não casar fica nulo — é caso legítimo (pessoa sem acesso)
e não deve virar erro.

Serve também de referência para rodar em produção: é a mesma lógica.
"""

from django.db import migrations


def vincular(apps, schema_editor):
    Person = apps.get_model("people", "Person")
    User = apps.get_model("accounts", "User")

    # Uma consulta só; o volume aqui é pequeno e o mapa evita N+1.
    contas = {
        email.lower(): pk
        for pk, email in User.objects.exclude(email="").values_list("pk", "email")
    }
    # O username também vale: create_person_with_user usa o e-mail como
    # username, então contas antigas podem ter username preenchido e email
    # vazio.
    contas |= {
        username.lower(): pk
        for pk, username in User.objects.values_list("pk", "username")
        if "@" in username
    }

    ligadas = 0
    vistos: set[tuple[int, int]] = set()
    for pessoa in Person.objects.filter(user__isnull=True).iterator():
        user_id = contas.get(pessoa.primary_email.lower())
        if user_id is None:
            continue
        # Respeita unique_conta_por_programa: se duas Person do mesmo
        # programa apontam para o mesmo e-mail, só a primeira é ligada.
        chave = (pessoa.program_id, user_id)
        if chave in vistos:
            continue
        vistos.add(chave)
        pessoa.user_id = user_id
        pessoa.save(update_fields=["user"])
        ligadas += 1

    if ligadas:
        print(f"  {ligadas} pessoa(s) vinculada(s) a contas existentes.")


def desvincular(apps, schema_editor):
    Person = apps.get_model("people", "Person")
    Person.objects.update(user=None)


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0002_person_user_person_unique_conta_por_programa"),
        ("accounts", "0001_initial"),
    ]

    operations = [migrations.RunPython(vincular, desvincular)]
