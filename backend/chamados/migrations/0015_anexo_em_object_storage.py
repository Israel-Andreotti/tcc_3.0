"""Anexos -> object storage (1/3): adiciona o vínculo com `midia.Arquivo` (ainda opcional).

Dividido em três migrations porque o PostgreSQL não permite alterar a tabela na mesma
transação em que os dados foram modificados ("pending trigger events").
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0014_anexo_no_banco'),
        ('midia', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='anexo',
            name='arquivo',
            field=models.OneToOneField(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name='anexo', to='midia.arquivo'
            ),
        ),
    ]
