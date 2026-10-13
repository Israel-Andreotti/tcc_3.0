"""Ciclo de encerramento: resolvido (aguarda confirmação do solicitante) -> fechado (definitivo).

Até aqui `fechado_em` guardava o momento em que o técnico resolvia. Para os chamados já
resolvidos, esse momento passa para `resolvido_em`, o SLA fica pausado a partir dele (como faz
`Chamado.resolver()`) e `fechado_em` fica vazio até o fechamento definitivo.
"""

from django.db import migrations, models
from django.db.models import F


def migrar_resolvidos(apps, schema_editor):
    Chamado = apps.get_model('chamados', 'Chamado')
    Chamado.objects.filter(status='resolvido').update(
        resolvido_em=F('fechado_em'), sla_pausado_em=F('fechado_em'), fechado_em=None
    )


def desfazer(apps, schema_editor):
    Chamado = apps.get_model('chamados', 'Chamado')
    Chamado.objects.filter(status='resolvido').update(fechado_em=F('resolvido_em'), sla_pausado_em=None)


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0016_chamados_demonstracao'),
    ]

    operations = [
        migrations.AddField(
            model_name='chamado',
            name='resolvido_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(migrar_resolvidos, desfazer),
    ]
