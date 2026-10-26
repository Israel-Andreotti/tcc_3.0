"""Simulação de uso para a demonstração do sistema (comando `simular_demo`).

Cada execução é um "passo" do dia de trabalho: solicitantes fictícios abrem chamados e técnicos
fictícios os atendem (assumem, registram procedimentos, pedem informação, fecham); os solicitantes
respondem, avaliam e às vezes reabrem. Rodando a cada poucos minutos, a fila se mexe sozinha e o
painel de indicadores ganha dados.

Regras de segurança:
- Só mexe em chamados abertos por usuários fictícios (login `demo.`) e que estejam sem técnico ou
  com um técnico fictício — o que uma pessoa real abriu ou assumiu nunca é tocado.
- Tudo passa pelos mesmos métodos do model e registra os mesmos eventos das telas, então os
  chamados simulados são indistinguíveis dos reais na linha do tempo e nos indicadores.
- Usuários fictícios têm senha inutilizável (ninguém entra com eles).
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from usuarios.models import Setor, Usuario

from .models import Chamado, EventoChamado, ProcedimentoEntry, Subcategoria

PREFIXO = 'demo.'
CHANCE_ABRIR = 0.6  # por passo; com o cron a cada 10 min, dá uns 3 a 4 chamados por hora
LIMITE_ABERTOS = 30  # acima disso não abre chamados novos, só atende os que existem
IDADE_MINIMA = timedelta(minutes=2)  # ninguém reage a um chamado no mesmo instante em que ele muda
# Parte dos chamados é "demorada", para o SLA às vezes estourar e os indicadores não ficarem todos
# em 100%: só fecham depois do prazo de SLA (+30 min) ou de DEMORA_MAXIMA, o que vier primeiro —
# na prática, críticos e altos estouram; médios e baixos ficam algumas horas na fila.
FRACAO_DEMORADOS = 0.25
DEMORA_MAXIMA = timedelta(hours=10)
FRACAO_SEM_AVALIACAO = 0.3  # nem todo solicitante avalia o atendimento
FRACAO_REABERTOS = 0.08  # chamados que o solicitante reabre (uma vez) por não ter sido resolvido

# login, nome, sobrenome, setor, vip (os quatro primeiros já vêm da migration 0016)
SOLICITANTES = [
    ('demo.paula', 'Paula', 'Martins', 'Enfermagem', False),
    ('demo.ricardo', 'Ricardo', 'Nunes', 'Laboratório', False),
    ('demo.fernanda', 'Fernanda', 'Rocha', 'Recepção', True),
    ('demo.joao', 'João', 'Pereira', 'Financeiro', False),
    ('demo.luciana', 'Luciana', 'Prado', 'Emergência', False),
    ('demo.andre', 'André', 'Souza', 'UTI Neonatal', False),
    ('demo.camila', 'Camila', 'Teixeira', 'Farmácia', False),
    ('demo.roberto', 'Roberto', 'Gomes', 'Faturamento', False),
]
TECNICOS = [
    ('demo.carlos', 'Carlos', 'Lima'),
    ('demo.beatriz', 'Beatriz', 'Alves'),
    ('demo.marcos', 'Marcos', 'Ribeiro'),
    ('demo.juliana', 'Juliana', 'Costa'),
    ('demo.tiago', 'Tiago', 'Mendes'),
]

# Descrições por subcategoria do catálogo; as que não estiverem aqui usam DESCRICAO_GENERICA.
DESCRICOES = {
    'Internet': [
        'Sem acesso à internet nos computadores do posto de enfermagem.',
        'A internet está muito lenta desde o início do turno, os sistemas web não carregam.',
    ],
    'Wi-Fi': [
        'Os tablets da enfermagem perdem o Wi-Fi a cada poucos minutos na ala B.',
        'O Wi-Fi da sala de reuniões não aparece na lista de redes.',
    ],
    'VPN': ['Não consigo conectar na VPN de casa para acessar o sistema de faturamento.'],
    'Telefonia': [
        'O ramal da recepção está mudo desde a manhã.',
        'O telefone do posto 2 não recebe ligações externas.',
    ],
    'Ponto de rede': ['Precisamos de um ponto de rede novo para o computador da sala de triagem.'],
    'Prontuário eletrônico': [
        'O prontuário eletrônico fecha sozinho ao salvar a evolução do paciente.',
        'Não consigo assinar a prescrição no prontuário, dá erro de certificado.',
    ],
    'Sistema de agendamento/regulação': [
        'A agenda de consultas não mostra os horários de amanhã.',
        'O sistema de regulação está fora do ar, não conseguimos solicitar vagas.',
    ],
    'Sistema de laboratório/exames': [
        'Os resultados de exames não estão sendo integrados ao prontuário.',
        'O sistema do laboratório não imprime as etiquetas das amostras.',
    ],
    'Reset de senha': [
        'Esqueci a senha do sistema e meu usuário foi bloqueado.',
        'Minha senha do e-mail expirou e não consigo trocar.',
    ],
    'Instalação/configuração de software': [
        'Preciso do assinador digital instalado para conferir documentos.',
        'Solicito a instalação do leitor de PDF no computador da coordenação.',
    ],
    'Impressora': [
        'A impressora do setor está imprimindo com manchas.',
        'A impressora não aparece no computador depois da atualização.',
    ],
    'Toner': ['O toner da impressora da recepção acabou.'],
    'Mouse/teclado': ['O teclado do computador do balcão está com teclas falhando.'],
    'Manutenção de computador': ['O computador demora muito para ligar e trava ao abrir o sistema.'],
    'Permissões de pastas compartilhadas': ['Preciso de acesso à pasta compartilhada da coordenação.'],
}
DESCRICAO_GENERICA = 'Preciso de ajuda com {servico}.'

PROCEDIMENTOS = [
    'Verificando o problema remotamente.',
    'Analisando os registros do sistema para identificar a causa.',
    'Contato feito com o setor; vou até o local verificar.',
]
PEDIDOS_DE_INFORMACAO = [
    'Pode informar o número do patrimônio do equipamento?',
    'Em qual computador acontece? Informe o nome que aparece na etiqueta.',
    'O erro aparece para todos do setor ou só para você?',
]
RESPOSTAS = [
    'É o computador da etiqueta ENF-03.',
    'Acontece só no meu usuário.',
    'Acontece com todos do setor.',
]
SOLUCOES = [
    'Configuração corrigida e testada com o usuário. Problema resolvido.',
    'Equipamento reiniciado e atualizado; funcionando normalmente.',
    'Acesso liberado e testado junto ao solicitante.',
]
MOTIVOS_REABERTURA = ['O problema voltou a acontecer hoje de manhã.', 'Continua com o mesmo erro.']

# Avaliações com distribuição realista (maioria satisfeita).
NOTAS = [5, 4, 3, 2, 1]
PESOS_NOTAS = [45, 30, 12, 8, 5]


class Simulador:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.acoes = []

    # ---- usuários fictícios ----

    def preparar_usuarios(self):
        """Garante os solicitantes e técnicos fictícios (com senha inutilizável)."""
        for login, nome, sobrenome, nome_setor, vip in SOLICITANTES:
            setor, _ = Setor.objects.get_or_create(nome=nome_setor)
            self._usuario(login, nome, sobrenome, Usuario.Perfil.SOLICITANTE, setor=setor, vip=vip)
        for login, nome, sobrenome in TECNICOS:
            self._usuario(login, nome, sobrenome, Usuario.Perfil.ATENDENTE)
        self.solicitantes = list(Usuario.objects.filter(username__startswith=PREFIXO, perfil=Usuario.Perfil.SOLICITANTE, is_active=True))
        self.tecnicos = list(Usuario.objects.filter(username__startswith=PREFIXO, perfil=Usuario.Perfil.ATENDENTE, is_active=True))

    @staticmethod
    def _usuario(login, nome, sobrenome, perfil, **campos):
        usuario = Usuario.objects.filter(username=login).first()
        if usuario is None:
            usuario = Usuario(username=login, first_name=nome, last_name=sobrenome, perfil=perfil,
                              email=f'{login}@exemplo.com', **campos)
            usuario.set_unusable_password()
            usuario.save()
        return usuario

    # ---- um passo da simulação ----

    def passo(self, novos=1):
        self.preparar_usuarios()
        abertos = Chamado.objects.exclude(status=Chamado.Status.FECHADO).count()
        for _ in range(novos):
            if abertos < LIMITE_ABERTOS and self.rng.random() < CHANCE_ABRIR:
                self.abrir_chamado()
                abertos += 1
        self.atender()
        return self.acoes

    def abrir_chamado(self):
        solicitante = self.rng.choice(self.solicitantes)
        subcategoria = self.rng.choice(list(Subcategoria.objects.select_related('categoria')))
        descricao = self.rng.choice(DESCRICOES.get(subcategoria.nome) or [DESCRICAO_GENERICA.format(servico=subcategoria.nome.lower())])
        chamado = Chamado.objects.create(
            titulo=subcategoria.nome, descricao=descricao, solicitante=solicitante, setor=solicitante.setor,
            categoria=subcategoria.categoria, subcategoria=subcategoria,
        )
        texto = f'Abriu o chamado ({chamado.get_tipo_display().lower()}) — prioridade {chamado.get_prioridade_display()}'
        if chamado.prioridade != subcategoria.prioridade:
            texto += ' (elevada por setor crítico)'
        texto += f', prazo de SLA {timezone.localtime(chamado.prazo_sla):%d/%m/%Y %H:%M}.'
        chamado.registrar_evento(EventoChamado.Tipo.ABERTURA, solicitante, texto)
        self._registrar(chamado, 'aberto')
        return chamado

    def candidatos(self):
        """Chamados que a simulação pode movimentar: de solicitantes fictícios, sem técnico ou com
        técnico fictício, sem movimentação de ativo pendente, e parados há pelo menos IDADE_MINIMA."""
        agora = timezone.now()
        # Fechados só interessam enquanto ainda podem ser avaliados ou reabertos.
        fechado_encerrado = Q(status=Chamado.Status.FECHADO) & (
            Q(avaliacao__isnull=False) | Q(fechado_em__lt=agora - timedelta(days=Chamado.DIAS_REABERTURA))
        )
        return (
            Chamado.objects.filter(solicitante__username__startswith=PREFIXO, atualizado_em__lte=agora - IDADE_MINIMA)
            .filter(Q(atendente__isnull=True) | Q(atendente__username__startswith=PREFIXO))
            .exclude(fechado_encerrado)
            .exclude(movimentacoes_ativo__status='pendente')
            .select_related('solicitante', 'atendente', 'subcategoria')
        )

    def atender(self):
        for chamado in self.candidatos().order_by('?'):
            with transaction.atomic():
                self._avancar(chamado)

    def _avancar(self, chamado):
        sorte = self.rng.random()
        status = chamado.status
        if status == Chamado.Status.ABERTO:
            if sorte < 0.5:
                self.assumir(chamado)
        elif status == Chamado.Status.EM_ANDAMENTO:
            ja_respondeu = chamado.procedimentos.filter(tipo=ProcedimentoEntry.Tipo.PUBLICO).exists()
            if not ja_respondeu:
                if sorte < 0.15:
                    self.pedir_informacao(chamado)
                elif sorte < 0.6:
                    self.registrar_procedimento(chamado)
            elif sorte < 0.35 and not self._segurar(chamado):
                self.fechar(chamado)
        elif status == Chamado.Status.AGUARDANDO_SOLICITANTE:
            if sorte < 0.5:
                self.responder(chamado)
        elif status == Chamado.Status.FECHADO and chamado.pode_reabrir:
            if chamado.avaliacao is not None or sorte >= 0.4:
                return
            if chamado.reaberturas == 0 and self._sorteio(chamado, 31) < FRACAO_REABERTOS:
                self.reabrir(chamado)  # no máximo uma vez, e antes de avaliar
            elif self._sorteio(chamado, 7919) >= FRACAO_SEM_AVALIACAO:
                self.avaliar(chamado)

    @staticmethod
    def _segurar(chamado):
        """Chamado demorado que ainda não chegou ao ponto de fechar. O sorteio usa o próprio chamado
        como semente, então ele é sempre demorado (ou nunca), passo após passo."""
        if Simulador._sorteio(chamado, 1) >= FRACAO_DEMORADOS:
            return False
        limite = min(chamado.prazo_sla + timedelta(minutes=30), chamado.criado_em + DEMORA_MAXIMA)
        return timezone.now() < limite

    @staticmethod
    def _sorteio(chamado, sal):
        """Número fixo por chamado (0 a 1): decide traços dele — se reabre, se avalia — de uma vez,
        em vez de sortear a cada passo (o que faria quase todo chamado acabar reaberto)."""
        return random.Random(chamado.pk * sal).random()

    # ---- ações (os mesmos passos e textos das telas) ----

    def assumir(self, chamado):
        tecnico = self.rng.choice(self.tecnicos)
        chamado.atribuir(tecnico)
        chamado.save()
        chamado.registrar_evento(EventoChamado.Tipo.ATRIBUICAO, tecnico, 'Assumiu o chamado.')
        self._registrar(chamado, f'assumido por {tecnico.first_name}')

    def registrar_procedimento(self, chamado):
        ProcedimentoEntry.objects.create(chamado=chamado, autor=chamado.atendente,
                                         tipo=ProcedimentoEntry.Tipo.PUBLICO, texto=self.rng.choice(PROCEDIMENTOS))
        chamado.registrar_primeira_resposta()
        chamado.save()
        self._registrar(chamado, 'procedimento registrado')

    def pedir_informacao(self, chamado):
        ProcedimentoEntry.objects.create(chamado=chamado, autor=chamado.atendente,
                                         tipo=ProcedimentoEntry.Tipo.PUBLICO, texto=self.rng.choice(PEDIDOS_DE_INFORMACAO))
        chamado.registrar_primeira_resposta()
        chamado.pediu_info = True
        chamado.status = Chamado.Status.AGUARDANDO_SOLICITANTE
        chamado.pausar_sla()
        chamado.save()
        chamado.registrar_evento(EventoChamado.Tipo.AGUARDANDO, chamado.atendente,
                                 'Pausou o atendimento aguardando o solicitante (SLA pausado).')
        self._registrar(chamado, 'aguardando o solicitante')

    def responder(self, chamado):
        ProcedimentoEntry.objects.create(chamado=chamado, autor=chamado.solicitante,
                                         tipo=ProcedimentoEntry.Tipo.RESPOSTA, texto=self.rng.choice(RESPOSTAS))
        chamado.status = Chamado.Status.EM_ANDAMENTO
        chamado.retomar_sla()
        chamado.resposta_solicitante_em = timezone.now()
        chamado.save()
        chamado.registrar_evento(EventoChamado.Tipo.RESPONDIDO, chamado.solicitante,
                                 'Respondeu; o chamado voltou para atendimento (SLA retomado).')
        self._registrar(chamado, 'respondido pelo solicitante')

    def fechar(self, chamado):
        ProcedimentoEntry.objects.create(chamado=chamado, autor=chamado.atendente,
                                         tipo=ProcedimentoEntry.Tipo.PUBLICO, texto=self.rng.choice(SOLUCOES))
        chamado.resposta_solicitante_em = None  # o técnico fictício "viu" a resposta
        chamado.fechar()
        chamado.save()
        prazo = 'dentro do prazo de SLA' if chamado.fechado_no_prazo else 'fora do prazo de SLA'
        chamado.registrar_evento(EventoChamado.Tipo.FECHADO, chamado.atendente, f'Fechou o chamado ({prazo}).')
        self._registrar(chamado, 'fechado')

    def avaliar(self, chamado):
        nota = self.rng.choices(NOTAS, weights=PESOS_NOTAS)[0]
        chamado.avaliacao = nota
        chamado.save()
        classificacao = Chamado.CLASSIFICACAO_AVALIACAO[nota][0]
        chamado.registrar_evento(EventoChamado.Tipo.AVALIADO, chamado.solicitante,
                                 f'Avaliou o atendimento: {nota} de 5 estrelas ({classificacao}).')
        self._registrar(chamado, f'avaliado com {nota}')

    def reabrir(self, chamado):
        ProcedimentoEntry.objects.create(chamado=chamado, autor=chamado.solicitante, tipo=ProcedimentoEntry.Tipo.RESPOSTA,
                                         texto=f'Não foi resolvido: {self.rng.choice(MOTIVOS_REABERTURA)}')
        chamado.reabrir()
        chamado.save()
        chamado.registrar_evento(EventoChamado.Tipo.REABERTO, chamado.solicitante,
                                 f'Informou que não foi resolvido; chamado reaberto (reabertura nº {chamado.reaberturas}).')
        self._registrar(chamado, 'reaberto')

    def _registrar(self, chamado, acao):
        self.acoes.append(f'{chamado.codigo}: {acao}')


# ---- cenários de validação (comando simular_cenario) ----

class _Desfazer(Exception):
    """Interrompe a transação do cenário para que nada fique gravado."""


def rodar_cenario(total_chamados=100, semente=1, intervalo=timedelta(minutes=10), max_passos=5000):
    """Simula `total_chamados` chamados do início ao fim com um relógio simulado (cada passo avança
    `intervalo`) e devolve os indicadores do painel calculados sobre eles.

    Roda numa transação desfeita no final: apaga os chamados existentes (só dentro da transação,
    para os indicadores verem apenas o cenário) e nada do que acontece fica gravado. Os números de
    código INC/REQ consumidos não voltam (sequences do PostgreSQL não são transacionais).
    """
    from unittest import mock

    from indicadores.metricas import Filtros, visao_executiva

    relogio = [timezone.now()]
    inicio = relogio[0]
    resultado = {}
    try:
        with mock.patch('django.utils.timezone.now', lambda: relogio[0]), transaction.atomic():
            Chamado.objects.all().delete()
            simulador = Simulador(random.Random(semente))
            passos = criados = 0
            while passos < max_passos:
                relogio[0] += intervalo
                passos += 1
                simulador.passo(novos=1 if criados < total_chamados else 0)
                criados = Chamado.objects.count()
                terminou = (
                    criados >= total_chamados
                    and not Chamado.objects.exclude(status=Chamado.Status.FECHADO).exists()
                    and not simulador.candidatos().exists()
                )
                if terminou:
                    break
            filtros = Filtros(periodo='personalizado', inicio=inicio, fim=relogio[0] + timedelta(minutes=1))
            resultado = visao_executiva(filtros)
            resultado['passos'] = passos
            resultado['tempo_simulado'] = relogio[0] - inicio
            resultado['em_aberto_no_fim'] = Chamado.objects.exclude(status=Chamado.Status.FECHADO).count()
            raise _Desfazer
    except _Desfazer:
        pass
    return resultado
