import threading
import time
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

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


class FechamentoEReaberturaTests(TestCase):
    """Fluxo de encerramento: o técnico fecha; o solicitante pode reabrir em até
    Chamado.DIAS_REABERTURA dias (volta para em andamento) e avaliar depois de cada fechamento."""

    def setUp(self):
        self.tecnico, _, self.chamado = criar_cenario()
        self.solicitante = self.chamado.solicitante
        cliente_logado(self.tecnico).post(reverse('chamados:pegar', args=[self.chamado.pk]))

    def fechar(self):
        return cliente_logado(self.tecnico).post(reverse('chamados:fechar', args=[self.chamado.pk]))

    def reabrir(self, texto='Continua sem acesso.'):
        return cliente_logado(self.solicitante).post(
            reverse('chamados:reabrir', args=[self.chamado.pk]), {'texto': texto}
        )

    def test_tecnico_fecha_chamado(self):
        self.fechar()

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)
        self.assertIsNotNone(self.chamado.fechado_em)
        self.assertTrue(self.chamado.fechado_no_prazo)
        self.assertTrue(self.chamado.sla_pausado)

    def test_solicitante_reabre_e_tecnico_fecha_de_novo(self):
        self.fechar()
        self.reabrir()

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)
        self.assertIsNone(self.chamado.fechado_em)
        self.assertFalse(self.chamado.sla_pausado)
        self.assertEqual(self.chamado.reaberturas, 1)

        self.fechar()
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)

    def test_nao_reabre_depois_do_prazo(self):
        self.fechar()
        vencido = timezone.now() - timedelta(days=Chamado.DIAS_REABERTURA, minutes=1)
        Chamado.objects.filter(pk=self.chamado.pk).update(fechado_em=vencido)

        self.reabrir()

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)
        self.assertEqual(self.chamado.reaberturas, 0)

    def test_reabrir_exige_motivo(self):
        self.fechar()
        self.reabrir(texto='')

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)

    def test_avaliacao_apos_fechar_e_descartada_ao_reabrir(self):
        self.fechar()
        cliente_logado(self.solicitante).post(reverse('chamados:avaliar', args=[self.chamado.pk]), {'avaliacao': '2'})
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.avaliacao, 2)

        self.reabrir()
        self.chamado.refresh_from_db()
        self.assertIsNone(self.chamado.avaliacao)

    def test_chamado_fechado_e_somente_leitura_para_a_equipe(self):
        self.fechar()
        cliente_logado(self.tecnico).post(
            reverse('chamados:aguardar_solicitante', args=[self.chamado.pk]), {'texto': 'Qual o ramal?'}
        )

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)
