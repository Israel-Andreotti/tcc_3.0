import threading
import time
from unittest import mock

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from usuarios.models import Setor, Usuario

from .models import Categoria, Chamado, Subcategoria


def criar_cenario():
    """Dois técnicos, um solicitante e um chamado aberto sem técnico."""
    setor = Setor.objects.create(nome='Setor de teste')
    tecnico_a = Usuario.objects.create_user('tecnico.a', password='x', perfil='atendente')
    tecnico_b = Usuario.objects.create_user('tecnico.b', password='x', perfil='atendente')
    solicitante = Usuario.objects.create_user('solicitante', password='x', setor=setor)
    categoria = Categoria.objects.create(nome='Categoria de teste')
    subcategoria = Subcategoria.objects.create(categoria=categoria, nome='Serviço de teste', prioridade='alta')
    chamado = Chamado.objects.create(
        titulo='VPN', descricao='Sem acesso à VPN.', solicitante=solicitante, setor=setor,
        categoria=categoria, subcategoria=subcategoria,
    )
    return tecnico_a, tecnico_b, chamado


def cliente_logado(usuario):
    cliente = Client()
    cliente.force_login(usuario)
    return cliente


class AtribuirChamadoTests(TestCase):
    def setUp(self):
        self.tecnico_a, self.tecnico_b, self.chamado = criar_cenario()
        self.url = reverse('chamados:pegar', args=[self.chamado.pk])

    def test_atribui_chamado_livre(self):
        resposta = cliente_logado(self.tecnico_a).post(self.url)

        self.chamado.refresh_from_db()
        self.assertRedirects(resposta, reverse('chamados:detail', args=[self.chamado.pk]))
        self.assertEqual(self.chamado.atendente, self.tecnico_a)
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)

    def test_nao_toma_chamado_de_outro_tecnico(self):
        cliente_logado(self.tecnico_a).post(self.url)
        resposta = cliente_logado(self.tecnico_b).post(self.url, follow=True)

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.atendente, self.tecnico_a)
        self.assertContains(resposta, 'já foi atribuído a')


class AtribuirChamadoConcorrenciaTests(TransactionTestCase):
    """Condição de corrida: dois técnicos clicam "Atribuir a mim" ao mesmo tempo. Cada requisição roda
    numa thread com a sua própria conexão ao PostgreSQL, e um atraso dentro do save() alarga a janela
    entre "ler" e "salvar". Com a trava de linha (select_for_update), só uma pode atribuir; a outra
    espera e é recusada, sem sobrescrever o técnico."""

    def test_cliques_simultaneos_so_um_tecnico_atribui(self):
        tecnico_a, tecnico_b, chamado = criar_cenario()
        url = reverse('chamados:pegar', args=[chamado.pk])
        clientes = {tecnico.pk: cliente_logado(tecnico) for tecnico in (tecnico_a, tecnico_b)}
        url_sucesso = reverse('chamados:detail', args=[chamado.pk])
        resultados, erros = {}, []
        largada = threading.Barrier(2)
        save_original = Chamado.save

        def save_lento(self, *args, **kwargs):
            time.sleep(0.5)
            return save_original(self, *args, **kwargs)

        def clicar(tecnico):
            largada.wait()
            try:
                resposta = clientes[tecnico.pk].post(url)
                resultados[tecnico.username] = 'atribuiu' if resposta['Location'] == url_sucesso else 'recusado'
            except Exception as erro:  # noqa: BLE001 — qualquer erro na requisição reprova o teste
                erros.append(erro)
            finally:
                connection.close()

        with mock.patch.object(Chamado, 'save', save_lento):
            threads = [threading.Thread(target=clicar, args=(tecnico,)) for tecnico in (tecnico_a, tecnico_b)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(erros, [])
        self.assertEqual(sorted(resultados.values()), ['atribuiu', 'recusado'])
        chamado.refresh_from_db()
        vencedor = next(nome for nome, resultado in resultados.items() if resultado == 'atribuiu')
        self.assertEqual(chamado.atendente.username, vencedor)
