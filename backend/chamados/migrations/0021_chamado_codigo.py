"""Código de exibição do chamado: INC000001 (incidentes) e REQ000001 (requisições), cada tipo com a
sua própria numeração em sequências do PostgreSQL. Os chamados existentes são numerados pela ordem
de abertura e as sequências continuam do último número usado."""

from django.db import migrations, models

SEQUENCIAS = {'incidente': ('INC', 'chamados_codigo_inc_seq'), 'requisicao': ('REQ', 'chamados_codigo_req_seq')}


def numerar_existentes(apps, schema_editor):
    Chamado = apps.get_model('chamados', 'Chamado')
    with schema_editor.connection.cursor() as cursor:
        for tipo, (prefixo, sequencia) in SEQUENCIAS.items():
            ids = Chamado.objects.filter(tipo=tipo).order_by('criado_em', 'pk').values_list('pk', flat=True)
            for numero, pk in enumerate(ids, start=1):
                Chamado.objects.filter(pk=pk).update(codigo=f'{prefixo}{numero:06d}')
            total = len(ids)
            # Próximo nextval() devolve total + 1 (ou 1, se não houver nenhum chamado desse tipo).
            cursor.execute('SELECT setval(%s, %s, %s)', [sequencia, max(total, 1), total > 0])


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0020_tipo_incidente_requisicao'),
    ]

    operations = [
        migrations.AddField(
            model_name='chamado',
            name='codigo',
            field=models.CharField(editable=False, max_length=12, null=True),
        ),
        migrations.RunSQL(
            sql=[
                'CREATE SEQUENCE IF NOT EXISTS chamados_codigo_inc_seq',
                'CREATE SEQUENCE IF NOT EXISTS chamados_codigo_req_seq',
            ],
            reverse_sql=[
                'DROP SEQUENCE IF EXISTS chamados_codigo_inc_seq',
                'DROP SEQUENCE IF EXISTS chamados_codigo_req_seq',
            ],
        ),
        migrations.RunPython(numerar_existentes, migrations.RunPython.noop),
    ]
