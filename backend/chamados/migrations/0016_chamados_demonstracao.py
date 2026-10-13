"""Dados de demonstração: 4 solicitantes fictícios e 7 chamados abertos de prioridades variadas.

Roda em qualquer banco que aplicar a migration (local e produção). Os solicitantes de
demonstração têm login prefixado com `demo.` e senha inutilizável (não conseguem entrar).
Reverter remove esses chamados e usuários (os setores criados são mantidos).

Como migrations usam os modelos "históricos" (sem o save() customizado), aqui é feito à mão
o que o sistema faz sozinho: matrícula do usuário, prioridade copiada da subcategoria e prazo
de SLA (com o desconto de solicitante VIP).
"""

from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.utils import timezone

SLA_HORAS_PADRAO = {'critica': 4, 'alta': 8, 'media': 24, 'baixa': 72}
VIP_SLA_MULTIPLICADOR = 0.75

# login, nome, sobrenome, setor, vip
SOLICITANTES = [
    ('demo.paula', 'Paula', 'Martins', 'Enfermagem', False),
    ('demo.ricardo', 'Ricardo', 'Nunes', 'Laboratório', False),
    ('demo.fernanda', 'Fernanda', 'Rocha', 'Recepção', True),
    ('demo.joao', 'João', 'Pereira', 'Financeiro', False),
]

# solicitante, subcategoria, descrição, horas desde a abertura (para variar a situação do SLA)
CHAMADOS = [
    ('demo.paula', 'Prontuário eletrônico',
     'O prontuário eletrônico fecha sozinho ao salvar a evolução do paciente no posto 3.', 1),
    ('demo.ricardo', 'Sistema de laboratório/exames',
     'Os resultados de hemograma não estão sendo integrados ao sistema desde a troca de turno.', 5),
    ('demo.fernanda', 'Internet',
     'Sem acesso à internet nos computadores do balcão de atendimento.', 2),
    ('demo.paula', 'Wi-Fi',
     'O Wi-Fi da ala de internação cai a cada poucos minutos nos tablets da enfermagem.', 6),
    ('demo.joao', 'Instalação/configuração de software',
     'Preciso do leitor de PDF e do assinador digital instalados para conferir notas fiscais.', 10),
    ('demo.fernanda', 'Reset de senha',
     'Esqueci a senha do sistema de agendamento e meu usuário foi bloqueado.', 1),
    ('demo.ricardo', 'Impressora',
     'A impressora de etiquetas do laboratório está imprimindo com falhas nas bordas.', 30),
]


def _proxima_matricula(Usuario):
    ultima = (
        Usuario.objects.exclude(matricula='')
        .order_by('-matricula')
        .values_list('matricula', flat=True)
        .first()
    )
    return str(int(ultima) + 1) if ultima else '100001'


def criar_dados(apps, schema_editor):
    Usuario = apps.get_model('usuarios', 'Usuario')
    Setor = apps.get_model('usuarios', 'Setor')
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    SLAPrioridade = apps.get_model('chamados', 'SLAPrioridade')
    Chamado = apps.get_model('chamados', 'Chamado')

    solicitantes = {}
    for login, nome, sobrenome, nome_setor, vip in SOLICITANTES:
        setor, _ = Setor.objects.get_or_create(nome=nome_setor)
        usuario = Usuario.objects.filter(username=login).first()
        if usuario is None:
            usuario = Usuario.objects.create(
                username=login,
                first_name=nome,
                last_name=sobrenome,
                email=f'{login}@exemplo.com',
                perfil='solicitante',
                setor=setor,
                vip=vip,
                matricula=_proxima_matricula(Usuario),
                password=make_password(None),  # senha inutilizável: usuário só de demonstração
            )
        solicitantes[login] = usuario

    sla_horas = dict(SLAPrioridade.objects.values_list('prioridade', 'horas'))
    agora = timezone.now()
    for login, nome_sub, descricao, horas_atras in CHAMADOS:
        subcategoria = Subcategoria.objects.filter(nome=nome_sub).select_related('categoria').first()
        if subcategoria is None:  # subcategoria removida do catálogo neste banco
            continue
        solicitante = solicitantes[login]
        horas = sla_horas.get(subcategoria.prioridade, SLA_HORAS_PADRAO.get(subcategoria.prioridade, 24))
        if solicitante.vip:
            horas *= VIP_SLA_MULTIPLICADOR
        aberto_em = agora - timedelta(hours=horas_atras)
        chamado = Chamado.objects.create(
            titulo=subcategoria.nome,
            descricao=descricao,
            status='aberto',
            prioridade=subcategoria.prioridade,
            categoria=subcategoria.categoria,
            subcategoria=subcategoria,
            solicitante=solicitante,
            setor=solicitante.setor,
            prazo_sla=aberto_em + timedelta(hours=horas),
        )
        # criado_em é auto_now_add: ajusta depois para simular chamados abertos há algum tempo.
        Chamado.objects.filter(pk=chamado.pk).update(criado_em=aberto_em)


def remover_dados(apps, schema_editor):
    Usuario = apps.get_model('usuarios', 'Usuario')
    Chamado = apps.get_model('chamados', 'Chamado')
    logins = [login for login, *_ in SOLICITANTES]
    Chamado.objects.filter(solicitante__username__in=logins).delete()
    Usuario.objects.filter(username__in=logins).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0015_renomear_telefonia'),
        ('usuarios', '0008_usuario_super_admin'),
    ]

    operations = [
        migrations.RunPython(criar_dados, remover_dados),
    ]
