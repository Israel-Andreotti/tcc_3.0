"""Compara a fila do sistema (urgência do SLA) com FIFO sobre os mesmos chamados, em várias cargas
de trabalho (ver chamados/comparacao.py). Nada fica gravado no banco.

Exemplos:
    python manage.py comparar_filas --chamados 100 --repeticoes 3 --cargas 0.8,1.0,1.2 --csv filas.csv
    python manage.py comparar_filas --tecnicos 5 --expediente 8-17      # horário comercial, seg. a sex.
"""

import csv
import statistics

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chamados.comparacao import POLITICAS, Expediente, comparar

PRIORIDADES = [('geral', 'Geral'), ('critica', 'Crítica'), ('alta', 'Alta'), ('media', 'Média'), ('baixa', 'Baixa')]
PRIORIDADES_EXPEDIENTE = [('critica_no_expediente', 'Crítica aberta no expediente'),
                          ('critica_fora_expediente', 'Crítica aberta fora do expediente')]
# métrica, rótulo, unidade
METRICAS = [
    ('nivel_servico', 'Nível de serviço', '%'),
    ('espera_media', 'Espera média até o atendimento', 'h'),
    ('espera_maxima', 'Maior espera', 'h'),
]
COM_MAIOR_ESPERA = ('geral', 'critica', 'baixa', 'critica_no_expediente', 'critica_fora_expediente')


def _texto(valor, unidade):
    if valor is None:
        return '—'
    return f'{valor:.1f}%' if unidade == '%' else f'{valor:.1f} h'


class Command(BaseCommand):
    help = 'Compara a fila do sistema com FIFO (mesmos chamados, várias cargas). Nada é gravado.'

    def add_arguments(self, parser):
        parser.add_argument('--chamados', type=int, default=100, help='Chamados por simulação (padrão: 100).')
        parser.add_argument('--repeticoes', type=int, default=3, help='Simulações por carga (padrão: 3).')
        parser.add_argument('--semente', type=int, default=1, help='Semente da 1ª simulação; as demais usam as seguintes.')
        parser.add_argument('--tecnicos', type=int, default=3, help='Técnicos na equipe (padrão: 3, máximo 5).')
        parser.add_argument('--expediente', help='Horário da equipe, ex.: 8-17 (padrão: 24 h).')
        parser.add_argument('--todos-os-dias', action='store_true', help='Expediente também no fim de semana.')
        parser.add_argument('--cargas', default='0.8,1.0,1.2',
                            help='Utilizações da equipe a comparar, separadas por vírgula (padrão: 0.8,1.0,1.2).')
        parser.add_argument('--csv', dest='arquivo_csv', help='Também salva os resultados neste CSV (separador ;).')
        parser.add_argument('--forcar', action='store_true', help='Roda mesmo com DEBUG=False.')

    def handle(self, *args, chamados, repeticoes, semente, tecnicos, expediente, todos_os_dias, cargas,
               arquivo_csv, forcar, **options):
        if not (settings.DEBUG or forcar):
            raise CommandError('A comparação roda no ambiente local (DEBUG=True) ou com --forcar.')
        try:
            cargas = [float(c) for c in cargas.split(',')]
        except ValueError:
            raise CommandError('--cargas deve ser uma lista de números, ex.: 0.8,1.0,1.2')
        if expediente:
            try:
                inicio, fim = (int(h) for h in expediente.split('-'))
            except ValueError:
                raise CommandError('--expediente deve ser no formato 8-17')
            expediente = Expediente(inicio, fim, dias_uteis=not todos_os_dias)
        prioridades = PRIORIDADES + (PRIORIDADES_EXPEDIENTE if expediente else [])

        self.stdout.write(
            f'{chamados} chamados por simulação, {repeticoes} repetições por carga, {tecnicos} técnicos, '
            'atendimento de 20 a 100 min (média 60). Mesmos chamados para as duas políticas.'
        )
        if expediente:
            self.stdout.write(f'Expediente da equipe: {expediente}; os chamados chegam 24 h e o SLA corre 24 h.')
        self.stdout.write('Carga = utilização esperada da equipe nas horas de trabalho (acima de 100% a fila cresce).')

        largura = 62 if expediente else 44
        linhas_csv = []
        for carga in cargas:
            rodadas = [comparar(chamados, semente + i, tecnicos, carga, expediente) for i in range(repeticoes)]

            self.stdout.write(self.style.MIGRATE_HEADING(f'\nCarga {carga:.0%}'))
            self.stdout.write(f"{'':{largura}}{'FIFO':>12}{'Sistema':>12}")
            for metrica, rotulo_metrica, unidade in METRICAS:
                for prioridade, rotulo_prioridade in prioridades:
                    if metrica == 'espera_maxima' and prioridade not in COM_MAIOR_ESPERA:
                        continue
                    medias = []
                    for politica in POLITICAS:
                        valores = [r[politica][prioridade][metrica] for r in rodadas if r[politica].get(prioridade)]
                        medias.append(statistics.mean(valores) if valores else None)
                    rotulo = f'{rotulo_metrica} — {rotulo_prioridade.lower()}'
                    self.stdout.write(f'{rotulo:{largura}}' + ''.join(f'{_texto(m, unidade):>12}' for m in medias))
                    linhas_csv.append([f'{carga:.0%}', rotulo_metrica, rotulo_prioridade]
                                      + [_texto(m, unidade).replace('.', ',') for m in medias])

        if arquivo_csv:
            with open(arquivo_csv, 'w', newline='', encoding='utf-8-sig') as arquivo:
                escritor = csv.writer(arquivo, delimiter=';')
                escritor.writerow(['Carga', 'Indicador', 'Prioridade'] + list(POLITICAS.values()))
                escritor.writerows(linhas_csv)
            self.stdout.write(self.style.SUCCESS(f'\nResultados salvos em {arquivo_csv}'))
