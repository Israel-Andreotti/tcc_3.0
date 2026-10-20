"""Catálogo de serviços (administrador): categorias, subcategorias, prioridade e tipo."""

from django.test import TestCase
from django.urls import reverse

from chamados.models import Categoria, SLAPrioridade, Subcategoria
from tests.fabricas import cliente, criar_admin, criar_chamado, criar_subcategoria, criar_tecnico, mensagens


class CatalogoTests(TestCase):
    def setUp(self):
        self.admin = criar_admin()
        self.c = cliente(self.admin)

    def test_categoria_nova_vai_para_o_fim_e_abre_a_edicao(self):
        maior_ordem = Categoria.objects.order_by('-ordem').values_list('ordem', flat=True).first() or 0
        resposta = self.c.post(reverse('chamados:categoria_cadastrar'), {'nome': 'Telefonia móvel'})

        categoria = Categoria.objects.get(nome='Telefonia móvel')
        self.assertEqual(categoria.ordem, maior_ordem + 1)
        self.assertRedirects(resposta, reverse('chamados:categoria_editar', args=[categoria.pk]))

    def test_adiciona_subcategoria_com_tipo_e_prioridade(self):
        categoria = criar_subcategoria().categoria
        self.c.post(
            reverse('chamados:subcategoria_adicionar', args=[categoria.pk]),
            {'nome': 'Crachá de acesso', 'tipo': 'requisicao', 'prioridade': 'baixa'},
        )

        subcategoria = Subcategoria.objects.get(categoria=categoria, nome='Crachá de acesso')
        self.assertEqual((subcategoria.tipo, subcategoria.prioridade), ('requisicao', 'baixa'))

    def test_nome_repetido_na_mesma_categoria_e_recusado(self):
        existente = criar_subcategoria(nome='VPN')
        resposta = self.c.post(
            reverse('chamados:subcategoria_adicionar', args=[existente.categoria_id]),
            {'nome': 'vpn', 'tipo': 'incidente', 'prioridade': 'media'},
        )

        self.assertEqual(Subcategoria.objects.filter(categoria=existente.categoria, nome__iexact='vpn').count(), 1)
        self.assertContains(resposta, 'Já existe a subcategoria')

    def test_trocar_prioridade_e_tipo(self):
        subcategoria = criar_subcategoria(prioridade='baixa', tipo='incidente')
        self.c.post(reverse('chamados:subcategoria_prioridade', args=[subcategoria.pk]), {'prioridade': 'alta'})
        self.c.post(reverse('chamados:subcategoria_tipo', args=[subcategoria.pk]), {'tipo': 'requisicao'})

        subcategoria.refresh_from_db()
        self.assertEqual((subcategoria.prioridade, subcategoria.tipo), ('alta', 'requisicao'))

    def test_valores_invalidos_sao_recusados(self):
        subcategoria = criar_subcategoria(prioridade='baixa', tipo='incidente')
        r1 = self.c.post(reverse('chamados:subcategoria_prioridade', args=[subcategoria.pk]), {'prioridade': 'urgentissima'}, follow=True)
        r2 = self.c.post(reverse('chamados:subcategoria_tipo', args=[subcategoria.pk]), {'tipo': 'problema'}, follow=True)

        subcategoria.refresh_from_db()
        self.assertEqual((subcategoria.prioridade, subcategoria.tipo), ('baixa', 'incidente'))
        self.assertIn('Prioridade inválida.', mensagens(r1))
        self.assertIn('Tipo inválido.', mensagens(r2))

    def test_nao_exclui_subcategoria_com_chamados(self):
        subcategoria = criar_subcategoria()
        criar_chamado(subcategoria=subcategoria)

        resposta = self.c.post(reverse('chamados:subcategoria_excluir', args=[subcategoria.pk]), follow=True)

        self.assertTrue(Subcategoria.objects.filter(pk=subcategoria.pk).exists())
        self.assertTrue(any('existem chamados vinculados' in m for m in mensagens(resposta)))

    def test_exclui_subcategoria_sem_chamados(self):
        subcategoria = criar_subcategoria()
        self.c.post(reverse('chamados:subcategoria_excluir', args=[subcategoria.pk]))

        self.assertFalse(Subcategoria.objects.filter(pk=subcategoria.pk).exists())


class SLAECategoriaTests(TestCase):
    def test_admin_altera_as_horas_do_sla(self):
        sla = SLAPrioridade.objects.get(prioridade='alta')
        resposta = cliente(criar_admin()).post(reverse('chamados:sla_editar', args=[sla.pk]), {'horas': 6}, follow=True)

        sla.refresh_from_db()
        self.assertEqual(sla.horas, 6)
        self.assertEqual(str(sla), 'Alta — 6h')
        self.assertIn('SLA de Alta atualizado para 6h.', mensagens(resposta))

    def test_tecnico_nao_altera_o_sla(self):
        sla = SLAPrioridade.objects.get(prioridade='alta')
        resposta = cliente(criar_tecnico()).post(reverse('chamados:sla_editar', args=[sla.pk]), {'horas': 1})

        self.assertEqual(resposta.status_code, 403)

    def test_renomear_categoria(self):
        categoria = criar_subcategoria().categoria
        resposta = cliente(criar_admin()).post(
            reverse('chamados:categoria_editar', args=[categoria.pk]), {'nome': 'Rede e Internet'}, follow=True,
        )

        categoria.refresh_from_db()
        self.assertEqual(categoria.nome, 'Rede e Internet')
        self.assertRedirects(resposta, reverse('chamados:categoria_editar', args=[categoria.pk]))
        self.assertIn('Categoria "Rede e Internet" atualizada.', mensagens(resposta))
