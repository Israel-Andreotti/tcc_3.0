"""Comparação de disciplinas de fila: a fila do sistema (urgência do SLA) × FIFO (ordem de chegada).

Modelo (simulação de eventos discretos, com os models reais e relógio simulado):
- Chegam N chamados em intervalos aleatórios (exponenciais), escolhendo serviço do catálogo e
  solicitante fictício (alguns em setores críticos). Prioridade e prazo de SLA são definidos pelo
  próprio Chamado.save(), como no sistema.
- Há T técnicos; cada um atende um chamado por vez, por um tempo aleatório (uniforme entre 20 e
  100 minutos, média de 60).
- Quando um técnico fica livre, pega o próximo chamado da fila segundo a política:
  - "sistema": a mesma ordenação da fila do sistema (ORDEM_URGENCIA: prazo de SLA mais próximo);
  - "fifo": o chamado mais antigo, sem olhar prioridade.
- As duas políticas recebem exatamente os mesmos chamados (mesmas chegadas, serviços e durações),
  então qualquer diferença vem só da ordem de atendimento.
- A carga é a utilização esperada da equipe: chegadas por hora × duração média ÷ técnicos. Acima de
  100%, chega mais trabalho do que a equipe dá conta e a fila cresce (um pico, como uma queda de rede).
- Opcionalmente, um expediente (ex.: 8h–17h, segunda a sexta): os técnicos só pegam chamados nesse
  horário (quem está atendendo às 17h termina o que começou), mas os chamados chegam a qualquer hora
  (o hospital funciona 24 h) e o SLA corre 24 h, como no sistema. A carga passa a ser calculada sobre
  as horas em que a equipe trabalha, e a simulação começa numa segunda-feira à 0h.

Roda numa transação desfeita no final: nada fica gravado.
"""

import heapq
import random
import statistics
from dataclasses import dataclass
from datetime import timedelta
from unittest import mock

from django.db import transaction
from django.db.models import Case, IntegerField, When
from django.utils import timezone

from .demo import Simulador, _Desfazer
from .models import NIVEIS_PRIORIDADE, Chamado, Subcategoria

POLITICAS = {
    'fifo': 'FIFO (ordem de chegada)',
    'sistema': 'Sistema (urgência do SLA)',
}
DURACAO_MINIMA, DURACAO_MAXIMA = 20, 100  # minutos de atendimento
DURACAO_MEDIA = (DURACAO_MINIMA + DURACAO_MAXIMA) / 2


@dataclass
class Expediente:
    inicio: int = 8  # hora de início
    fim: int = 17  # hora de fim (exclusiva)
    dias_uteis: bool = True  # segunda a sexta; False = todos os dias

    def trabalhando(self, momento):
        local = timezone.localtime(momento)
        return (not self.dias_uteis or local.weekday() < 5) and self.inicio <= local.hour < self.fim

    def proximo_inicio(self, momento):
        """Primeiro instante de expediente a partir de `momento`."""
        if self.trabalhando(momento):
            return momento
        local = timezone.localtime(momento)
        dia = local.replace(hour=self.inicio, minute=0, second=0, microsecond=0)
        if local.hour >= self.inicio:
            dia += timedelta(days=1)
        while self.dias_uteis and dia.weekday() >= 5:
            dia += timedelta(days=1)
        return dia

    @property
    def fracao_do_tempo(self):
        """Fração das horas da semana em que a equipe trabalha (para calcular a carga)."""
        return (self.fim - self.inicio) / 24 * (5 / 7 if self.dias_uteis else 1)

    def __str__(self):
        return f"{self.inicio}h–{self.fim}h, {'segunda a sexta' if self.dias_uteis else 'todos os dias'}"


@dataclass
class Chegada:
    minuto: float  # minutos desde o início da simulação
    subcategoria: Subcategoria
    solicitante: object
    duracao: float  # minutos de atendimento


def gerar_chegadas(total, semente, tecnicos, carga, solicitantes, expediente=None):
    rng = random.Random(semente)
    subcategorias = list(Subcategoria.objects.select_related('categoria').order_by('pk'))
    capacidade = tecnicos * (expediente.fracao_do_tempo if expediente else 1)  # técnicos-hora por hora
    intervalo_medio = DURACAO_MEDIA / (capacidade * carga)
    minuto, chegadas = 0.0, []
    for _ in range(total):
        minuto += rng.expovariate(1 / intervalo_medio)
        chegadas.append(Chegada(minuto, rng.choice(subcategorias), rng.choice(solicitantes),
                                rng.uniform(DURACAO_MINIMA, DURACAO_MAXIMA)))
    return chegadas


def proximo_da_fila(politica):
    fila = Chamado.objects.filter(status=Chamado.Status.ABERTO, atendente__isnull=True)
    if politica == 'fifo':
        return fila.order_by('criado_em', 'pk').first()
    from .views import ORDEM_URGENCIA  # a mesma ordenação da tela da fila

    return fila.annotate(
        sla_pausado_ordem=Case(When(sla_pausado_em__isnull=False, then=1), default=0, output_field=IntegerField()),
    ).order_by(*ORDEM_URGENCIA).first()


def executar(politica, chegadas, tecnicos, relogio, base, expediente=None):
    """Atende as chegadas com a política dada e devolve as métricas dos chamados."""
    livres = list(tecnicos)
    em_atendimento = []  # heap: (fim, ordem, chamado_pk, técnico)
    duracoes = {}
    seguinte = 0
    contador = 0

    def despachar():
        nonlocal contador
        if expediente and not expediente.trabalhando(relogio[0]):
            return
        while livres:
            chamado = proximo_da_fila(politica)
            if chamado is None:
                return
            tecnico = livres.pop(0)
            chamado.atribuir(tecnico)
            chamado.registrar_primeira_resposta()
            chamado.save()
            contador += 1
            heapq.heappush(em_atendimento, (relogio[0] + duracoes[chamado.pk], contador, chamado.pk, tecnico))

    def fila_esperando():
        return Chamado.objects.filter(status=Chamado.Status.ABERTO, atendente__isnull=True).exists()

    while True:
        proxima_chegada = (base + timedelta(minutes=chegadas[seguinte].minuto)) if seguinte < len(chegadas) else None
        proximo_fim = em_atendimento[0][0] if em_atendimento else None
        # Fora do expediente, com chamados esperando e técnico livre: o próximo evento pode ser a
        # abertura do expediente seguinte.
        proximo_turno = None
        if expediente and livres and not expediente.trabalhando(relogio[0]) and fila_esperando():
            proximo_turno = expediente.proximo_inicio(relogio[0])
        eventos = [t for t in (proxima_chegada, proximo_fim, proximo_turno) if t is not None]
        if not eventos:
            break
        momento = min(eventos)
        if momento == proximo_turno and momento not in (proxima_chegada, proximo_fim):
            relogio[0] = momento
        elif proximo_fim is not None and momento == proximo_fim:
            fim, _, pk, tecnico = heapq.heappop(em_atendimento)
            relogio[0] = fim
            chamado = Chamado.objects.get(pk=pk)
            chamado.fechar()
            chamado.save()
            livres.append(tecnico)
        else:
            relogio[0] = proxima_chegada
            chegada = chegadas[seguinte]
            chamado = Chamado.objects.create(
                titulo=chegada.subcategoria.nome, descricao='Chamado simulado.', solicitante=chegada.solicitante,
                setor=chegada.solicitante.setor, categoria=chegada.subcategoria.categoria,
                subcategoria=chegada.subcategoria,
            )
            duracoes[chamado.pk] = timedelta(minutes=chegada.duracao)
            seguinte += 1
        despachar()
    return metricas(Chamado.objects.all(), expediente)


def metricas(chamados, expediente=None):
    """Nível de serviço, espera até o atendimento e resolução — no total e por prioridade."""
    def resumo(lista):
        if not lista:
            return None
        esperas = [(c.atribuido_em - c.criado_em).total_seconds() / 3600 for c in lista]
        resolucoes = [(c.fechado_em - c.criado_em).total_seconds() / 3600 for c in lista]
        return {
            'total': len(lista),
            'nivel_servico': 100 * sum(c.fechado_no_prazo for c in lista) / len(lista),
            'espera_media': statistics.mean(esperas),
            'espera_maxima': max(esperas),
            'resolucao_media': statistics.mean(resolucoes),
        }

    lista = list(chamados)
    resultado = {'geral': resumo(lista)}
    for prioridade in NIVEIS_PRIORIDADE:
        resultado[prioridade] = resumo([c for c in lista if c.prioridade == prioridade])
    if expediente:
        criticos = [c for c in lista if c.prioridade == 'critica']
        resultado['critica_no_expediente'] = resumo([c for c in criticos if expediente.trabalhando(c.criado_em)])
        resultado['critica_fora_expediente'] = resumo([c for c in criticos if not expediente.trabalhando(c.criado_em)])
    return resultado


def comparar(total_chamados=100, semente=1, tecnicos=3, carga=1.0, expediente=None):
    """Roda as duas políticas sobre os mesmos chamados e devolve {política: métricas}."""
    base = timezone.now()
    if expediente:  # começa numa segunda-feira à 0h, para a semana simulada ser sempre a mesma
        local = timezone.localtime(base)
        base = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        base += timedelta(days=7)
    relogio = [base]
    resultado = {}
    try:
        with mock.patch('django.utils.timezone.now', lambda: relogio[0]), transaction.atomic():
            Chamado.objects.all().delete()
            simulador = Simulador()
            simulador.preparar_usuarios()
            equipe = simulador.tecnicos[:tecnicos]
            chegadas = gerar_chegadas(total_chamados, semente, len(equipe), carga, simulador.solicitantes, expediente)
            for politica in POLITICAS:
                relogio[0] = base
                try:
                    with transaction.atomic():
                        resultado[politica] = executar(politica, chegadas, equipe, relogio, base, expediente)
                        raise _Desfazer
                except _Desfazer:
                    pass
            raise _Desfazer
    except _Desfazer:
        pass
    return resultado
