"""Comentario saiu de uso (a linha do tempo usa ProcedimentoEntry). Antes de apagar a tabela, cada
comentário que ainda exista vira um procedimento público, com o autor e a data originais."""

from django.db import migrations


def comentarios_para_procedimentos(apps, schema_editor):
    Comentario = apps.get_model('chamados', 'Comentario')
    ProcedimentoEntry = apps.get_model('chamados', 'ProcedimentoEntry')
    for comentario in Comentario.objects.all():
        procedimento = ProcedimentoEntry.objects.create(
            chamado_id=comentario.chamado_id, autor_id=comentario.autor_id, tipo='publico', texto=comentario.texto,
        )
        # criado_em é auto_now_add: a data original só pode ser gravada depois de criar.
        ProcedimentoEntry.objects.filter(pk=procedimento.pk).update(criado_em=comentario.criado_em)


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0023_fluxo_fechamento_simplificado'),
    ]

    operations = [
        migrations.RunPython(comentarios_para_procedimentos, migrations.RunPython.noop),
    ]
