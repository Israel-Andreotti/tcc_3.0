"""Um passo da simulação de uso para a demonstração (ver chamados/demo.py).

Em produção roda como cron no Railway (a cada 10 minutos), num serviço com DEMO=True.
Localmente: python manage.py simular_demo --forcar
"""

import random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chamados.demo import Simulador


class Command(BaseCommand):
    help = 'Executa um passo da simulação de demonstração: abre chamados fictícios e avança os existentes.'

    def add_arguments(self, parser):
        parser.add_argument('--novos', type=int, default=1, help='Tentativas de abrir chamado neste passo, cada uma com 60%% de chance (padrão: 1).')
        parser.add_argument('--passos', type=int, default=1, help='Quantos passos executar em sequência (padrão: 1).')
        parser.add_argument('--semente', type=int, help='Semente do sorteio, para repetir uma simulação.')
        parser.add_argument('--forcar', action='store_true', help='Roda mesmo sem DEMO=True (uso local).')

    def handle(self, *args, novos, passos, semente, forcar, **options):
        if not (settings.DEMO or forcar):
            raise CommandError('Simulação desligada: defina DEMO=True no ambiente (ou use --forcar localmente).')
        simulador = Simulador(random.Random(semente))
        for _ in range(passos):
            simulador.passo(novos=novos)
        for acao in simulador.acoes:
            self.stdout.write(acao)
        self.stdout.write(self.style.SUCCESS(f'{len(simulador.acoes)} ações simuladas.'))
