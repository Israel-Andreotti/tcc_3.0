"""Simulação de demonstração (chamados/demo.py e o comando simular_demo)."""

import random
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from chamados.demo import PREFIXO, Simulador, rodar_cenario
from chamados.models import Chamado, EventoChamado
from tests.fabricas import criar_chamado, criar_solicitante, criar_tecnico
from usuarios.models import Usuario

# Sem a espera mínima entre uma mudança e a próxima reação, para os passos rodarem em sequência.
sem_espera = mock.patch('chamados.demo.IDADE_MINIMA', timedelta(0))


class ComandoTests(TestCase):
    def test_desligado_sem_demo(self):
        with self.assertRaises(CommandError):
            call_command('simular_demo', stdout=StringIO())
        self.assertFalse(Usuario.objects.filter(username='demo.carlos').exists())

    @override_settings(DEMO=True)
    def test_ligado_com_demo(self):
        saida = StringIO()
        call_command('simular_demo', '--semente', '1', '--passos', '5', stdout=saida)

        self.assertIn('ações simuladas', saida.getvalue())
        self.assertTrue(Chamado.objects.filter(solicitante__username__startswith=PREFIXO,
                                               eventos__tipo=EventoChamado.Tipo.ABERTURA).exists())


@sem_espera
class SimuladorTests(TestCase):
    def setUp(self):
        Chamado.objects.all().delete()  # o banco de teste vem com chamados de demonstração
        self.simulador = Simulador(random.Random(42))

    def rodar(self, passos):
        for _ in range(passos):
            self.simulador.passo()

    def test_usuarios_ficticios_sem_senha(self):
        self.simulador.preparar_usuarios()

        tecnico = Usuario.objects.get(username='demo.carlos')
        self.assertEqual(tecnico.perfil, Usuario.Perfil.ATENDENTE)
        self.assertFalse(tecnico.has_usable_password())
        self.assertTrue(Usuario.objects.get(username='demo.luciana').setor.nome == 'Emergência')

    def test_abre_chamado_como_um_usuario(self):
        self.simulador.preparar_usuarios()
        chamado = self.simulador.abrir_chamado()

        self.assertTrue(chamado.solicitante.username.startswith(PREFIXO))
        self.assertEqual(chamado.setor, chamado.solicitante.setor)
        self.assertRegex(chamado.codigo, r'^(INC|REQ)\d{6}$')
        self.assertIsNotNone(chamado.prazo_sla)
        self.assertTrue(chamado.eventos.get().descricao.startswith('Abriu o chamado'))

    def test_ciclo_completo(self):
        self.rodar(80)

        fechados = Chamado.objects.filter(status=Chamado.Status.FECHADO)
        self.assertTrue(fechados.exists())
        self.assertTrue(fechados.filter(avaliacao__isnull=False).exists())
        self.assertTrue(Chamado.objects.filter(pediu_info=True).exists())
        for chamado in fechados:
            self.assertIsNotNone(chamado.atendente)
            self.assertIsNotNone(chamado.primeira_resposta_em)
            self.assertTrue(chamado.eventos.filter(tipo=EventoChamado.Tipo.FECHADO).exists())
        for chamado in Chamado.objects.filter(status=Chamado.Status.AGUARDANDO_SOLICITANTE):
            self.assertTrue(chamado.sla_pausado)

    def test_nao_toca_em_chamados_de_pessoas_reais(self):
        real = criar_chamado()
        tecnico_real = criar_tecnico()
        demo_com_tecnico_real = self.simulador_abre()
        demo_com_tecnico_real.atribuir(tecnico_real)
        demo_com_tecnico_real.save()

        self.rodar(40)

        for chamado in (real, demo_com_tecnico_real):
            antes = (chamado.status, chamado.atendente_id, chamado.eventos.count())
            chamado.refresh_from_db()
            self.assertEqual((chamado.status, chamado.atendente_id, chamado.eventos.count()), antes)

    def test_respeita_o_limite_de_abertos(self):
        with mock.patch('chamados.demo.LIMITE_ABERTOS', 3), mock.patch.object(Simulador, 'atender'):
            for _ in range(10):
                self.simulador.passo(novos=2)

        self.assertEqual(Chamado.objects.exclude(status=Chamado.Status.FECHADO).count(), 3)

    def test_chamado_demorado_estoura_o_sla(self):
        with mock.patch('chamados.demo.FRACAO_DEMORADOS', 1.0):  # todos demorados
            self.rodar(40)
            em_andamento = Chamado.objects.filter(status=Chamado.Status.EM_ANDAMENTO)
            self.assertFalse(Chamado.objects.filter(status=Chamado.Status.FECHADO).exists())

            # Seis horas depois: os de prazo curto (crítica 4h) já podem fechar, fora do prazo.
            depois = timezone.now() + timedelta(hours=6)
            with mock.patch('django.utils.timezone.now', return_value=depois):
                self.rodar(40)

        criticos = Chamado.objects.filter(prioridade='critica', status=Chamado.Status.FECHADO)
        self.assertTrue(em_andamento.exists())
        self.assertTrue(criticos.exists())
        self.assertFalse(criticos.filter(fechado_no_prazo=True).exists())

    def test_solicitante_real_nao_conta_como_ficticio(self):
        criar_solicitante(username='demonstracao.real')  # parecido, mas sem o ponto do prefixo
        self.simulador.preparar_usuarios()

        self.assertTrue(all(u.username.startswith(PREFIXO) for u in self.simulador.solicitantes))

    def simulador_abre(self):
        self.simulador.preparar_usuarios()
        return self.simulador.abrir_chamado()


class CenarioTests(TestCase):
    def test_cenario_completo_nao_grava_nada(self):
        antes = (Chamado.objects.count(), EventoChamado.objects.count())

        resultado = rodar_cenario(total_chamados=20, semente=3)

        self.assertEqual((resultado['total_chamados'], resultado['total_fechados']), (20, 20))
        self.assertEqual(resultado['em_aberto_no_fim'], 0)
        self.assertLess(resultado['passos'], 5000)  # terminou sozinho, não pelo limite de segurança
        self.assertEqual((Chamado.objects.count(), EventoChamado.objects.count()), antes)

    def test_reabre_no_maximo_uma_vez(self):
        with sem_espera:
            Chamado.objects.all().delete()
            simulador = Simulador(random.Random(5))
            for _ in range(200):
                simulador.passo()

        self.assertFalse(Chamado.objects.filter(reaberturas__gt=1).exists())

    @override_settings(DEBUG=True)
    def test_comando_gera_tabela_e_csv(self):
        caminho = Path(tempfile.mkdtemp()) / 'simulacoes.csv'
        saida = StringIO()

        call_command('simular_cenario', '--chamados', '10', '--repeticoes', '2', '--csv', str(caminho), stdout=saida)

        self.assertIn('Desvio padrão', saida.getvalue())
        linhas = caminho.read_text(encoding='utf-8-sig').splitlines()
        self.assertEqual(linhas[0], 'Indicador;Sim. 1;Sim. 2;Média;Desvio padrão')
        self.assertTrue(linhas[1].startswith('Chamados abertos;10;10;10'))

    def test_comando_recusa_em_producao(self):
        with self.assertRaises(CommandError):
            call_command('simular_cenario', stdout=StringIO())
