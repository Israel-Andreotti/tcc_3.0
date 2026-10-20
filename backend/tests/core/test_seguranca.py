"""Segurança: bloqueio de login por força bruta (django-axes), expiração da sessão por inatividade
e páginas de erro próprias."""

import time
from unittest import mock

from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.urls import reverse

from tests.fabricas import SENHA, cliente, criar_solicitante, criar_tecnico, mensagens


@override_settings(LOGIN_RAPIDO=False)
class BloqueioDeLoginTests(TestCase):
    URL = reverse('usuarios:login')

    def setUp(self):
        self.usuario = criar_solicitante()
        self.c = cliente()

    def tentar(self, senha):
        return self.c.post(self.URL, {'username': self.usuario.username, 'password': senha})

    def run(self, result=None):
        # O axes registra cada falha no log (WARNING); aqui fica capturado em vez de sujar a saída.
        with self.assertLogs('axes', level='WARNING') as self.logs:
            return super().run(result)

    def test_cinco_senhas_erradas_bloqueiam_ate_a_senha_certa(self):
        for _ in range(5):
            self.tentar('errada')

        resposta = self.tentar(SENHA)

        self.assertEqual(resposta.status_code, 429)
        self.assertTemplateUsed(resposta, 'usuarios/login_bloqueado.html')
        self.assertContains(resposta, '15min', status_code=429)
        self.assertFalse(resposta.wsgi_request.user.is_authenticated)
        self.assertTrue(any('Locking out' in linha for linha in self.logs.output))

    def test_login_certo_zera_as_tentativas(self):
        for _ in range(4):
            self.tentar('errada')
        self.assertEqual(self.tentar(SENHA).status_code, 302)
        self.c.logout()

        for _ in range(4):
            self.tentar('errada')
        self.assertEqual(self.tentar(SENHA).status_code, 302)  # não acumulou com as 4 anteriores

    def test_bloqueio_e_por_usuario(self):
        for _ in range(5):
            self.tentar('errada')
        outro = criar_solicitante()

        resposta = self.c.post(self.URL, {'username': outro.username, 'password': SENHA})

        self.assertEqual(resposta.status_code, 302)


@override_settings(SESSAO_INATIVIDADE_MINUTOS=30)
class SessaoInativaTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()
        self.c = cliente(self.tecnico)
        self.agora = time.time()
        self.acessar(reverse('chamados:list'))  # registra a última atividade

    def acessar(self, url, minutos_depois=0, **kwargs):
        with mock.patch('core.middleware.time.time', return_value=self.agora + minutos_depois * 60):
            return self.c.get(url, **kwargs)

    def test_uso_dentro_do_limite_mantem_a_sessao(self):
        self.assertEqual(self.acessar(reverse('chamados:list'), minutos_depois=29).status_code, 200)
        self.assertEqual(self.acessar(reverse('chamados:list'), minutos_depois=58).status_code, 200)

    def test_inatividade_encerra_a_sessao_com_aviso(self):
        url = reverse('chamados:list')
        resposta = self.acessar(url, minutos_depois=31, follow=True)

        self.assertRedirects(resposta, f"{reverse('usuarios:login')}?next={url}")
        self.assertIn('Sua sessão expirou por inatividade. Entre novamente.', mensagens(resposta))
        self.assertFalse(resposta.wsgi_request.user.is_authenticated)

    def test_consultas_automaticas_nao_contam_como_uso(self):
        for minutos in (10, 20, 29):
            self.assertEqual(self.acessar(reverse('chamados:notificacoes'), minutos_depois=minutos).status_code, 200)

        resposta = self.acessar(reverse('chamados:list'), minutos_depois=31)

        self.assertEqual(resposta.status_code, 302)

    def test_consulta_automatica_com_sessao_vencida_responde_401(self):
        resposta = self.acessar(reverse('chamados:fila_versao'), minutos_depois=31)

        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.json(), {'sessao_expirada': True})
        # O logout acontece no acesso normal seguinte (o recarregamento feito pelo JavaScript).
        self.assertEqual(self.acessar(reverse('chamados:list'), minutos_depois=31).status_code, 302)


class PaginasDeErroTests(TestCase):
    def test_404(self):
        resposta = cliente(criar_solicitante()).get('/nao-existe/')

        self.assertEqual(resposta.status_code, 404)
        self.assertTemplateUsed(resposta, '404.html')
        self.assertContains(resposta, 'Voltar aos chamados', status_code=404)

    def test_404_anonimo_aponta_para_o_login(self):
        self.assertContains(cliente().get('/nao-existe/'), 'Ir para o login', status_code=404)

    def test_403(self):
        resposta = cliente(criar_solicitante()).get(reverse('usuarios:list'))

        self.assertEqual(resposta.status_code, 403)
        self.assertTemplateUsed(resposta, '403.html')

    def test_500_renderiza_sem_contexto(self):
        html = get_template('500.html').render()

        self.assertIn('Algo deu errado no servidor', html)
