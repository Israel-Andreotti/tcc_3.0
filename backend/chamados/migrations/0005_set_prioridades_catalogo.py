from django.db import migrations

# Prioridade padrão por subcategoria, definida a partir da criticidade de cada grupo do catálogo:
# sistemas clínicos/assistenciais = crítica, infraestrutura de rede = alta,
# suporte ao usuário e acessos/permissões = média, equipamentos/periféricos = baixa.
PRIORIDADES = {
    'Prontuário eletrônico': 'critica',
    'Sistema de laboratório/exames': 'critica',
    'Sistema de agendamento/regulação': 'critica',

    'Internet': 'alta',
    'Ponto de rede': 'alta',
    'Wi-Fi': 'alta',
    'VPN': 'alta',
    'Telefonia (ligações externas, transferência de chamadas)': 'alta',

    'Reset de senha': 'media',
    'Instalação/configuração de software': 'media',
    'Instalação/remoção de computador': 'media',
    'Configuração de projeção/auditório': 'media',
    'Erro de acesso a site': 'media',

    'Impressora': 'baixa',
    'Scanner': 'baixa',
    'Toner': 'baixa',
    'Limpeza preventiva': 'baixa',
    'Mouse/teclado': 'baixa',
    'Webcam': 'baixa',
    'Manutenção de computador': 'baixa',

    'Criação/exclusão/alteração de usuário': 'media',
    'Listas de e-mail': 'media',
    'Permissões de pastas compartilhadas': 'media',
}


def set_prioridades(apps, schema_editor):
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    Chamado = apps.get_model('chamados', 'Chamado')

    for subcategoria in Subcategoria.objects.all():
        prioridade = PRIORIDADES.get(subcategoria.nome)
        if prioridade:
            subcategoria.prioridade = prioridade
            subcategoria.save(update_fields=['prioridade'])

    # Realinha chamados já existentes com a prioridade da subcategoria escolhida.
    for chamado in Chamado.objects.select_related('subcategoria').filter(subcategoria__isnull=False):
        if chamado.prioridade != chamado.subcategoria.prioridade:
            chamado.prioridade = chamado.subcategoria.prioridade
            chamado.save(update_fields=['prioridade'])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0004_subcategoria_prioridade'),
    ]

    operations = [
        migrations.RunPython(set_prioridades, reverse_noop),
    ]
