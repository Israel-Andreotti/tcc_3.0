from django.db import migrations


class Migration(migrations.Migration):
    """Remove a funcionalidade de anexos de chamados (upload de arquivos)."""

    dependencies = [
        ('chamados', '0013_resposta_solicitante_em'),
    ]

    operations = [
        migrations.DeleteModel(name='Anexo'),
    ]
