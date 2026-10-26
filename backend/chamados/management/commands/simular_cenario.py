"""Cenários de validação: simula N chamados do início ao fim (relógio simulado) e compara os
indicadores entre repetições com sementes diferentes. Nada fica gravado no banco.

Exemplo: python manage.py simular_cenario --chamados 100 --repeticoes 3 --csv simulacoes.csv
"""

import csv
import statistics
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chamados import demo
from chamados.demo import rodar_cenario

# chave do resultado, rótulo, unidade ('n' quantidade, '%' percentual, 'h' horas, 'nota' 1 a 5)
INDICADORES = [
    ('total_chamados', 'Chamados abertos', 'n'),
    ('total_fechados', 'Chamados fechados', 'n'),
    ('nivel_servico', 'Nível de serviço (fechados no prazo)', '%'),
    ('nivel_servico_incidente', '  incidentes', '%'),
    ('nivel_servico_requisicao', '  requisições', '%'),
    ('ftr', 'Tempo até a 1ª resposta (FTR)', 'h'),
    ('tempo_atendimento', 'Tempo médio de atendimento', 'h'),
    ('tempo_resolucao', 'Tempo médio de resolução', 'h'),
    ('primeiro_contato', 'Resolução no 1º contato (FCR)', '%'),
    ('reabertura', 'Taxa de reabertura', '%'),
    ('csat_base', 'Avaliações recebidas', 'n'),
    ('csat', 'Satisfação (CSAT)', '%'),
    ('csat_media', 'Nota média', 'nota'),
    ('tempo_simulado', 'Tempo simulado', 'h'),
]


def _numero(valor):
    """Indicador como número (horas para durações); None quando não há base de cálculo."""
    if isinstance(valor, timedelta):
        return valor.total_seconds() / 3600
    return float(valor) if valor is not None else None


def _texto(valor, unidade):
    if valor is None:
        return '—'
    if unidade == 'n':
        return f'{valor:.0f}' if float(valor).is_integer() else f'{valor:.1f}'
    if unidade == '%':
        return f'{valor:.1f}%'
    if unidade == 'h':
        return f'{valor:.1f} h'
    return f'{valor:.2f}'


class Command(BaseCommand):
    help = 'Simula cenários completos de chamados e compara os indicadores entre repetições (nada é gravado).'

    def add_arguments(self, parser):
        parser.add_argument('--chamados', type=int, default=100, help='Chamados por simulação (padrão: 100).')
        parser.add_argument('--repeticoes', type=int, default=3, help='Quantas simulações (padrão: 3).')
        parser.add_argument('--semente', type=int, default=1, help='Semente da 1ª simulação; as demais usam as seguintes.')
        parser.add_argument('--intervalo', type=int, default=10, help='Minutos simulados por passo (padrão: 10).')
        parser.add_argument('--csv', dest='arquivo_csv', help='Também salva a tabela neste arquivo CSV (separador ;).')
        parser.add_argument('--forcar', action='store_true', help='Roda mesmo com DEBUG=False.')

    def handle(self, *args, chamados, repeticoes, semente, intervalo, arquivo_csv, forcar, **options):
        if not (settings.DEBUG or forcar):
            raise CommandError('Os cenários rodam no ambiente local (DEBUG=True) ou com --forcar.')

        self.stdout.write(
            f'Parâmetros do simulador: abertura {demo.CHANCE_ABRIR:.0%} por passo de {intervalo} min; '
            f'{demo.FRACAO_DEMORADOS:.0%} dos chamados demorados; {demo.FRACAO_REABERTOS:.0%} reabertos; '
            f'{demo.FRACAO_SEM_AVALIACAO:.0%} sem avaliação; '
            f'pesos das notas 5..1 = {demo.PESOS_NOTAS}.\n'
        )
        colunas = []
        for i in range(repeticoes):
            self.stdout.write(f'Simulação {i + 1} (semente {semente + i})...')
            resultado = rodar_cenario(chamados, semente + i, timedelta(minutes=intervalo))
            for tipo in resultado['por_tipo']:
                resultado[f"nivel_servico_{tipo['tipo']}"] = tipo['nivel_servico']
            colunas.append({chave: _numero(resultado.get(chave)) for chave, _, _ in INDICADORES})

        cabecalho = ['Indicador'] + [f'Sim. {i + 1}' for i in range(repeticoes)] + ['Média', 'Desvio padrão']
        linhas = []
        for chave, rotulo, unidade in INDICADORES:
            valores = [coluna[chave] for coluna in colunas]
            validos = [v for v in valores if v is not None]
            media = statistics.mean(validos) if validos else None
            desvio = statistics.stdev(validos) if len(validos) > 1 else None
            linhas.append((rotulo, unidade, valores + [media, desvio]))

        largura = max(len(rotulo) for rotulo, _, _ in linhas) + 2
        self.stdout.write('\n' + cabecalho[0].ljust(largura) + ''.join(c.rjust(15) for c in cabecalho[1:]))
        for rotulo, unidade, valores in linhas:
            self.stdout.write(rotulo.ljust(largura) + ''.join(_texto(v, unidade).rjust(15) for v in valores))

        if arquivo_csv:
            with open(arquivo_csv, 'w', newline='', encoding='utf-8-sig') as arquivo:
                escritor = csv.writer(arquivo, delimiter=';')
                escritor.writerow(cabecalho)
                for rotulo, unidade, valores in linhas:
                    escritor.writerow([rotulo.strip()] + [_texto(v, unidade).replace('.', ',') for v in valores])
            self.stdout.write(self.style.SUCCESS(f'\nTabela salva em {arquivo_csv}'))
