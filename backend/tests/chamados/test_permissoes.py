"""Controle de acesso por perfil (RBAC): o que cada perfil pode ver e fazer."""

from django.test import TestCase
from django.urls import reverse

from tests.fabricas import cliente, criar_admin, criar_chamado, criar_solicitante, criar_subcategoria, criar_tecnico


class AnonimoTests(TestCase):
    def test_paginas_exigem_login(self):
        chamado = criar_chamado()
        for url in [reverse('chamados:list'), reverse('chamados:create'), reverse('chamados:detail', args=[chamado.pk]),
                    reverse('ativos:list'), reverse('indicadores:painel'), reverse('usuarios:list')]:
            with self.subTest(url=url):
                resposta = cliente().get(url)
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse('usuarios:login'), resposta['Location'])


class SolicitanteTests(TestCase):
    def setUp(self):
        self.solicitante = criar_solicitante()
        self.meu = criar_chamado(solicitante=self.solicitante)
        self.de_outro = criar_chamado()

    def test_ve_so_os_proprios_chamados(self):
        resposta = cliente(self.solicitante).get(reverse('chamados:list'))

        self.assertEqual([c.pk for c in resposta.context['chamados']], [self.meu.pk])

    def test_nao_abre_chamado_de_outra_pessoa(self):
        resposta = cliente(self.solicitante).get(reverse('chamados:detail', args=[self.de_outro.pk]))

        self.assertEqual(resposta.status_code, 404)

    def test_sem_acesso_as_telas_da_equipe(self):
        urls = [
            reverse('chamados:historico'), reverse('chamados:catalogo'), reverse('chamados:notificacoes'),
            reverse('chamados:fila_versao'), reverse('ativos:list'), reverse('usuarios:list'),
            reverse('indicadores:painel'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(cliente(self.solicitante).get(url).status_code, 403)

    def test_nao_executa_acoes_da_equipe(self):
        for nome in ['pegar', 'fechar', 'retomar']:
            with self.subTest(acao=nome):
                resposta = cliente(self.solicitante).post(reverse(f'chamados:{nome}', args=[self.meu.pk]))
                self.assertEqual(resposta.status_code, 403)
        self.meu.refresh_from_db()
        self.assertIsNone(self.meu.atendente)


class TecnicoTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()

    def test_acessa_fila_historico_catalogo_ativos_e_usuarios(self):
        for nome in ['chamados:list', 'chamados:historico', 'chamados:catalogo', 'ativos:list', 'usuarios:list']:
            with self.subTest(url=nome):
                self.assertEqual(cliente(self.tecnico).get(reverse(nome)).status_code, 200)

    def test_sem_acesso_as_telas_de_administrador(self):
        subcategoria = criar_subcategoria()
        urls = [
            reverse('chamados:categoria_cadastrar'),
            reverse('chamados:categoria_editar', args=[subcategoria.categoria_id]),
            reverse('usuarios:setores'),
            reverse('usuarios:setor_cadastrar'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(cliente(self.tecnico).get(url).status_code, 403)

    def test_nao_altera_o_catalogo(self):
        subcategoria = criar_subcategoria(prioridade='baixa')
        resposta = cliente(self.tecnico).post(
            reverse('chamados:subcategoria_prioridade', args=[subcategoria.pk]), {'prioridade': 'critica'}
        )

        subcategoria.refresh_from_db()
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(subcategoria.prioridade, 'baixa')


class AdministradorTests(TestCase):
    def test_acessa_telas_de_administrador(self):
        admin = criar_admin()
        subcategoria = criar_subcategoria()
        for url in [reverse('chamados:categoria_editar', args=[subcategoria.categoria_id]), reverse('usuarios:setores')]:
            with self.subTest(url=url):
                self.assertEqual(cliente(admin).get(url).status_code, 200)
