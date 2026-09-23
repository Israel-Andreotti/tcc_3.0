from django.db import migrations

CATALOGO = [
    ('Sistemas clínicos/assistenciais', [
        'Prontuário eletrônico',
        'Sistema de laboratório/exames',
        'Sistema de agendamento/regulação',
    ]),
    ('Infraestrutura de rede', [
        'Internet',
        'Ponto de rede',
        'Wi-Fi',
        'VPN',
        'Telefonia (ligações externas, transferência de chamadas)',
    ]),
    ('Suporte ao usuário', [
        'Reset de senha',
        'Instalação/configuração de software',
        'Instalação/remoção de computador',
        'Configuração de projeção/auditório',
        'Erro de acesso a site',
    ]),
    ('Equipamentos e periféricos', [
        'Impressora',
        'Scanner',
        'Toner',
        'Limpeza preventiva',
        'Mouse/teclado',
        'Webcam',
        'Manutenção de computador',
    ]),
    ('Acessos e permissões', [
        'Criação/exclusão/alteração de usuário',
        'Listas de e-mail',
        'Permissões de pastas compartilhadas',
    ]),
]


def seed_catalogo(apps, schema_editor):
    Categoria = apps.get_model('chamados', 'Categoria')
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    for ordem, (nome_categoria, subitens) in enumerate(CATALOGO, start=1):
        categoria, _ = Categoria.objects.get_or_create(nome=nome_categoria, defaults={'ordem': ordem})
        for nome_sub in subitens:
            Subcategoria.objects.get_or_create(categoria=categoria, nome=nome_sub)


def remove_catalogo(apps, schema_editor):
    Categoria = apps.get_model('chamados', 'Categoria')
    nomes = [nome for nome, _ in CATALOGO]
    Categoria.objects.filter(nome__in=nomes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0002_categoria_chamado_categoria_subcategoria_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_catalogo, remove_catalogo),
    ]
