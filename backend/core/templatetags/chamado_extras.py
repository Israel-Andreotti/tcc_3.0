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
