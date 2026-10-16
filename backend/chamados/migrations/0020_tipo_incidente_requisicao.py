"""ITIL: separa incidente (interrupção/degradação de um serviço) de requisição de serviço (pedido de
algo padrão). O tipo fica na subcategoria do catálogo e é herdado pelo chamado na abertura.

O catálogo atual é classificado pelo nome das subcategorias; qualquer outra (ex.: criada pelo
administrador) fica como incidente e pode ser ajustada na tela da categoria. Os chamados existentes
herdam o tipo da subcategoria.
"""

from django.db import migrations, models
from django.db.models import OuterRef, Subquery

REQUISICOES = [
    'Reset de senha',
    'Instalação/configuração de software',
    'Instalação/remoção de computador',
    'Configuração de projeção/auditório',
    'Ponto de rede',
    'Toner',
    'Limpeza preventiva',
    'Criação/exclusão/alteração de usuário',
    'Listas de e-mail',
    'Permissões de pastas compartilhadas',
]

TIPOS = [('incidente', 'Incidente'), ('requisicao', 'Requisição')]


def classificar(apps, schema_editor):
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    Chamado = apps.get_model('chamados', 'Chamado')
    Subcategoria.objects.filter(nome__in=REQUISICOES).update(tipo='requisicao')
    Chamado.objects.filter(subcategoria__isnull=False).update(
        tipo=Subquery(Subcategoria.objects.filter(pk=OuterRef('subcategoria_id')).values('tipo')[:1])
    )


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0019_eventochamado'),
    ]

    operations = [
        migrations.AddField(
            model_name='subcategoria',
            name='tipo',
            field=models.CharField(choices=TIPOS, default='incidente', max_length=10),
        ),
        migrations.AddField(
            model_name='chamado',
            name='tipo',
            field=models.CharField(choices=TIPOS, default='incidente', max_length=10),
        ),
        migrations.RunPython(classificar, migrations.RunPython.noop),
    ]
