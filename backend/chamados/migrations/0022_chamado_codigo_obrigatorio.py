"""Torna o código do chamado obrigatório e único (separado da 0021 porque o PostgreSQL não permite
alterar a tabela na mesma transação em que os dados foram atualizados)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0021_chamado_codigo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chamado',
            name='codigo',
            field=models.CharField(editable=False, max_length=12, unique=True),
        ),
    ]
