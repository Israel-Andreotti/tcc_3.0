"""Fábricas de dados para os testes: criam usuários, setores, catálogo e chamados com nomes únicos.

Os nomes levam um contador porque o banco de teste já vem com dados das migrations (catálogo,
setores e chamados de demonstração) e vários campos são únicos.
"""

from itertools import count

from django.test import Client

from chamados.models import Categoria, Chamado, Subcategoria
from usuarios.models import Setor, Usuario

SENHA = 'senha-de-teste-123'
_sequencia = count(1)


def _n():
    return next(_sequencia)


def criar_setor(nome=None, critico=False):
    return Setor.objects.create(nome=nome or f'Setor de teste {_n()}', critico=critico)


def criar_usuario(perfil='solicitante', setor=None, **campos):
    numero = _n()
    usuario = Usuario.objects.create_user(
        username=campos.pop('username', f'{perfil}.teste{numero}'),
        password=SENHA,
        first_name=campos.pop('first_name', perfil.capitalize()),
        last_name=campos.pop('last_name', f'Teste {numero}'),
        perfil=perfil,
        setor=setor,
        **campos,
    )
    return usuario


def criar_solicitante(setor=None, **campos):
    return criar_usuario('solicitante', setor=setor or criar_setor(), **campos)


def criar_tecnico(**campos):
    return criar_usuario('atendente', **campos)


def criar_admin(**campos):
    return criar_usuario('administrador', **campos)


def criar_subcategoria(prioridade='media', tipo='incidente', categoria=None, nome=None):
    categoria = categoria or Categoria.objects.create(nome=f'Categoria de teste {_n()}')
    return Subcategoria.objects.create(
        categoria=categoria, nome=nome or f'Serviço de teste {_n()}', prioridade=prioridade, tipo=tipo,
    )


def criar_chamado(solicitante=None, subcategoria=None, setor=None, **campos):
    """Chamado aberto pelo model (save() aplica prioridade, tipo, código e prazo de SLA)."""
    solicitante = solicitante or criar_solicitante()
    subcategoria = subcategoria or criar_subcategoria()
    return Chamado.objects.create(
        titulo=subcategoria.nome,
        descricao=campos.pop('descricao', 'Descrição de teste.'),
        solicitante=solicitante,
        setor=setor or solicitante.setor,
        categoria=subcategoria.categoria,
        subcategoria=subcategoria,
        **campos,
    )


def cliente(usuario=None):
    """Client do Django já autenticado como `usuario` (ou anônimo)."""
    c = Client()
    if usuario is not None:
        c.force_login(usuario)
    return c


def mensagens(resposta):
    """Textos das mensagens do framework de messages numa resposta obtida com follow=True."""
    return [str(m) for m in resposta.context['messages']] if resposta.context else []
