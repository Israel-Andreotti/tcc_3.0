from django import template

register = template.Library()

STATUS_CLASSES = {
    'aberto': 'status-aberto',
    'em_andamento': 'status-andamento',
    'aguardando_solicitante': 'status-aguardando',
    'resolvido': 'status-resolvido',
    'fechado': 'status-fechado',
}

PRIORIDADE_CLASSES = {
    'baixa': 'prioridade-baixa',
    'media': 'prioridade-media',
    'alta': 'prioridade-alta',
    'critica': 'prioridade-critica',
}


@register.filter
def status_badge(status):
    return STATUS_CLASSES.get(status, 'status-aberto')


@register.filter
def prioridade_badge(prioridade):
    return PRIORIDADE_CLASSES.get(prioridade, 'prioridade-media')


@register.filter
def iniciais(nome):
    partes = (nome or '').split()
    if not partes:
        return '?'
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()
