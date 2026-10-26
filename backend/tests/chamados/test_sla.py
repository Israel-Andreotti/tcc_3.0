"""Regras de SLA e prioridade do chamado (testes de unidade sobre o model).

A passagem do tempo é simulada trocando o relógio do Django (`django.utils.timezone.now`)."""

from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chamados.models import Chamado, Prioridade, SLAPrioridade, prioridade_do_chamado
from tests.fabricas import cliente, criar_chamado, criar_setor, criar_solicitante, criar_subcategoria, criar_tecnico

AGORA = timezone.now()


@contextmanager
def relogio(horas=0):
    """Executa o bloco como se fossem AGORA + `horas`."""
    with mock.patch('django.utils.timezone.now', return_value=AGORA + timedelta(hours=horas)):
        yield


def horas_do_sla(chamado):
    return round((chamado.prazo_sla - chamado.criado_em).total_seconds() / 3600, 2)


class PrioridadeTests(TestCase):
    def test_prioridade_vem_da_subcategoria(self):
        chamado = criar_chamado(subcategoria=criar_subcategoria(prioridade='alta'))

        self.assertEqual(chamado.prioridade, Prioridade.ALTA)

    def test_setor_critico_sobe_um_nivel(self):
        setor = criar_setor(critico=True)
        esperado = {'baixa': 'media', 'media': 'alta', 'alta': 'critica', 'critica': 'critica'}
        for da_subcategoria, do_chamado in esperado.items():
            with self.subTest(prioridade=da_subcategoria):
                chamado = criar_chamado(
                    solicitante=criar_solicitante(setor=setor),
                    subcategoria=criar_subcategoria(prioridade=da_subcategoria),
                )
                self.assertEqual(chamado.prioridade, do_chamado)

    def test_funcao_prioridade_do_chamado(self):
        self.assertEqual(prioridade_do_chamado(Prioridade.BAIXA, None), Prioridade.BAIXA)
        self.assertEqual(prioridade_do_chamado(Prioridade.BAIXA, criar_setor(critico=False)), Prioridade.BAIXA)
        self.assertEqual(prioridade_do_chamado(Prioridade.CRITICA, criar_setor(critico=True)), Prioridade.CRITICA)

    def test_prioridade_e_tipo_definidos_so_na_abertura(self):
        subcategoria = criar_subcategoria(prioridade='baixa', tipo='incidente')
        chamado = criar_chamado(subcategoria=subcategoria)
        prazo = chamado.prazo_sla

        subcategoria.prioridade, subcategoria.tipo = 'critica', 'requisicao'
        subcategoria.save()
        chamado.descricao = 'atualizado'
        chamado.save()
        chamado.refresh_from_db()

        self.assertEqual(chamado.prioridade, Prioridade.BAIXA)
        self.assertEqual(chamado.tipo, 'incidente')
        self.assertEqual(chamado.prazo_sla, prazo)

    def test_titulo_do_chamado_nao_muda_a_prioridade(self):
        chamado = criar_chamado(subcategoria=criar_subcategoria(prioridade='media'))

        self.assertEqual(chamado.titulo, chamado.subcategoria.nome)


class PrazoSLATests(TestCase):
    def test_prazo_segue_as_horas_configuradas_por_prioridade(self):
        for sla in SLAPrioridade.objects.all():
            with self.subTest(prioridade=sla.prioridade):
                chamado = criar_chamado(subcategoria=criar_subcategoria(prioridade=sla.prioridade))
                self.assertAlmostEqual(horas_do_sla(chamado), sla.horas, places=1)

    def test_horas_editadas_pelo_administrador_valem_para_novos_chamados(self):
        SLAPrioridade.objects.filter(prioridade='media').update(horas=10)
        chamado = criar_chamado(subcategoria=criar_subcategoria(prioridade='media'))

        self.assertAlmostEqual(horas_do_sla(chamado), 10, places=1)

    def test_sem_configuracao_usa_o_padrao_do_codigo(self):
        SLAPrioridade.objects.filter(prioridade='alta').delete()
        chamado = criar_chamado(subcategoria=criar_subcategoria(prioridade='alta'))

        self.assertAlmostEqual(horas_do_sla(chamado), Chamado.SLA_HORAS['alta'], places=1)

    def test_solicitante_vip_tem_prazo_reduzido_em_25_por_cento(self):
        horas = SLAPrioridade.objects.get(prioridade='baixa').horas
        chamado = criar_chamado(
            solicitante=criar_solicitante(vip=True), subcategoria=criar_subcategoria(prioridade='baixa')
        )

        self.assertAlmostEqual(horas_do_sla(chamado), horas * Chamado.VIP_SLA_MULTIPLICADOR, places=1)


class AndamentoDoSLATests(TestCase):
    """Percentual, cor, estouro e texto de tempo restante ao longo do tempo (SLA de 10h)."""

    def setUp(self):
        SLAPrioridade.objects.filter(prioridade='media').update(horas=10)
        with relogio(0):
            self.chamado = criar_chamado(subcategoria=criar_subcategoria(prioridade='media'))

    def test_percentual_e_cor_conforme_o_tempo_passa(self):
        casos = [(0, 0, 'ok'), (5, 50, 'ok'), (7, 70, 'atencao'), (10, 100, 'critico'), (30, 100, 'critico')]
        for horas, percentual, cor in casos:
            with self.subTest(horas=horas), relogio(horas):
                self.assertEqual(self.chamado.sla_percentual, percentual)
                self.assertEqual(self.chamado.sla_cor, cor)

    def test_estouro_e_texto_de_tempo_restante(self):
        with relogio(4):
            self.assertFalse(self.chamado.sla_estourado)
            self.assertEqual(self.chamado.sla_tempo_restante_display, '6h 0min restantes')
        with relogio(12):
            self.assertTrue(self.chamado.sla_estourado)
            self.assertEqual(self.chamado.sla_tempo_restante_display, 'Atrasado há 2h 0min')

    def test_pausa_congela_o_sla(self):
        with relogio(3):
            self.chamado.pausar_sla()
        for horas in (3, 20, 200):
            with self.subTest(horas=horas), relogio(horas):
                self.assertEqual(self.chamado.sla_percentual, 30)
                self.assertFalse(self.chamado.sla_estourado)
                self.assertEqual(self.chamado.sla_cor, 'pausado')
                self.assertEqual(self.chamado.sla_tempo_restante_display, 'Pausado')

    def test_pausado_depois_de_estourar_continua_estourado(self):
        with relogio(12):  # 2h depois do prazo de 10h
            self.chamado.pausar_sla()
        for horas in (12, 50):
            with self.subTest(horas=horas), relogio(horas):
                self.assertTrue(self.chamado.sla_estourado)
                self.assertEqual(self.chamado.sla_cor, 'pausado')
                self.assertEqual(self.chamado.sla_tempo_restante_display, 'Pausado · estourado')

    def test_fila_mostra_pausado_e_estourado(self):
        with relogio(12):
            self.chamado.pausar_sla()
            self.chamado.status = Chamado.Status.AGUARDANDO_SOLICITANTE
            self.chamado.save()
            resposta = cliente(criar_tecnico()).get(reverse('chamados:list'))

        self.assertContains(resposta, 'title="O prazo estourou antes da pausa">estourado</span>')

    def test_retomar_estende_o_prazo_pelo_tempo_pausado(self):
        prazo_original = self.chamado.prazo_sla
        with relogio(3):
            self.chamado.pausar_sla()
        with relogio(8):  # ficou 5h pausado
            self.chamado.retomar_sla()

        self.assertEqual(self.chamado.prazo_sla - prazo_original, timedelta(hours=5))
        self.assertEqual(self.chamado.sla_tempo_pausado, timedelta(hours=5))
        with relogio(9):  # 9h corridas - 5h pausadas = 4h de 10h
            self.assertEqual(self.chamado.sla_percentual, 40)
            self.assertEqual(self.chamado.sla_tempo_restante_display, '6h 0min restantes')

    def test_pausar_duas_vezes_nao_reinicia_a_pausa(self):
        with relogio(2):
            self.chamado.pausar_sla()
        with relogio(5):
            self.chamado.pausar_sla()
        with relogio(6):
            self.chamado.retomar_sla()

        self.assertEqual(self.chamado.sla_tempo_pausado, timedelta(hours=4))

    def test_chamado_fechado_nao_conta_como_estourado(self):
        with relogio(12):
            self.chamado.fechar()
            self.assertFalse(self.chamado.sla_estourado)
            self.assertTrue(self.chamado.encerrado)
            self.assertFalse(self.chamado.fechado_no_prazo)
