from django.db import migrations

SLA_HORAS_PADRAO = {
    'critica': 4,
    'alta': 8,
    'media': 24,
    'baixa': 72,
}


def seed_sla(apps, schema_editor):
    SLAPrioridade = apps.get_model('chamados', 'SLAPrioridade')
    for prioridade, horas in SLA_HORAS_PADRAO.items():
        SLAPrioridade.objects.get_or_create(prioridade=prioridade, defaults={'horas': horas})


def remove_sla(apps, schema_editor):
    SLAPrioridade = apps.get_model('chamados', 'SLAPrioridade')
    SLAPrioridade.objects.filter(prioridade__in=SLA_HORAS_PADRAO.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0010_slaprioridade'),
    ]

    operations = [
        migrations.RunPython(seed_sla, remove_sla),
    ]
