"""Fluxo de encerramento simplificado: o técnico fecha o chamado (não existe mais o status
"resolvido" aguardando a confirmação do solicitante). O solicitante pode reabrir em até
Chamado.DIAS_REABERTURA dias.

Dados: chamados "resolvido" passam a "fechado". O momento do fechamento passa a ser o da
conclusão pelo técnico (o antigo `resolvido_em`), que é o que os indicadores já usavam; a data
da confirmação (antigo `fechado_em`) é descartada.
"""

from django.db import migrations, models


def resolvidos_para_fechados(apps, schema_editor):
    Chamado = apps.get_model('chamados', 'Chamado')
    Chamado.objects.filter(status='resolvido').update(status='fechado')


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0022_chamado_codigo_obrigatorio'),
    ]

    operations = [
        migrations.RunPython(resolvidos_para_fechados, migrations.RunPython.noop),
        migrations.RemoveField(model_name='chamado', name='fechado_em'),
        migrations.RenameField(model_name='chamado', old_name='resolvido_em', new_name='fechado_em'),
        migrations.RenameField(model_name='chamado', old_name='resolvido_no_prazo', new_name='fechado_no_prazo'),
        migrations.AlterField(
            model_name='chamado',
            name='status',
            field=models.CharField(
                choices=[
                    ('aberto', 'Aberto'),
                    ('em_andamento', 'Em andamento'),
                    ('aguardando_solicitante', 'Aguardando solicitante'),
                    ('fechado', 'Fechado'),
                ],
                default='aberto',
                max_length=25,
            ),
        ),
    ]
