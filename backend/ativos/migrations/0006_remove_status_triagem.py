"""Remove a situação "Triagem" dos ativos: os que estavam nela passam para "Disponível"."""

from django.db import migrations, models


def triagem_para_disponivel(apps, schema_editor):
    Ativo = apps.get_model('ativos', 'Ativo')
    Ativo.objects.filter(status='triagem').update(status='disponivel')


class Migration(migrations.Migration):

    dependencies = [
        ('ativos', '0005_movimentacao_protect'),
    ]

    operations = [
        migrations.RunPython(triagem_para_disponivel, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='ativo',
            name='status',
            field=models.CharField(
                choices=[('em_uso', 'Em uso'), ('disponivel', 'Disponível'), ('danificado', 'Danificado')],
                default='disponivel',
                max_length=20,
            ),
        ),
    ]
