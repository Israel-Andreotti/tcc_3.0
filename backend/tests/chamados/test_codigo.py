"""Código de exibição do chamado (INC/REQ + número próprio de cada tipo) e a busca por ele."""

import re

from django.test import TestCase
from django.urls import reverse

from chamados.models import Chamado, formatar_codigo
from chamados.views import filtro_busca_chamado
from tests.fabricas import cliente, criar_chamado, criar_subcategoria, criar_tecnico


def numero(codigo):
    return int(codigo[3:])


class CodigoChamadoTests(TestCase):
    def test_formato_do_codigo(self):
        self.assertEqual(formatar_codigo('incidente', 7), 'INC000007')
        self.assertEqual(formatar_codigo('requisicao', 123), 'REQ000123')

    def test_prefixo_segue_o_tipo_da_subcategoria(self):
        incidente = criar_chamado(subcategoria=criar_subcategoria(tipo='incidente'))
        requisicao = criar_chamado(subcategoria=criar_subcategoria(tipo='requisicao'))

        self.assertRegex(incidente.codigo, r'^INC\d{6}$')
        self.assertRegex(requisicao.codigo, r'^REQ\d{6}$')

    def test_cada_tipo_tem_sua_propria_sequencia(self):
        sub_inc, sub_req = criar_subcategoria(tipo='incidente'), criar_subcategoria(tipo='requisicao')
        inc1 = criar_chamado(subcategoria=sub_inc)
        req1 = criar_chamado(subcategoria=sub_req)
        inc2 = criar_chamado(subcategoria=sub_inc)

        self.assertEqual(numero(inc2.codigo), numero(inc1.codigo) + 1)  # o REQ no meio não consome número de INC
        req2 = criar_chamado(subcategoria=sub_req)
        self.assertEqual(numero(req2.codigo), numero(req1.codigo) + 1)

    def test_codigo_nao_muda_ao_salvar_de_novo(self):
        chamado = criar_chamado()
        codigo = chamado.codigo
        chamado.descricao = 'editado'
        chamado.save()

        self.assertEqual(Chamado.objects.get(pk=chamado.pk).codigo, codigo)

    def test_representacao_textual_usa_o_codigo(self):
        chamado = criar_chamado()

        self.assertTrue(str(chamado).startswith(chamado.codigo))


class BuscaPorCodigoTests(TestCase):
    def setUp(self):
        self.inc = criar_chamado(subcategoria=criar_subcategoria(tipo='incidente', nome='Impressora travando'))
        self.req = criar_chamado(subcategoria=criar_subcategoria(tipo='requisicao'))

    def buscar(self, termo):
        return set(Chamado.objects.filter(filtro_busca_chamado(termo)).values_list('pk', flat=True))

    def test_codigo_completo_em_qualquer_caixa(self):
        self.assertIn(self.inc.pk, self.buscar(self.inc.codigo))
        self.assertIn(self.inc.pk, self.buscar(self.inc.codigo.lower()))

    def test_codigo_abreviado_sem_zeros(self):
        self.assertIn(self.inc.pk, self.buscar(f'inc{numero(self.inc.codigo)}'))
        self.assertIn(self.req.pk, self.buscar(f'REQ{numero(self.req.codigo)}'))

    def test_prefixo_errado_nao_encontra(self):
        self.assertNotIn(self.inc.pk, self.buscar(f'REQ{numero(self.inc.codigo)}'))

    def test_so_o_numero_busca_nos_dois_tipos(self):
        encontrados = Chamado.objects.filter(filtro_busca_chamado(str(numero(self.inc.codigo))))
        prefixos = {c.codigo[:3] for c in encontrados if numero(c.codigo) == numero(self.inc.codigo)}

        self.assertIn('INC', prefixos)

    def test_busca_pelo_titulo(self):
        self.assertIn(self.inc.pk, self.buscar('impressora'))

    def test_busca_na_fila_usa_o_codigo(self):
        resposta = cliente(criar_tecnico()).get(reverse('chamados:list'), {'q': self.inc.codigo})

        self.assertEqual([c.pk for c in resposta.context['chamados']], [self.inc.pk])
        self.assertIsNone(re.search(rf'#{self.inc.pk}\b', resposta.content.decode()))  # nunca mostra o pk
