"""Campos usados pelos indicadores de gestão, com o preenchimento possível dos chamados antigos.

- primeira_resposta_em: primeiro procedimento público registrado por alguém que não é o solicitante
  (ou a resolução, se o chamado foi resolvido sem nenhum registro antes).
- resolvido_no_prazo: resolução até o prazo do SLA (só para resolvidos/fechados).
- pediu_info: chamado que está ou já esteve aguardando o solicitante (tempo de SLA pausado).
- atribuido_em, reaberturas e avaliacao não têm como ser recuperados: valem a partir de agora.
"""

from django.db import migrations, models
from django.db.models import F, OuterRef, Q, Subquery


def preencher_antigos(apps, schema_editor):
    Chamado = apps.get_model('chamados', 'Chamado')
    ProcedimentoEntry = apps.get_model('chamados', 'ProcedimentoEntry')

    primeira_resposta = (
        ProcedimentoEntry.objects.filter(chamado=OuterRef('pk'), tipo='publico')
        .exclude(autor=OuterRef('solicitante'))
        .order_by('criado_em')
        .values('criado_em')[:1]
    )
    Chamado.objects.update(primeira_resposta_em=Subquery(primeira_resposta))
    Chamado.objects.filter(primeira_resposta_em__isnull=True, resolvido_em__isnull=False).update(
        primeira_resposta_em=F('resolvido_em')
    )

    encerrados = Chamado.objects.filter(resolvido_em__isnull=False, prazo_sla__isnull=False)
    encerrados.filter(resolvido_em__lte=F('prazo_sla')).update(resolvido_no_prazo=True)
    encerrados.filter(resolvido_em__gt=F('prazo_sla')).update(resolvido_no_prazo=False)

    Chamado.objects.filter(
        Q(status='aguardando_solicitante') | Q(sla_tempo_pausado__gt='0 seconds')
    ).update(pediu_info=True)


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0017_chamado_resolvido_em'),
    ]

    operations = [
        migrations.AddField(model_name='chamado', name='atribuido_em',
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='chamado', name='primeira_resposta_em',
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='chamado', name='resolvido_no_prazo',
                            field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name='chamado', name='reaberturas',
                            field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='chamado', name='pediu_info',
                            field=models.BooleanField(default=False)),
        migrations.AddField(model_name='chamado', name='avaliacao',
                            field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.RunPython(preencher_antigos, migrations.RunPython.noop),
    ]
