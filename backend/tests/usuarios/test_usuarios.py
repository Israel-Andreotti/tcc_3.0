"""Usuários e setores: matrícula, superadministrador, senha temporária, troca obrigatória de senha,
login por perfil, login rápido de testes e setor crítico."""

from django.test import TestCase, override_settings
from django.urls import reverse

from tests.fabricas import SENHA, cliente, criar_admin, criar_setor, criar_solicitante, criar_tecnico, mensagens
from usuarios.models import Setor, Usuario
from usuarios.views import SENHA_TEMPORARIA_CHARS, gerar_senha_temporaria


class UsuarioModelTests(TestCase):
    def test_matricula_sequencial(self):
        primeiro = criar_solicitante()
        segundo = criar_solicitante()

        self.assertRegex(primeiro.matricula, r'^\d{6}$')
        self.assertEqual(int(segundo.matricula), int(primeiro.matricula) + 1)

    def test_superadministrador_e_sempre_administrador(self):
        usuario = criar_solicitante()
        usuario.super_admin = True
        usuario.save()

        usuario.refresh_from_db()
        self.assertEqual(usuario.perfil, Usuario.Perfil.ADMINISTRADOR)

    def test_senha_temporaria(self):
        senhas = {gerar_senha_temporaria() for _ in range(50)}

        self.assertEqual(len(senhas), 50)  # aleatórias
        for senha in senhas:
            self.assertEqual(len(senha), 10)
            self.assertTrue(set(senha) <= set(SENHA_TEMPORARIA_CHARS))
        self.assertFalse(set('IOl01') & set(SENHA_TEMPORARIA_CHARS))  # sem caracteres ambíguos


class GestaoDeUsuariosTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()
        self.c = cliente(self.tecnico)

    def test_cadastro_gera_senha_temporaria_e_exige_troca(self):
        resposta = self.c.post(reverse('usuarios:cadastrar'), {
            'username': 'novo.usuario', 'first_name': 'Novo', 'last_name': 'Usuário', 'email': 'novo@exemplo.com',
            'telefone': '(11)98765-4321', 'perfil': 'solicitante', 'setor': criar_setor().pk,
        })

        usuario = Usuario.objects.get(username='novo.usuario')
        senha = resposta.context['senha_temporaria']
        self.assertTrue(usuario.check_password(senha))
        self.assertTrue(usuario.deve_trocar_senha)
        self.assertEqual(usuario.telefone, '11987654321')  # guardado só com dígitos

    def test_telefone_invalido(self):
        resposta = self.c.post(reverse('usuarios:cadastrar'), {
            'username': 'x', 'first_name': 'X', 'last_name': 'Y', 'email': 'x@exemplo.com',
            'telefone': '123', 'perfil': 'solicitante',
        })

        self.assertFalse(Usuario.objects.filter(username='x').exists())
        self.assertContains(resposta, 'Telefone inválido')

    def test_resetar_senha(self):
        usuario = criar_solicitante()
        resposta = self.c.post(reverse('usuarios:resetar_senha', args=[usuario.pk]))

        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(resposta.context['senha_temporaria']))
        self.assertTrue(usuario.deve_trocar_senha)

    def test_desativar_e_reativar(self):
        usuario = criar_solicitante()
        url = reverse('usuarios:toggle_ativo', args=[usuario.pk])

        self.c.post(url)
        usuario.refresh_from_db()
        self.assertFalse(usuario.is_active)
        self.c.post(url)
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_active)

    def test_nao_desativa_a_propria_conta(self):
        resposta = self.c.post(reverse('usuarios:toggle_ativo', args=[self.tecnico.pk]), follow=True)

        self.tecnico.refresh_from_db()
        self.assertTrue(self.tecnico.is_active)
        self.assertIn('Você não pode desativar a própria conta.', mensagens(resposta))

    def test_superadministrador_protegido_e_oculto(self):
        super_admin = criar_admin(super_admin=True)
        senha_antes = super_admin.password

        self.c.post(reverse('usuarios:toggle_ativo', args=[super_admin.pk]))
        self.c.post(reverse('usuarios:resetar_senha', args=[super_admin.pk]))
        edicao = self.c.get(reverse('usuarios:editar', args=[super_admin.pk]))
        lista = self.c.get(reverse('usuarios:list'))

        super_admin.refresh_from_db()
        self.assertTrue(super_admin.is_active)
        self.assertEqual(super_admin.password, senha_antes)
        self.assertRedirects(edicao, reverse('usuarios:list'))
        self.assertNotIn(super_admin, lista.context['usuarios'])


@override_settings(LOGIN_RAPIDO=False)
class LoginETrocaDeSenhaTests(TestCase):
    def login(self, usuario, senha=SENHA):
        return cliente().post(reverse('usuarios:login'), {'username': usuario.username, 'password': senha})

    def test_login_redireciona_conforme_o_perfil(self):
        self.assertRedirects(self.login(criar_tecnico()), reverse('chamados:list'), fetch_redirect_response=False)
        self.assertRedirects(self.login(criar_admin()), reverse('chamados:list'), fetch_redirect_response=False)
        self.assertRedirects(self.login(criar_solicitante()), reverse('chamados:create'), fetch_redirect_response=False)

    def test_senha_errada(self):
        resposta = self.login(criar_solicitante(), senha='errada')

        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.wsgi_request.user.is_authenticated)

    def test_troca_de_senha_obrigatoria_bloqueia_o_sistema(self):
        usuario = criar_solicitante(deve_trocar_senha=True)
        c = cliente(usuario)

        resposta = c.get(reverse('chamados:list'))
        self.assertRedirects(resposta, reverse('usuarios:trocar_senha'))

        c.post(reverse('usuarios:trocar_senha'), {
            'old_password': SENHA, 'new_password1': 'Nova-senha-forte-2026', 'new_password2': 'Nova-senha-forte-2026',
        })
        usuario.refresh_from_db()
        self.assertFalse(usuario.deve_trocar_senha)
        self.assertEqual(c.get(reverse('chamados:list')).status_code, 200)

    def test_login_volta_para_a_pagina_pedida(self):
        resposta = cliente().post(
            reverse('usuarios:login') + '?next=' + reverse('ativos:list'),
            {'username': criar_tecnico().username, 'password': SENHA},
        )

        self.assertRedirects(resposta, reverse('ativos:list'), fetch_redirect_response=False)

    def test_login_rapido_desligado_responde_404(self):
        usuario = criar_solicitante()

        self.assertEqual(cliente().post(reverse('usuarios:login_rapido', args=[usuario.pk])).status_code, 404)
        self.assertNotIn('Entrar como', cliente().get(reverse('usuarios:login')).content.decode())


@override_settings(LOGIN_RAPIDO=True)
class LoginRapidoLigadoTests(TestCase):
    def test_entra_sem_senha_e_ignora_troca_obrigatoria(self):
        usuario = criar_solicitante(deve_trocar_senha=True)
        c = cliente()

        resposta = c.post(reverse('usuarios:login_rapido', args=[usuario.pk]))

        self.assertRedirects(resposta, reverse('chamados:create'), fetch_redirect_response=False)
        self.assertEqual(c.get(reverse('chamados:list')).status_code, 200)

    def test_tela_de_login_lista_so_usuarios_ativos(self):
        ativo = criar_solicitante()
        inativo = criar_solicitante(is_active=False)

        usuarios = list(cliente().get(reverse('usuarios:login')).context['usuarios_login_rapido'])
        self.assertIn(ativo, usuarios)
        self.assertNotIn(inativo, usuarios)

    def test_nao_entra_como_usuario_inativo(self):
        usuario = criar_solicitante(is_active=False)

        self.assertEqual(cliente().post(reverse('usuarios:login_rapido', args=[usuario.pk])).status_code, 404)


class ListaDeUsuariosTests(TestCase):
    def setUp(self):
        self.c = cliente(criar_admin())
        self.solicitante = criar_solicitante(first_name='Anabela', last_name='Prado')
        self.tecnico = criar_tecnico(first_name='Anabela', last_name='Reis')
        self.inativo = criar_solicitante(first_name='Anabela', last_name='Costa', is_active=False)

    def listar(self, **filtros):
        return set(self.c.get(reverse('usuarios:list'), filtros).context['usuarios'])

    def test_busca_e_filtros(self):
        self.assertEqual(self.listar(q='anabela'), {self.solicitante, self.tecnico, self.inativo})
        self.assertEqual(self.listar(q='anabela', perfil='atendente'), {self.tecnico})
        self.assertEqual(self.listar(q='anabela', status='ativo'), {self.solicitante, self.tecnico})
        self.assertEqual(self.listar(q='anabela', status='inativo'), {self.inativo})
        self.assertEqual(self.listar(q=self.solicitante.matricula), {self.solicitante})


class SetoresTests(TestCase):
    def setUp(self):
        self.c = cliente(criar_admin())

    def test_cadastra_setor_ja_critico(self):
        self.c.post(reverse('usuarios:setor_cadastrar'), {'nome': 'UTI Adulto', 'critico': 'on'})

        self.assertTrue(Setor.objects.get(nome='UTI Adulto').critico)

    def test_marcar_e_desmarcar_setor_critico(self):
        setor = criar_setor()
        url = reverse('usuarios:setor_critico', args=[setor.pk])

        self.c.post(url)
        setor.refresh_from_db()
        self.assertTrue(setor.critico)
        self.c.post(url)
        setor.refresh_from_db()
        self.assertFalse(setor.critico)
