"""Filtros e tags de template (core/templatetags/chamado_extras.py) e o dashboard."""

from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from chamados.models import Chamado
from core.templatetags.chamado_extras import (
    chamados_aguardando_resposta, duracao, iniciais, prioridade_badge, respostas_nao_vistas, status_badge,
)
from tests.fabricas import cliente, criar_chamado, criar_solicitante, criar_tecnico


class FiltrosTests(TestCase):
    def test_badges_com_valor_desconhecido_usam_o_padrao(self):
        self.assertEqual(status_badge('aguardando_solicitante'), 'status-aguardando')
        self.assertEqual(status_badge('inexistente'), 'status-aberto')
        self.assertEqual(prioridade_badge('critica'), 'prioridade-critica')
        self.assertEqual(prioridade_badge(None), 'prioridade-media')

    def test_iniciais(self):
        self.assertEqual(iniciais('Ana Maria Souza'), 'AS')
        self.assertEqual(iniciais('admin'), 'AD')
        self.assertEqual(iniciais(''), '?')
        self.assertEqual(iniciais(None), '?')

    def test_duracao(self):
        casos = [
            (None, '—'),
            (timedelta(minutes=45), '45min'),
            (timedelta(hours=3, minutes=20), '3h 20min'),
            (timedelta(days=2, hours=5, minutes=59), '2d 5h'),
            (timedelta(seconds=30), '0min'),
        ]
        for valor, esperado in casos:
            with self.subTest(valor=valor):
                self.assertEqual(duracao(valor), esperado)


class ContadoresDoMenuTests(TestCase):
    def test_chamados_aguardando_resposta_do_solicitante(self):
        chamado = criar_chamado()
        Chamado.objects.filter(pk=chamado.pk).update(status=Chamado.Status.AGUARDANDO_SOLICITANTE)
        criar_chamado(solicitante=chamado.solicitante)  # aberto: não precisa de ação dele

        self.assertEqual(chamados_aguardando_resposta(chamado.solicitante), 1)
        self.assertEqual(chamados_aguardando_resposta(criar_tecnico()), 0)
        self.assertEqual(chamados_aguardando_resposta(AnonymousUser()), 0)

    def test_respostas_nao_vistas_do_tecnico(self):
        tecnico = criar_tecnico()
        chamado = criar_chamado()
        Chamado.objects.filter(pk=chamado.pk).update(atendente=tecnico, resposta_solicitante_em=chamado.criado_em)

        self.assertEqual(respostas_nao_vistas(tecnico), 1)
        self.assertEqual(respostas_nao_vistas(chamado.solicitante), 0)
        self.assertEqual(respostas_nao_vistas(AnonymousUser()), 0)


class DashboardTests(TestCase):
    def test_exige_login(self):
        resposta = cliente().get(reverse('core:dashboard'))

        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse('usuarios:login'), resposta.url)

    def test_usuario_logado_ve_o_dashboard(self):
        usuario = criar_solicitante()

        self.assertEqual(cliente(usuario).get(reverse('core:dashboard')).context['usuario'], usuario)
