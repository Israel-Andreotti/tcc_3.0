"""Cálculo dos indicadores de gestão do service desk.

Duas visões:
- Executiva (período): volume, níveis de serviço e qualidade do atendimento.
  Indicadores de volume usam a data de ABERTURA; os de resolução usam a data de FECHAMENTO.
- Operacional (agora): fila atual, chamados sem técnico e carga/travamentos por técnico.

Definições:
- FTR (primeira resposta): abertura -> primeiro registro público da equipe (ou o fechamento).
- Tempo de atendimento: primeira atribuição -> fechamento.
- Tempo de resolução: abertura -> fechamento.
- Resolução no primeiro contato: fechado sem reabertura e sem pedir informação ao solicitante.
- Taxa de reabertura: fechados que já foram reabertos ao menos uma vez / fechados.
- Nível de serviço: fechados dentro do prazo de SLA / fechados com prazo medido.
- CSAT: avaliações 4 ou 5 / avaliações (nota de 1 a 5 dada pelo solicitante após o fechamento).
  Classificação das notas (Chamado.CLASSIFICACAO_AVALIACAO): 5 muito satisfeito, 4 satisfeito,
  3 neutro, 2 insatisfeito, 1 muito insatisfeito; grupos: satisfeitos (4-5), neutros (3),
  insatisfeitos (1-2).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from chamados.models import Chamado, NIVEIS_PRIORIDADE, Prioridade, TipoChamado

PERIODOS = {'7': 7, '30': 30, '90': 90, '365': 365}
PERIODO_PADRAO = '30'
HORAS_PARADO = 24  # chamado em andamento sem nenhuma atualização há mais que isso = travado


@dataclass
class Filtros:
    periodo: str
    inicio: datetime
    fim: datetime
    tecnico_id: int | None = None
    setor_id: int | None = None
    categoria_id: int | None = None
    tipo: str | None = None

    @property
    def dias(self):
        return max(1, (self.fim - self.inicio).days)

    @classmethod
    def do_request(cls, get):
        """Lê os filtros da querystring; valores inválidos voltam ao padrão."""
        agora = timezone.localtime()
        periodo = get.get('periodo', PERIODO_PADRAO)
        inicio = fim = None
        if periodo == 'personalizado':
            inicio, fim = _data(get.get('de')), _data(get.get('ate'))
            if not inicio or not fim or inicio > fim:
                periodo, inicio, fim = PERIODO_PADRAO, None, None
        if periodo != 'personalizado':
            periodo = periodo if periodo in PERIODOS else PERIODO_PADRAO
            fim = agora.date()
            inicio = fim - timedelta(days=PERIODOS[periodo] - 1)
        tz = timezone.get_current_timezone()
        return cls(
            periodo=periodo,
            inicio=datetime.combine(inicio, time.min, tzinfo=tz),
            fim=datetime.combine(fim, time.max, tzinfo=tz),
            tecnico_id=_inteiro(get.get('tecnico')),
            setor_id=_inteiro(get.get('setor')),
            categoria_id=_inteiro(get.get('categoria')),
            tipo=get.get('tipo') if get.get('tipo') in TipoChamado.values else None,
        )


def _data(valor):
    try:
        return date.fromisoformat(valor or '')
    except ValueError:
        return None


def _inteiro(valor):
    return int(valor) if valor and str(valor).isdigit() else None


def _filtrar(qs, f, campo_periodo=None):
    """Aplica técnico/setor/categoria e, se informado, o período sobre `campo_periodo`."""
    if f.tecnico_id:
        qs = qs.filter(atendente_id=f.tecnico_id)
    if f.setor_id:
        qs = qs.filter(setor_id=f.setor_id)
    if f.categoria_id:
        qs = qs.filter(categoria_id=f.categoria_id)
    if f.tipo:
        qs = qs.filter(tipo=f.tipo)
    if campo_periodo:
        qs = qs.filter(**{f'{campo_periodo}__range': (f.inicio, f.fim)})
    return qs


def _duracao_media(qs, de, ate):
    return qs.aggregate(
        media=Avg(ExpressionWrapper(F(ate) - F(de), output_field=DurationField()))
    )['media']


def _percentual(parte, total):
    return round(parte * 100 / total, 1) if total else None


# --------------------------------------------------------------------------- visão executiva

def visao_executiva(f):
    abertos = _filtrar(Chamado.objects.all(), f, 'criado_em')
    fechados = _filtrar(Chamado.objects.filter(fechado_em__isnull=False), f, 'fechado_em')
    total_fechados = fechados.count()

    medidos_sla = fechados.filter(fechado_no_prazo__isnull=False)
    total_medidos = medidos_sla.count()
    avaliados = fechados.filter(avaliacao__isnull=False)
    total_avaliados = avaliados.count()

    return {
        'total_chamados': abertos.count(),
        'total_fechados': total_fechados,
        'ftr': _duracao_media(abertos.filter(primeira_resposta_em__isnull=False), 'criado_em', 'primeira_resposta_em'),
        'tempo_atendimento': _duracao_media(
            fechados.filter(atribuido_em__isnull=False), 'atribuido_em', 'fechado_em'
        ),
        'tempo_resolucao': _duracao_media(fechados, 'criado_em', 'fechado_em'),
        'primeiro_contato': _percentual(fechados.filter(reaberturas=0, pediu_info=False).count(), total_fechados),
        'reabertura': _percentual(fechados.filter(reaberturas__gt=0).count(), total_fechados),
        'nivel_servico': _percentual(medidos_sla.filter(fechado_no_prazo=True).count(), total_medidos),
        'nivel_servico_base': total_medidos,
        'csat': _percentual(avaliados.filter(avaliacao__gte=4).count(), total_avaliados),
        'csat_media': avaliados.aggregate(media=Avg('avaliacao'))['media'],
        'csat_base': total_avaliados,
        **_satisfacao(avaliados, total_avaliados),
        'volume': _volume(f),
        'por_categoria': list(
            abertos.values(nome=F('categoria__nome')).annotate(total=Count('pk')).order_by('-total', 'nome')
        ),
        'por_setor': list(
            abertos.values(nome=F('setor__nome'), critico=F('setor__critico'))
            .annotate(total=Count('pk')).order_by('-total', 'nome')
        ),
        'por_prioridade': _por_prioridade(abertos),
        'por_tecnico': _por_tecnico(fechados),
        'por_tipo': _por_tipo(abertos, fechados),
    }


def _por_tipo(abertos, fechados):
    """Incidentes x requisições: volume, nível de serviço e tempo médio de resolução."""
    resultado = []
    for valor, rotulo in TipoChamado.choices:
        fechados_tipo = fechados.filter(tipo=valor)
        medidos = fechados_tipo.filter(fechado_no_prazo__isnull=False)
        total_medidos = medidos.count()
        resultado.append({
            'tipo': valor,
            'rotulo': rotulo,
            'abertos': abertos.filter(tipo=valor).count(),
            'fechados': fechados_tipo.count(),
            'nivel_servico': _percentual(medidos.filter(fechado_no_prazo=True).count(), total_medidos),
            'tempo_resolucao': _duracao_media(fechados_tipo, 'criado_em', 'fechado_em'),
        })
    return resultado


def _satisfacao(avaliados, total):
    """Distribuição das avaliações por nota (5 -> 1) e pelos três grupos."""
    contagem = dict(avaliados.values_list('avaliacao').annotate(n=Count('pk')))
    por_nota, grupos = [], {'satisfeitos': 0, 'neutros': 0, 'insatisfeitos': 0}
    for nota in sorted(Chamado.CLASSIFICACAO_AVALIACAO, reverse=True):
        rotulo, grupo = Chamado.CLASSIFICACAO_AVALIACAO[nota]
        quantidade = contagem.get(nota, 0)
        grupos[grupo] += quantidade
        por_nota.append({'nota': nota, 'rotulo': rotulo, 'total': quantidade, 'percentual': _percentual(quantidade, total)})
    return {
        'avaliacoes_por_nota': por_nota,
        'satisfacao_grupos': [
            {'grupo': 'Satisfeitos', 'notas': '4 e 5', 'total': grupos['satisfeitos'],
             'percentual': _percentual(grupos['satisfeitos'], total)},
            {'grupo': 'Neutros', 'notas': '3', 'total': grupos['neutros'],
             'percentual': _percentual(grupos['neutros'], total)},
            {'grupo': 'Insatisfeitos', 'notas': '1 e 2', 'total': grupos['insatisfeitos'],
             'percentual': _percentual(grupos['insatisfeitos'], total)},
        ],
    }


def _volume(f):
    """Chamados abertos x fechados por dia (períodos até ~2 meses) ou por mês."""
    por_mes = f.dias > 62
    trunc = TruncMonth if por_mes else TruncDate
    tz = timezone.get_current_timezone()

    def contar(campo, base):
        return dict(
            _filtrar(base, f, campo)
            .annotate(bucket=trunc(campo, tzinfo=tz)).values('bucket')
            .annotate(total=Count('pk')).values_list('bucket', 'total')
        )

    abertos = contar('criado_em', Chamado.objects.all())
    fechados = contar('fechado_em', Chamado.objects.filter(fechado_em__isnull=False))

    rotulos, serie_abertos, serie_fechados = [], [], []
    dia = f.inicio.date()
    ultimo = f.fim.date()
    while dia <= ultimo:
        chave = dia.replace(day=1) if por_mes else dia
        rotulos.append(chave.strftime('%m/%Y') if por_mes else chave.strftime('%d/%m'))
        # TruncMonth devolve datetime/date conforme o banco: normaliza para date.
        serie_abertos.append(_valor_bucket(abertos, chave))
        serie_fechados.append(_valor_bucket(fechados, chave))
        if por_mes:
            dia = (chave.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            dia += timedelta(days=1)
    return {
        'rotulos': rotulos, 'abertos': serie_abertos, 'fechados': serie_fechados, 'por_mes': por_mes,
        'linhas': list(zip(rotulos, serie_abertos, serie_fechados)),  # tabela acessível do gráfico
    }


def _valor_bucket(contagens, chave):
    for bucket, total in contagens.items():
        bucket_data = bucket.date() if isinstance(bucket, datetime) else bucket
        if bucket_data == chave:
            return total
    return 0


def _por_prioridade(abertos):
    contagem = dict(abertos.values_list('prioridade').annotate(total=Count('pk')))
    rotulos = dict(Prioridade.choices)
    # Da mais urgente para a menos urgente.
    return [
        {'prioridade': p, 'nome': rotulos[p], 'total': contagem.get(p, 0)}
        for p in reversed(NIVEIS_PRIORIDADE)
    ]


def _por_tecnico(fechados):
    duracao = ExpressionWrapper(F('fechado_em') - F('criado_em'), output_field=DurationField())
    linhas = (
        fechados.filter(atendente__isnull=False)
        .values('atendente', 'atendente__first_name', 'atendente__last_name', 'atendente__username')
        .annotate(
            fechados=Count('pk'),
            reabertos=Count('pk', filter=Q(reaberturas__gt=0)),
            no_prazo=Count('pk', filter=Q(fechado_no_prazo=True)),
            medidos=Count('pk', filter=Q(fechado_no_prazo__isnull=False)),
            tempo_medio=Avg(duracao),
            csat_media=Avg('avaliacao'),
        )
        .order_by('-fechados')
    )
    resultado = []
    for linha in linhas:
        nome = f"{linha['atendente__first_name']} {linha['atendente__last_name']}".strip()
        resultado.append({
            'nome': nome or linha['atendente__username'],
            'fechados': linha['fechados'],
            'reabertura': _percentual(linha['reabertos'], linha['fechados']),
            'nivel_servico': _percentual(linha['no_prazo'], linha['medidos']),
            'tempo_medio': linha['tempo_medio'],
            'csat_media': linha['csat_media'],
        })
    return resultado


# --------------------------------------------------------------------------- visão operacional

def visao_operacional(f):
    """Situação atual da fila (o período não se aplica; técnico/setor/categoria sim)."""
    agora = timezone.now()
    em_aberto = _filtrar(Chamado.objects.exclude(status=Chamado.Status.FECHADO), f).select_related(
        'solicitante', 'setor', 'atendente', 'categoria'
    )
    estourado = Q(sla_pausado_em__isnull=True, prazo_sla__lt=agora)
    parado = Q(status=Chamado.Status.EM_ANDAMENTO, atualizado_em__lt=agora - timedelta(hours=HORAS_PARADO))

    carga = (
        em_aberto.filter(atendente__isnull=False)
        .values('atendente', 'atendente__first_name', 'atendente__last_name', 'atendente__username')
        .annotate(
            total=Count('pk'),
            em_andamento=Count('pk', filter=Q(status=Chamado.Status.EM_ANDAMENTO)),
            aguardando=Count('pk', filter=Q(status=Chamado.Status.AGUARDANDO_SOLICITANTE)),
            estourados=Count('pk', filter=estourado),
            parados=Count('pk', filter=parado),
        )
        .order_by('-estourados', '-parados', '-total')
    )
    por_tecnico = []
    for linha in carga:
        nome = f"{linha['atendente__first_name']} {linha['atendente__last_name']}".strip()
        por_tecnico.append({**linha, 'nome': nome or linha['atendente__username']})

    return {
        'em_aberto': em_aberto.count(),
        'sem_atribuicao': em_aberto.filter(atendente__isnull=True).count(),
        'estourados': em_aberto.filter(estourado).count(),
        'aguardando_solicitante': em_aberto.filter(status=Chamado.Status.AGUARDANDO_SOLICITANTE).count(),
        'fila_sem_atribuicao': list(
            em_aberto.filter(atendente__isnull=True).order_by(F('prazo_sla').asc(nulls_last=True))[:15]
        ),
        'por_tecnico': por_tecnico,
        'travados': list(
            em_aberto.filter(atendente__isnull=False).filter(estourado | parado)
            .order_by(F('prazo_sla').asc(nulls_last=True))[:20]
        ),
        'horas_parado': HORAS_PARADO,
    }
