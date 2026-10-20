"""Ativos: patrimônio automático, lotação (setor ou funcionário), edição com histórico e exclusão."""

from django.test import TestCase
from django.urls import reverse

from ativos.forms import AtivoEditarForm
from ativos.models import Ativo, MovimentacaoAtivo
from tests.fabricas import cliente, criar_admin, criar_setor, criar_solicitante, criar_tecnico, mensagens
from usuarios.models import Setor


def setor_ti():
    return Setor.objects.get_or_create(nome='TI')[0]


def criar_ativo(**campos):
    campos.setdefault('setor', setor_ti())
    return Ativo.objects.create(marca=campos.pop('marca', 'dell'), modelo=campos.pop('modelo', 'latitude'), **campos)


class AtivoModelTests(TestCase):
    def test_patrimonio_e_sequencial_com_seis_digitos(self):
        primeiro = criar_ativo()
        segundo = criar_ativo()

        self.assertRegex(primeiro.patrimonio, r'^\d{6}$')
        self.assertEqual(int(segundo.patrimonio), int(primeiro.patrimonio) + 1)

    def test_patrimonio_manual_fora_do_padrao_nao_afeta_a_sequencia(self):
        anterior = criar_ativo()
        criar_ativo(patrimonio='PAT-ANTIGO')

        self.assertEqual(int(criar_ativo().patrimonio), int(anterior.patrimonio) + 1)

    def test_marca_e_modelo_sao_normalizados(self):
        ativo = criar_ativo(marca='  lenovo ', modelo='THINKPAD')

        self.assertEqual((ativo.marca, ativo.modelo), ('Lenovo', 'Thinkpad'))

    def test_lotacao_por_extenso(self):
        funcionario = criar_solicitante(first_name='Ana', last_name='Souza')

        self.assertEqual(criar_ativo().lotacao_display, 'TI')
        self.assertEqual(criar_ativo(setor=None, funcionario=funcionario).lotacao_display, 'Ana Souza (funcionário)')
        self.assertEqual(criar_ativo(setor=None).lotacao_display, 'Sem lotação')

    def test_setor_e_funcionario_ao_mesmo_tempo_e_invalido(self):
        ativo = criar_ativo()
        form = AtivoEditarForm(instance=ativo, data={
            'marca': 'Dell', 'modelo': 'X', 'tipo': 'notebook', 'status': 'em_uso',
            'setor': setor_ti().pk, 'funcionario': criar_solicitante().pk,
        })

        self.assertFalse(form.is_valid())
        self.assertIn('ao mesmo tempo', str(form.non_field_errors()))


class AtivoTelasTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()
        self.c = cliente(self.tecnico)

    def editar(self, ativo, **dados):
        campos = {'marca': ativo.marca, 'modelo': ativo.modelo, 'tipo': ativo.tipo, 'status': ativo.status,
                  'setor': ativo.setor_id or '', 'funcionario': ativo.funcionario_id or ''}
        campos.update(dados)
        return self.c.post(reverse('ativos:editar', args=[ativo.pk]), campos, follow=True)

    def test_cadastro_entra_na_ti_como_disponivel(self):
        self.c.post(reverse('ativos:cadastrar'), {'marca': 'hp', 'modelo': 'm24', 'tipo': 'monitor'})

        ativo = Ativo.objects.get(marca='Hp', modelo='M24')
        self.assertEqual(ativo.setor, setor_ti())
        self.assertEqual(ativo.status, Ativo.Status.DISPONIVEL)

    def test_editar_lotacao_gera_movimentacao_efetivada(self):
        ativo = criar_ativo()
        destino = criar_setor()

        resposta = self.editar(ativo, setor=destino.pk)

        movimentacao = ativo.movimentacoes.get()
        self.assertEqual(movimentacao.status, MovimentacaoAtivo.Status.EFETIVADA)
        self.assertEqual((movimentacao.setor_origem, movimentacao.setor_destino), (setor_ti(), destino))
        self.assertEqual(movimentacao.realizado_por, self.tecnico)
        self.assertIsNone(movimentacao.chamado)
        self.assertTrue(any('Movimentação registrada no histórico' in m for m in mensagens(resposta)))

    def test_editar_sem_mudar_lotacao_nao_gera_movimentacao(self):
        ativo = criar_ativo()
        self.editar(ativo, status='danificado')

        self.assertFalse(ativo.movimentacoes.exists())

    def test_lotacao_bloqueada_com_movimentacao_pendente(self):
        ativo = criar_ativo()
        MovimentacaoAtivo.objects.create(ativo=ativo, setor_destino=criar_setor(), realizado_por=self.tecnico)

        resposta = self.editar(ativo, setor=criar_setor().pk)

        ativo.refresh_from_db()
        self.assertEqual(ativo.setor, setor_ti())
        self.assertContains(resposta, 'movimentação pendente')

    def test_ativo_com_historico_nao_pode_ser_excluido(self):
        ativo = criar_ativo()
        self.editar(ativo, setor=criar_setor().pk)

        resposta = cliente(criar_admin()).post(reverse('ativos:excluir', args=[ativo.pk]), follow=True)

        self.assertTrue(Ativo.objects.filter(pk=ativo.pk).exists())
        self.assertTrue(any('histórico de movimentações' in m for m in mensagens(resposta)))

    def test_ativo_sem_historico_pode_ser_excluido_pelo_admin(self):
        ativo = criar_ativo()
        cliente(criar_admin()).post(reverse('ativos:excluir', args=[ativo.pk]))

        self.assertFalse(Ativo.objects.filter(pk=ativo.pk).exists())

    def test_tecnico_nao_exclui_ativo(self):
        ativo = criar_ativo()

        self.assertEqual(self.c.post(reverse('ativos:excluir', args=[ativo.pk])).status_code, 403)
        self.assertTrue(Ativo.objects.filter(pk=ativo.pk).exists())

    def test_historico_do_ativo(self):
        ativo = criar_ativo()
        self.editar(ativo, setor=criar_setor().pk)

        resposta = self.c.get(reverse('ativos:historico', args=[ativo.pk]))

        self.assertEqual(len(resposta.context['movimentacoes']), 1)
        self.assertContains(resposta, 'Edição manual')
