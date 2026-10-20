"""Atribuição de chamados: "Atribuir a mim", reatribuição e a condição de corrida de dois técnicos
clicando ao mesmo tempo."""

import threading
import time
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from chamados.models import Chamado, EventoChamado
from tests.fabricas import cliente, criar_chamado, criar_solicitante, criar_tecnico, mensagens


class AtribuirChamadoTests(TestCase):
    def setUp(self):
        self.tecnico_a = criar_tecnico()
        self.tecnico_b = criar_tecnico()
        self.chamado = criar_chamado()
        self.url = reverse('chamados:pegar', args=[self.chamado.pk])

    def test_atribui_chamado_livre(self):
        resposta = cliente(self.tecnico_a).post(self.url)

        self.chamado.refresh_from_db()
        self.assertRedirects(resposta, reverse('chamados:detail', args=[self.chamado.pk]))
        self.assertEqual(self.chamado.atendente, self.tecnico_a)
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)
        self.assertIsNotNone(self.chamado.atribuido_em)

    def test_nao_toma_chamado_de_outro_tecnico(self):
        cliente(self.tecnico_a).post(self.url)
        resposta = cliente(self.tecnico_b).post(self.url, follow=True)

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.atendente, self.tecnico_a)
        self.assertTrue(any('já foi atribuído a' in m for m in mensagens(resposta)))

    def test_pegar_de_novo_o_proprio_chamado_nao_muda_nada(self):
        cliente(self.tecnico_a).post(self.url)
        atribuido_em = Chamado.objects.get(pk=self.chamado.pk).atribuido_em

        resposta = cliente(self.tecnico_a).post(self.url, follow=True)

        self.assertIn('Este chamado já está com você.', mensagens(resposta))
        self.assertEqual(Chamado.objects.get(pk=self.chamado.pk).atribuido_em, atribuido_em)

    def test_reatribuir_registra_evento_e_mantem_primeira_atribuicao(self):
        cliente(self.tecnico_a).post(self.url)
        primeira = Chamado.objects.get(pk=self.chamado.pk).atribuido_em

        cliente(self.tecnico_a).post(
            reverse('chamados:reatribuir', args=[self.chamado.pk]), {'atendente': self.tecnico_b.pk}
        )

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.atendente, self.tecnico_b)
        self.assertEqual(self.chamado.atribuido_em, primeira)  # tempo de atendimento conta da 1ª atribuição
        self.assertTrue(self.chamado.eventos.filter(tipo=EventoChamado.Tipo.REATRIBUICAO).exists())

    def test_reatribuir_para_solicitante_e_recusado(self):
        resposta = cliente(self.tecnico_a).post(
            reverse('chamados:reatribuir', args=[self.chamado.pk]), {'atendente': criar_solicitante().pk}, follow=True
        )

        self.chamado.refresh_from_db()
        self.assertIsNone(self.chamado.atendente)
        self.assertIn('Selecione um técnico válido para reatribuir o chamado.', mensagens(resposta))


class AtribuirChamadoConcorrenciaTests(TransactionTestCase):
    """Condição de corrida: dois técnicos clicam "Atribuir a mim" ao mesmo tempo. Cada requisição roda
    numa thread com a sua própria conexão ao PostgreSQL, e um atraso dentro do save() alarga a janela
    entre "ler" e "salvar". Com a trava de linha (select_for_update), só uma pode atribuir; a outra
    espera e é recusada, sem sobrescrever o técnico."""

    def test_cliques_simultaneos_so_um_tecnico_atribui(self):
        tecnicos = [criar_tecnico(), criar_tecnico()]
        chamado = criar_chamado()
        url = reverse('chamados:pegar', args=[chamado.pk])
        url_sucesso = reverse('chamados:detail', args=[chamado.pk])
        clientes = {t.pk: cliente(t) for t in tecnicos}
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
            threads = [threading.Thread(target=clicar, args=(t,)) for t in tecnicos]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(erros, [])
        self.assertEqual(sorted(resultados.values()), ['atribuiu', 'recusado'])
        chamado.refresh_from_db()
        vencedor = next(nome for nome, resultado in resultados.items() if resultado == 'atribuiu')
        self.assertEqual(chamado.atendente.username, vencedor)
