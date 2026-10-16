"""Log do ciclo de vida do chamado (EventoChamado), com a reconstrução possível para os chamados
existentes: abertura, primeira atribuição, resolução e fechamento, nas datas já registradas."""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def reconstruir_eventos(apps, schema_editor):
    Chamado = apps.get_model('chamados', 'Chamado')
    EventoChamado = apps.get_model('chamados', 'EventoChamado')
    novos = []
    for c in Chamado.objects.all().iterator():
        novos.append(EventoChamado(
            chamado_id=c.pk, tipo='abertura', autor_id=c.solicitante_id, criado_em=c.criado_em,
            descricao='Abriu o chamado (registro reconstruído).',
        ))
        if c.atribuido_em and c.atendente_id:
            novos.append(EventoChamado(
                chamado_id=c.pk, tipo='atribuicao', autor_id=c.atendente_id, criado_em=c.atribuido_em,
                descricao='Assumiu o chamado (registro reconstruído).',
            ))
        if c.resolvido_em:
            novos.append(EventoChamado(
                chamado_id=c.pk, tipo='resolvido', autor_id=c.atendente_id, criado_em=c.resolvido_em,
                descricao='Marcou como resolvido (registro reconstruído).',
            ))
        if c.status == 'fechado' and c.fechado_em:
            novos.append(EventoChamado(
                chamado_id=c.pk, tipo='fechado', autor_id=None, criado_em=c.fechado_em,
                descricao='Fechou o chamado (registro reconstruído).',
            ))
    EventoChamado.objects.bulk_create(novos, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0018_dados_indicadores'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EventoChamado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[
                    ('abertura', 'Abertura'), ('atribuicao', 'Atribuição'), ('reatribuicao', 'Reatribuição'),
                    ('aguardando', 'Aguardando solicitante'), ('retomado', 'Atendimento retomado'),
                    ('respondido', 'Resposta do solicitante'), ('resolvido', 'Resolução'), ('reaberto', 'Reabertura'),
                    ('fechado', 'Fechamento'), ('avaliado', 'Avaliação'), ('movimentacao', 'Movimentação de ativo'),
                ], max_length=20)),
                ('descricao', models.CharField(max_length=255)),
                ('publico', models.BooleanField(default=True)),
                ('criado_em', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('autor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                            related_name='+', to=settings.AUTH_USER_MODEL)),
                ('chamado', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='eventos',
                                              to='chamados.chamado')),
            ],
            options={
                'verbose_name': 'Evento do chamado',
                'verbose_name_plural': 'Eventos do chamado',
                'ordering': ['criado_em', 'pk'],
            },
        ),
        migrations.RunPython(reconstruir_eventos, migrations.RunPython.noop),
    ]
