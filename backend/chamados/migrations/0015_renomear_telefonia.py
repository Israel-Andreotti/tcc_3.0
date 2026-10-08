from django.db import migrations

NOME_ANTIGO = 'Telefonia (ligações externas, transferência de chamadas)'
NOME_NOVO = 'Telefonia'


def renomear(apps, schema_editor, de, para):
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    Chamado = apps.get_model('chamados', 'Chamado')
    # Só renomeia se não houver já uma "Telefonia" na mesma categoria (unique_together).
    for sub in Subcategoria.objects.filter(nome=de):
        if not Subcategoria.objects.filter(categoria=sub.categoria, nome=para).exists():
            sub.nome = para
            sub.save(update_fields=['nome'])
            # O título do chamado é copiado do nome da subcategoria na abertura.
            Chamado.objects.filter(subcategoria=sub, titulo=de).update(titulo=para)


def aplicar(apps, schema_editor):
    renomear(apps, schema_editor, NOME_ANTIGO, NOME_NOVO)


def reverter(apps, schema_editor):
    renomear(apps, schema_editor, NOME_NOVO, NOME_ANTIGO)


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0014_remove_anexo'),
    ]

    operations = [
        migrations.RunPython(aplicar, reverter),
    ]
