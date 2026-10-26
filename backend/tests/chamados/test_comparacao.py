"""Comparação de filas: sistema (urgência do SLA) × FIFO (chamados/comparacao.py)."""

from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from chamados.comparacao import Expediente, comparar
from chamados.models import Chamado


class ComparacaoTests(TestCase):
    def test_mesmos_chamados_nas_duas_politicas_e_nada_gravado(self):
        antes = Chamado.objects.count()

        resultado = comparar(total_chamados=40, semente=3, tecnicos=3, carga=1.2)

        fifo, sistema = resultado['fifo'], resultado['sistema']
        for prioridade in ('geral', 'critica', 'alta', 'media', 'baixa'):
            total = lambda r: r[prioridade]['total'] if r[prioridade] else 0  # noqa: E731
            self.assertEqual(total(fifo), total(sistema))
        self.assertEqual(fifo['geral']['total'], 40)
        self.assertEqual(Chamado.objects.count(), antes)

    def test_sistema_atende_criticos_antes(self):
        resultado = comparar(total_chamados=60, semente=1, tecnicos=3, carga=1.2)

        fifo, sistema = resultado['fifo']['critica'], resultado['sistema']['critica']
        self.assertLess(sistema['espera_media'], fifo['espera_media'])
        self.assertGreaterEqual(sistema['nivel_servico'], fifo['nivel_servico'])

    @override_settings(DEBUG=True)
    def test_comando(self):
        saida = StringIO()
        call_command('comparar_filas', '--chamados', '15', '--repeticoes', '1', '--cargas', '1.0', stdout=saida)

        self.assertIn('Nível de serviço — crítica', saida.getvalue())

    def test_comando_recusa_em_producao(self):
        with self.assertRaises(CommandError):
            call_command('comparar_filas', stdout=StringIO())


class ExpedienteTests(TestCase):
    def setUp(self):
        self.expediente = Expediente(8, 17)
        tz = timezone.get_current_timezone()
        self.quando = lambda d, h, m=0: datetime(2026, 10, d, h, m, tzinfo=tz)  # 26/10/2026 é segunda

    def test_horario_de_trabalho(self):
        self.assertTrue(self.expediente.trabalhando(self.quando(26, 8)))
        self.assertTrue(self.expediente.trabalhando(self.quando(26, 16, 59)))
        self.assertFalse(self.expediente.trabalhando(self.quando(26, 17)))
        self.assertFalse(self.expediente.trabalhando(self.quando(31, 10)))  # sábado
        self.assertTrue(Expediente(8, 17, dias_uteis=False).trabalhando(self.quando(31, 10)))

    def test_proximo_inicio(self):
        self.assertEqual(self.expediente.proximo_inicio(self.quando(26, 6)), self.quando(26, 8))
        self.assertEqual(self.expediente.proximo_inicio(self.quando(26, 20)), self.quando(27, 8))
        segunda = datetime(2026, 11, 2, 8, tzinfo=timezone.get_current_timezone())
        self.assertEqual(self.expediente.proximo_inicio(self.quando(30, 18)), segunda)  # sexta à noite
        self.assertEqual(self.expediente.proximo_inicio(self.quando(27, 10)), self.quando(27, 10))

    def test_ninguem_e_atribuido_fora_do_expediente(self):
        capturados = []
        original = Chamado.atribuir

        def espiar(chamado, tecnico):
            capturados.append(timezone.now())
            return original(chamado, tecnico)

        with mock.patch.object(Chamado, 'atribuir', espiar):
            resultado = comparar(total_chamados=40, semente=2, tecnicos=5, carga=1.0, expediente=self.expediente)

        self.assertTrue(capturados)
        self.assertTrue(all(self.expediente.trabalhando(momento) for momento in capturados))
        self.assertEqual(resultado['fifo']['geral']['total'], 40)
        self.assertIn('critica_fora_expediente', resultado['sistema'])
