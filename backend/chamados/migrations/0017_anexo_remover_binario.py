"""Anexos -> object storage (3/3): remove o binário/metadados antigos e torna o vínculo obrigatório."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0016_anexo_copiar_para_storage'),
    ]

    operations = [
        migrations.RemoveField(model_name='anexo', name='conteudo'),
        migrations.RemoveField(model_name='anexo', name='content_type'),
        migrations.RemoveField(model_name='anexo', name='nome'),
        migrations.RemoveField(model_name='anexo', name='tamanho'),
        migrations.AlterField(
            model_name='anexo',
            name='arquivo',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT, related_name='anexo', to='midia.arquivo'
            ),
        ),
    ]
