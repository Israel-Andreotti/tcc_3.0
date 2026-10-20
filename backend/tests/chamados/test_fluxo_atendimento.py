"""Fluxo de atendimento ponta a ponta (integração): abertura pela tela, procedimentos, aguardar o
solicitante, resposta, retomada, notificações e o log de eventos do ciclo de vida."""

from django.test import TestCase
from django.urls import reverse

from chamados.models import Chamado, EventoChamado, ProcedimentoEntry
from tests.fabricas import cliente, criar_chamado, criar_setor, criar_solicitante, criar_subcategoria, criar_tecnico, mensagens


class AberturaTests(TestCase):
    def setUp(self):
        self.solicitante = criar_solicitante()
        self.subcategoria = criar_subcategoria(prioridade='media', tipo='requisicao')

    def abrir(self, **dados):
        campos = {
            'categoria': self.subcategoria.categoria_id, 'subcategoria': self.subcategoria.pk,
            'setor': self.solicitante.setor_id, 'descricao': 'Preciso de acesso à pasta X.',
        }
        campos.update(dados)
        return cliente(self.solicitante).post(reverse('chamados:create'), campos, follow=True)

    def test_abre_chamado_pela_tela(self):
        resposta = self.abrir()

        chamado = Chamado.objects.filter(solicitante=self.solicitante).get()
        self.assertEqual(chamado.titulo, self.subcategoria.nome)
        self.assertEqual(chamado.status, Chamado.Status.ABERTO)
        self.assertEqual(chamado.tipo, 'requisicao')
        self.assertTrue(chamado.codigo.startswith('REQ'))
        self.assertIn('Chamado aberto com sucesso.', mensagens(resposta))
        evento = chamado.eventos.get(tipo=EventoChamado.Tipo.ABERTURA)
        self.assertEqual(evento.autor, self.solicitante)
        self.assertIn('requisição', evento.descricao)

    def test_abertura_em_setor_critico_registra_prioridade_elevada(self):
        setor_critico = criar_setor(critico=True)
        self.abrir(setor=setor_critico.pk)

        chamado = Chamado.objects.filter(solicitante=self.solicitante).get()
        self.assertEqual(chamado.prioridade, 'alta')
        self.assertIn('setor crítico', chamado.eventos.get(tipo=EventoChamado.Tipo.ABERTURA).descricao)

    def test_campos_obrigatorios(self):
        resposta = self.abrir(subcategoria='', setor='')

        self.assertFalse(Chamado.objects.filter(solicitante=self.solicitante).exists())
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context['form'].errors)


class AtendimentoTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()
        self.chamado = criar_chamado()
        self.solicitante = self.chamado.solicitante
        cliente(self.tecnico).post(reverse('chamados:pegar', args=[self.chamado.pk]))

    def url(self, nome):
        return reverse(f'chamados:{nome}', args=[self.chamado.pk])

    def test_procedimento_publico_conta_como_primeira_resposta(self):
        cliente(self.tecnico).post(self.url('procedimento_add'), {'tipo': 'interno', 'texto': 'Nota da equipe'})
        self.chamado.refresh_from_db()
        self.assertIsNone(self.chamado.primeira_resposta_em)  # nota interna não é resposta ao usuário

        cliente(self.tecnico).post(self.url('procedimento_add'), {'tipo': 'publico', 'texto': 'Verificando'})
        self.chamado.refresh_from_db()
        self.assertIsNotNone(self.chamado.primeira_resposta_em)

    def test_equipe_nao_registra_resposta_em_nome_do_solicitante(self):
        resposta = cliente(self.tecnico).post(self.url('procedimento_add'), {'tipo': 'resposta', 'texto': 'x'}, follow=True)

        self.assertFalse(self.chamado.procedimentos.exists())
        self.assertIn('Não foi possível registrar o procedimento.', mensagens(resposta))

    def test_aguardar_solicitante_pausa_e_exige_mensagem(self):
        cliente(self.tecnico).post(self.url('aguardar_solicitante'), {'texto': ''})
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)

        cliente(self.tecnico).post(self.url('aguardar_solicitante'), {'texto': 'Qual o número do patrimônio?'})
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.AGUARDANDO_SOLICITANTE)
        self.assertTrue(self.chamado.sla_pausado)
        self.assertTrue(self.chamado.pediu_info)
        self.assertIsNotNone(self.chamado.primeira_resposta_em)
        self.assertTrue(self.chamado.eventos.filter(tipo=EventoChamado.Tipo.AGUARDANDO).exists())

    def test_resposta_do_solicitante_retoma_e_notifica_o_tecnico(self):
        cliente(self.tecnico).post(self.url('aguardar_solicitante'), {'texto': 'Qual o ramal?'})

        cliente(self.solicitante).post(self.url('responder'), {'texto': 'Ramal 2045'})

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)
        self.assertFalse(self.chamado.sla_pausado)
        self.assertTrue(self.chamado.procedimentos.filter(tipo=ProcedimentoEntry.Tipo.RESPOSTA, texto='Ramal 2045').exists())
        notificacoes = cliente(self.tecnico).get(reverse('chamados:notificacoes')).json()
        self.assertEqual(notificacoes['total'], 1)
        self.assertEqual(notificacoes['itens'][0]['codigo'], self.chamado.codigo)

    def test_abrir_o_chamado_marca_a_resposta_como_vista(self):
        cliente(self.tecnico).post(self.url('aguardar_solicitante'), {'texto': 'Qual o ramal?'})
        cliente(self.solicitante).post(self.url('responder'), {'texto': 'Ramal 2045'})

        cliente(criar_tecnico()).get(self.url('detail'))  # outro técnico abrir não conta
        self.assertEqual(cliente(self.tecnico).get(reverse('chamados:notificacoes')).json()['total'], 1)

        cliente(self.tecnico).get(self.url('detail'))
        self.assertEqual(cliente(self.tecnico).get(reverse('chamados:notificacoes')).json()['total'], 0)

    def test_tecnico_retoma_sem_esperar_resposta(self):
        cliente(self.tecnico).post(self.url('aguardar_solicitante'), {'texto': 'Qual o ramal?'})
        cliente(self.tecnico).post(self.url('retomar'))

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)
        self.assertTrue(self.chamado.eventos.filter(tipo=EventoChamado.Tipo.RETOMADO).exists())

    def test_responder_so_quando_aguardando(self):
        resposta = cliente(self.solicitante).post(self.url('responder'), {'texto': 'oi'}, follow=True)

        self.assertIn('Este chamado não está aguardando uma resposta sua.', mensagens(resposta))
        self.assertFalse(self.chamado.procedimentos.exists())


class LogDeEventosTests(TestCase):
    """O log do ciclo de vida registra cada mudança de estado, na ordem, com o autor."""

    def test_ciclo_completo_gera_eventos_na_ordem(self):
        tecnico = criar_tecnico()
        chamado = criar_chamado()
        solicitante = chamado.solicitante
        url = lambda nome: reverse(f'chamados:{nome}', args=[chamado.pk])  # noqa: E731

        cliente(tecnico).post(url('pegar'))
        cliente(tecnico).post(url('aguardar_solicitante'), {'texto': 'Qual o erro?'})
        cliente(solicitante).post(url('responder'), {'texto': 'Erro 809'})
        cliente(tecnico).post(url('fechar'))
        cliente(solicitante).post(url('reabrir'), {'texto': 'Voltou'})
        cliente(tecnico).post(url('fechar'))
        cliente(solicitante).post(url('avaliar'), {'avaliacao': '4'})

        T = EventoChamado.Tipo
        self.assertEqual(
            list(chamado.eventos.values_list('tipo', flat=True)),
            [T.ATRIBUICAO, T.AGUARDANDO, T.RESPONDIDO, T.FECHADO, T.REABERTO, T.FECHADO, T.AVALIADO],
        )
        self.assertEqual(chamado.eventos.get(tipo=T.ATRIBUICAO).autor, tecnico)
        self.assertEqual(chamado.eventos.get(tipo=T.REABERTO).autor, solicitante)

    def test_solicitante_nao_ve_eventos_nem_notas_internas(self):
        tecnico = criar_tecnico()
        chamado = criar_chamado()
        chamado.registrar_evento(EventoChamado.Tipo.MOVIMENTACAO, tecnico, 'Registrou movimentação secreta.', publico=False)
        ProcedimentoEntry.objects.create(chamado=chamado, autor=tecnico, tipo='interno', texto='Nota interna secreta')
        ProcedimentoEntry.objects.create(chamado=chamado, autor=tecnico, tipo='publico', texto='Procedimento visível')

        pagina_solicitante = cliente(chamado.solicitante).get(reverse('chamados:detail', args=[chamado.pk])).content.decode()
        pagina_equipe = cliente(tecnico).get(reverse('chamados:detail', args=[chamado.pk])).content.decode()

        self.assertIn('Procedimento visível', pagina_solicitante)
        self.assertNotIn('secreta', pagina_solicitante)
        self.assertIn('movimentação secreta', pagina_equipe)
        self.assertIn('Nota interna secreta', pagina_equipe)

    def test_evento_sem_autor_aparece_como_sistema(self):
        evento = criar_chamado().registrar_evento(EventoChamado.Tipo.FECHADO, None, 'Fechou automaticamente.')

        self.assertEqual(evento.autor_display, 'Sistema')


class AcoesForaDoEstadoCertoTests(TestCase):
    """Ações repetidas ou fora de hora não mudam nada e avisam o usuário."""

    def setUp(self):
        self.tecnico = criar_tecnico()
        self.chamado = criar_chamado()
        self.solicitante = self.chamado.solicitante
        cliente(self.tecnico).post(reverse('chamados:pegar', args=[self.chamado.pk]))

    def url(self, nome):
        return reverse(f'chamados:{nome}', args=[self.chamado.pk])

    def aguardar(self):
        return cliente(self.tecnico).post(self.url('aguardar_solicitante'), {'texto': 'Qual o ramal?'}, follow=True)

    def test_aguardar_duas_vezes(self):
        self.aguardar()
        resposta = self.aguardar()

        self.assertIn('Este chamado já está aguardando o solicitante.', mensagens(resposta))
        self.assertEqual(self.chamado.procedimentos.count(), 1)

    def test_aguardar_chamado_sem_tecnico_atribui_a_quem_pediu(self):
        livre = criar_chamado()
        cliente(self.tecnico).post(reverse('chamados:aguardar_solicitante', args=[livre.pk]), {'texto': 'Qual o ramal?'})

        livre.refresh_from_db()
        self.assertEqual(livre.atendente, self.tecnico)

    def test_retomar_chamado_que_nao_esta_aguardando(self):
        resposta = cliente(self.tecnico).post(self.url('retomar'), follow=True)

        self.assertIn('Este chamado não está aguardando o solicitante.', mensagens(resposta))
        self.assertFalse(self.chamado.eventos.filter(tipo=EventoChamado.Tipo.RETOMADO).exists())

    def test_resposta_vazia_do_solicitante(self):
        self.aguardar()
        resposta = cliente(self.solicitante).post(self.url('responder'), {'texto': '   '}, follow=True)

        self.chamado.refresh_from_db()
        self.assertIn('Escreva sua resposta antes de enviar.', mensagens(resposta))
        self.assertEqual(self.chamado.status, Chamado.Status.AGUARDANDO_SOLICITANTE)

    def test_solicitante_ve_o_que_o_tecnico_pediu(self):
        self.aguardar()
        resposta = cliente(self.solicitante).get(self.url('detail'))

        self.assertEqual(resposta.context['pedido_tecnico'].texto, 'Qual o ramal?')
