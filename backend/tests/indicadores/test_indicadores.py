"""Indicadores de gestão: fórmulas conferidas contra um cenário de resultado conhecido, filtros e
acesso por perfil.

Cenário (todos abertos ao mesmo tempo, `base`, dentro do período; horas relativas a `base`):

    chamado  atribuído  1ª resposta  fechado  no prazo  reaberturas  pediu info  avaliação
    c1       +1h        +1h          +4h      sim       0            não         5
    c2       +1h        +3h          +6h      sim       1            não         4
    c3       +2h        +2h          +8h      sim       0            sim         2
    c4       +1h        +2h          +10h     não       0            não         —
    c5       (aberto, sem técnico, SLA estourado)
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chamados.models import Chamado
from indicadores.metricas import Filtros, visao_executiva, visao_operacional
from tests.fabricas import cliente, criar_admin, criar_chamado, criar_solicitante, criar_subcategoria, criar_tecnico


class CenarioIndicadores(TestCase):
    def setUp(self):
        Chamado.objects.all().delete()  # o banco de teste vem com chamados de demonstração
        self.tecnico = criar_tecnico()
        self.subcategoria = criar_subcategoria(tipo='incidente')
        base = timezone.now() - timedelta(days=1)
        h = lambda horas: base + timedelta(hours=horas)  # noqa: E731
        linhas = [
            (1, 1, 4, True, 0, False, 5),
            (1, 3, 6, True, 1, False, 4),
            (2, 2, 8, True, 0, True, 2),
            (1, 2, 10, False, 0, False, None),
        ]
        for atribuido, resposta, fechado, no_prazo, reaberturas, pediu_info, avaliacao in linhas:
            chamado = criar_chamado(subcategoria=self.subcategoria)
            Chamado.objects.filter(pk=chamado.pk).update(
                status=Chamado.Status.FECHADO, atendente=self.tecnico, criado_em=base,
                atribuido_em=h(atribuido), primeira_resposta_em=h(resposta), fechado_em=h(fechado),
                fechado_no_prazo=no_prazo, reaberturas=reaberturas, pediu_info=pediu_info, avaliacao=avaliacao,
            )
        self.aberto = criar_chamado(subcategoria=self.subcategoria)
        Chamado.objects.filter(pk=self.aberto.pk).update(criado_em=base, prazo_sla=h(1))

    def filtros(self, **params):
        return Filtros.do_request(params)


class VisaoExecutivaTests(CenarioIndicadores):
    def test_volume(self):
        dados = visao_executiva(self.filtros())

        self.assertEqual(dados['total_chamados'], 5)
        self.assertEqual(dados['total_fechados'], 4)

    def test_nivel_de_servico(self):
        self.assertEqual(visao_executiva(self.filtros())['nivel_servico'], 75.0)  # 3 de 4 no prazo

    def test_taxa_de_reabertura(self):
        self.assertEqual(visao_executiva(self.filtros())['reabertura'], 25.0)  # 1 de 4

    def test_resolucao_no_primeiro_contato(self):
        self.assertEqual(visao_executiva(self.filtros())['primeiro_contato'], 50.0)  # c1 e c4

    def test_tempos_medios(self):
        dados = visao_executiva(self.filtros())

        self.assertEqual(dados['ftr'], timedelta(hours=2))  # (1+3+2+2)/4
        self.assertEqual(dados['tempo_atendimento'], timedelta(hours=5.75))  # (3+5+6+9)/4
        self.assertEqual(dados['tempo_resolucao'], timedelta(hours=7))  # (4+6+8+10)/4

    def test_csat_e_grupos_de_satisfacao(self):
        dados = visao_executiva(self.filtros())

        self.assertEqual(dados['csat'], 66.7)  # notas 5 e 4 de 3 avaliações
        self.assertAlmostEqual(dados['csat_media'], 11 / 3)
        self.assertEqual(dados['csat_base'], 3)
        grupos = {g['grupo']: g['total'] for g in dados['satisfacao_grupos']}
        self.assertEqual(grupos, {'Satisfeitos': 2, 'Neutros': 0, 'Insatisfeitos': 1})

    def test_desempenho_por_tecnico(self):
        linha = visao_executiva(self.filtros())['por_tecnico'][0]

        self.assertEqual(linha['fechados'], 4)
        self.assertEqual(linha['nivel_servico'], 75.0)
        self.assertEqual(linha['reabertura'], 25.0)

    def test_filtro_por_tipo_e_por_tecnico(self):
        self.assertEqual(visao_executiva(self.filtros(tipo='requisicao'))['total_chamados'], 0)
        self.assertEqual(visao_executiva(self.filtros(tecnico=criar_tecnico().pk))['total_fechados'], 0)
        self.assertEqual(visao_executiva(self.filtros(tecnico=self.tecnico.pk))['total_fechados'], 4)

    def test_chamado_fora_do_periodo_nao_entra(self):
        antigo = criar_chamado(subcategoria=self.subcategoria)
        ha_60_dias = timezone.now() - timedelta(days=60)
        Chamado.objects.filter(pk=antigo.pk).update(
            criado_em=ha_60_dias, fechado_em=ha_60_dias, status=Chamado.Status.FECHADO, fechado_no_prazo=False,
        )

        self.assertEqual(visao_executiva(self.filtros(periodo='30'))['total_fechados'], 4)
        self.assertEqual(visao_executiva(self.filtros(periodo='90'))['total_fechados'], 5)

    def test_sem_dados_nao_divide_por_zero(self):
        Chamado.objects.all().delete()
        dados = visao_executiva(self.filtros())

        self.assertIsNone(dados['nivel_servico'])
        self.assertIsNone(dados['csat'])
        self.assertIsNone(dados['tempo_resolucao'])


class VisaoOperacionalTests(CenarioIndicadores):
    def test_fila_agora(self):
        dados = visao_operacional(self.filtros())

        self.assertEqual(dados['em_aberto'], 1)
        self.assertEqual(dados['sem_atribuicao'], 1)
        self.assertEqual(dados['estourados'], 1)
        self.assertEqual([c.pk for c in dados['fila_sem_atribuicao']], [self.aberto.pk])

    def test_carga_e_travados_por_tecnico(self):
        Chamado.objects.filter(pk=self.aberto.pk).update(
            atendente=self.tecnico, status=Chamado.Status.EM_ANDAMENTO,
            atualizado_em=timezone.now() - timedelta(hours=30),
        )
        dados = visao_operacional(self.filtros())

        linha = dados['por_tecnico'][0]
        self.assertEqual((linha['total'], linha['estourados'], linha['parados']), (1, 1, 1))
        self.assertEqual([c.pk for c in dados['travados']], [self.aberto.pk])


class FiltrosTests(TestCase):
    def test_periodos(self):
        self.assertEqual(Filtros.do_request({}).periodo, '30')
        self.assertEqual(Filtros.do_request({'periodo': '7'}).dias, 6)
        self.assertEqual(Filtros.do_request({'periodo': 'xyz'}).periodo, '30')

    def test_periodo_personalizado(self):
        filtros = Filtros.do_request({'periodo': 'personalizado', 'de': '2026-10-01', 'ate': '2026-10-15'})

        self.assertEqual((filtros.inicio.date().isoformat(), filtros.fim.date().isoformat()), ('2026-10-01', '2026-10-15'))

    def test_datas_invertidas_ou_invalidas_voltam_ao_padrao(self):
        self.assertEqual(Filtros.do_request({'periodo': 'personalizado', 'de': '2026-10-15', 'ate': '2026-10-01'}).periodo, '30')
        self.assertEqual(Filtros.do_request({'periodo': 'personalizado', 'de': 'ontem'}).periodo, '30')

    def test_valores_invalidos_sao_ignorados(self):
        filtros = Filtros.do_request({'tecnico': 'abc', 'tipo': 'problema'})

        self.assertIsNone(filtros.tecnico_id)
        self.assertIsNone(filtros.tipo)


class AcessoAoPainelTests(TestCase):
    URL = reverse('indicadores:painel')

    def test_administrador_ve_as_duas_visoes(self):
        c = cliente(criar_admin())

        self.assertEqual(c.get(self.URL).context['visao'], 'executiva')
        self.assertEqual(c.get(self.URL, {'visao': 'operacional'}).context['visao'], 'operacional')

    def test_tecnico_so_ve_a_operacional(self):
        resposta = cliente(criar_tecnico()).get(self.URL, {'visao': 'executiva'})

        self.assertEqual(resposta.context['visao'], 'operacional')
        self.assertFalse(resposta.context['pode_ver_executiva'])

    def test_solicitante_sem_acesso(self):
        self.assertEqual(cliente(criar_solicitante()).get(self.URL).status_code, 403)
