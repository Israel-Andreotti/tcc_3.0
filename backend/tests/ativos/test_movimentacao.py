"""Movimentação de ativos via chamado: regras (validar_movimentacao_ativo), registro pendente e
efetivação no fechamento do chamado."""

from django.test import TestCase
from django.urls import reverse

from ativos.models import Ativo, MovimentacaoAtivo
from chamados.views import validar_movimentacao_ativo
from tests.ativos.test_ativos import criar_ativo, setor_ti
from tests.fabricas import cliente, criar_chamado, criar_setor, criar_solicitante, criar_tecnico, mensagens


class RegrasDeMovimentacaoTests(TestCase):
    """Cada caso permitido e recusado da regra única de movimentação."""

    def setUp(self):
        self.setor = criar_setor()
        self.chamado = criar_chamado(solicitante=criar_solicitante(setor=self.setor))
        self.ti = setor_ti()

    def validar(self, patrimonio, funcionario_id=None):
        return validar_movimentacao_ativo(self.chamado, patrimonio, funcionario_id)

    def test_ativo_da_ti_vai_para_o_setor_do_chamado(self):
        ativo = criar_ativo(setor=self.ti)
        _, setor, funcionario, erro = self.validar(ativo.patrimonio)

        self.assertIsNone(erro)
        self.assertEqual((setor, funcionario), (self.setor, None))

    def test_ativo_do_setor_do_chamado_volta_para_a_ti(self):
        ativo = criar_ativo(setor=self.setor)
        _, setor, _, erro = self.validar(ativo.patrimonio)

        self.assertIsNone(erro)
        self.assertEqual(setor, self.ti)

    def test_ativo_com_funcionario_e_devolvido_a_ti(self):
        ativo = criar_ativo(setor=None, funcionario=criar_solicitante())
        _, setor, funcionario, erro = self.validar(ativo.patrimonio)

        self.assertIsNone(erro)
        self.assertEqual((setor, funcionario), (self.ti, None))

    def test_atribuir_a_funcionario_do_setor(self):
        ativo = criar_ativo(setor=self.ti)
        pessoa = criar_solicitante(setor=self.setor)
        _, setor, funcionario, erro = self.validar(ativo.patrimonio, pessoa.pk)

        self.assertIsNone(erro)
        self.assertEqual((setor, funcionario), (None, pessoa))

    def test_casos_recusados(self):
        outro_setor = criar_setor()
        em_outro_setor = criar_ativo(setor=outro_setor)
        fora_da_ti = criar_ativo(setor=self.setor)
        da_ti = criar_ativo(setor=self.ti)
        pendente = criar_ativo(setor=self.ti)
        MovimentacaoAtivo.objects.create(ativo=pendente, setor_destino=self.setor, realizado_por=criar_tecnico())
        de_fora_do_setor = criar_solicitante(setor=outro_setor)
        casos = [
            ('', None, 'Informe o número de patrimônio'),
            ('999999', None, 'Nenhum ativo encontrado'),
            (em_outro_setor.patrimonio, None, 'não na TI nem em'),
            (pendente.patrimonio, None, 'movimentação pendente'),
            (fora_da_ti.patrimonio, criar_solicitante(setor=self.setor).pk, 'precisa estar disponível na TI'),
            (da_ti.patrimonio, de_fora_do_setor.pk, 'funcionário lotado em'),
            (da_ti.patrimonio, 'abc', 'funcionário lotado em'),
        ]
        for patrimonio, funcionario_id, trecho in casos:
            with self.subTest(trecho=trecho):
                _, _, _, erro = self.validar(patrimonio, funcionario_id)
                self.assertIsNotNone(erro)
                self.assertIn(trecho, erro)

    def test_sem_setor_ti_cadastrado(self):
        self.ti.ativos_lotados.update(setor=None)
        ativo = criar_ativo(setor=self.setor)
        self.ti.delete()

        _, _, _, erro = self.validar(ativo.patrimonio)
        self.assertIn('Setor "TI" não está cadastrado', erro)


class MovimentacaoViaChamadoTests(TestCase):
    def setUp(self):
        self.setor = criar_setor()
        self.tecnico = criar_tecnico()
        self.chamado = criar_chamado(solicitante=criar_solicitante(setor=self.setor))
        self.c = cliente(self.tecnico)
        self.c.post(reverse('chamados:pegar', args=[self.chamado.pk]))

    def registrar(self, ativo, funcionario=''):
        return self.c.post(
            reverse('chamados:movimentar_ativo', args=[self.chamado.pk]),
            {'patrimonio': ativo.patrimonio, 'funcionario': funcionario},
        )

    def test_verificacao_ao_vivo(self):
        ativo = criar_ativo(setor=setor_ti())
        url = reverse('chamados:verificar_ativo', args=[self.chamado.pk])

        self.assertTrue(self.c.get(url, {'patrimonio': ativo.patrimonio}).json()['ok'])
        self.assertFalse(self.c.get(url, {'patrimonio': '999999'}).json()['ok'])

    def test_registro_fica_pendente_ate_fechar_o_chamado(self):
        ativo = criar_ativo(setor=setor_ti())
        self.registrar(ativo)

        movimentacao = ativo.movimentacoes.get()
        ativo.refresh_from_db()
        self.assertEqual(movimentacao.status, MovimentacaoAtivo.Status.PENDENTE)
        self.assertEqual(ativo.setor, setor_ti())  # nada muda antes do fechamento

        self.c.post(reverse('chamados:fechar', args=[self.chamado.pk]))

        movimentacao.refresh_from_db()
        ativo.refresh_from_db()
        self.assertEqual(movimentacao.status, MovimentacaoAtivo.Status.EFETIVADA)
        self.assertEqual(ativo.setor, self.setor)
        self.assertEqual(ativo.status, Ativo.Status.EM_USO)

    def test_entrega_a_funcionario_e_devolucao_a_ti(self):
        pessoa = criar_solicitante(setor=self.setor)
        notebook = criar_ativo(setor=setor_ti())
        celular = criar_ativo(setor=None, funcionario=pessoa)
        self.registrar(notebook, funcionario=pessoa.pk)
        self.registrar(celular)

        self.c.post(reverse('chamados:fechar', args=[self.chamado.pk]))

        notebook.refresh_from_db()
        celular.refresh_from_db()
        self.assertEqual((notebook.setor, notebook.funcionario, notebook.status), (None, pessoa, Ativo.Status.EM_USO))
        self.assertEqual((celular.setor, celular.funcionario, celular.status), (setor_ti(), None, Ativo.Status.DISPONIVEL))

    def test_origem_e_recapturada_na_efetivacao(self):
        ativo = criar_ativo(setor=setor_ti())
        self.registrar(ativo)
        Ativo.objects.filter(pk=ativo.pk).update(setor=self.setor)  # lotação mudou depois do registro

        self.c.post(reverse('chamados:fechar', args=[self.chamado.pk]))

        self.assertEqual(ativo.movimentacoes.get().setor_origem, self.setor)


class MovimentacaoMensagensTests(TestCase):
    def setUp(self):
        self.setor = criar_setor()
        self.chamado = criar_chamado(solicitante=criar_solicitante(setor=self.setor))
        self.c = cliente(criar_tecnico())
        setor_ti()

    def test_registro_recusado_nao_cria_movimentacao(self):
        ativo = criar_ativo(setor=criar_setor())
        resposta = self.c.post(
            reverse('chamados:movimentar_ativo', args=[self.chamado.pk]), {'patrimonio': ativo.patrimonio}, follow=True,
        )

        self.assertFalse(ativo.movimentacoes.exists())
        self.assertTrue(any('não na TI nem em' in m for m in mensagens(resposta)))

    def test_ativo_sem_lotacao_e_recusado(self):
        ativo = criar_ativo(setor=None)
        _, _, _, erro = validar_movimentacao_ativo(self.chamado, ativo.patrimonio)

        self.assertIn('sem lotação', erro)

    def test_verificacao_avisa_que_desfaz_o_vinculo_com_a_pessoa(self):
        ativo = criar_ativo(setor=None, funcionario=criar_solicitante(first_name='Bia', last_name='Lima'))
        dados = self.c.get(
            reverse('chamados:verificar_ativo', args=[self.chamado.pk]), {'patrimonio': ativo.patrimonio},
        ).json()

        self.assertTrue(dados['ok'])
        self.assertIn('será desatribuído de Bia Lima', dados['mensagem'])
