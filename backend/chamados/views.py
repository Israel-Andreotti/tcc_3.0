import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models, transaction
from django.db.models import (
    Case, DateTimeField, DurationField, ExpressionWrapper, F, FloatField, Func, IntegerField, ProtectedError,
    Value, When,
)
from django.db.models.functions import Coalesce, NullIf
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from ativos.models import Ativo, MovimentacaoAtivo
from core.mixins import AdministradorRequiredMixin, AtendenteRequiredMixin
from usuarios.models import Setor, Usuario

from .forms import (
    CategoriaForm,
    ChamadoCreateForm,
    ProcedimentoEntryForm,
    SLAPrioridadeForm,
    SubcategoriaForm,
)
from .models import (
    PREFIXO_CODIGO, Categoria, Chamado, EventoChamado, Prioridade, ProcedimentoEntry, SLAPrioridade, Subcategoria,
    TipoChamado, formatar_codigo,
)

# Ordem de urgência (mais urgente primeiro) e descrição curta de cada prioridade,
# usadas na tela do catálogo de serviços.
PRIORIDADE_ORDEM = {'critica': 0, 'alta': 1, 'media': 2, 'baixa': 3}
PRIORIDADE_DESCRICOES = {
    'critica': 'Sistema fora do ar ou impacto crítico no atendimento',
    'alta': 'Funcionalidade essencial comprometida',
    'media': 'Impacto moderado no trabalho do solicitante',
    'baixa': 'Sem impacto imediato na operação',
}


class ChamadoEditavelMixin:
    """Bloqueia ações em chamados já encerrados (resolvidos/fechados), mesmo via POST direto."""

    def dispatch(self, request, *args, **kwargs):
        chamado = get_object_or_404(Chamado, pk=kwargs['pk'])
        if chamado.encerrado:
            messages.error(request, 'Este chamado já foi encerrado e não pode mais ser alterado.')
            return redirect('chamados:detail', pk=chamado.pk)
        return super().dispatch(request, *args, **kwargs)


# Urgência do SLA: SLA correndo antes de pausado (aguardando o solicitante vai pro fim) e, depois,
# o prazo mais próximo — estourados ficam no topo e a prioridade entra por tabela (crítico tem
# prazo bem menor que baixa). Também é o desempate das demais ordenações.
ORDEM_URGENCIA = ('sla_pausado_ordem', F('prazo_sla').asc(nulls_last=True), 'criado_em')

# Opções do seletor "Ordenar por" da fila: chave -> (rótulo, ordenação).
ORDENACOES_CHAMADO = {
    'urgencia': ('Urgência do SLA', ORDEM_URGENCIA),
    'consumido': ('Prazo SLA (% consumido)', (F('sla_consumido').desc(nulls_last=True),) + ORDEM_URGENCIA),
    'categoria': ('Categoria', ('categoria__nome', 'subcategoria__nome') + ORDEM_URGENCIA),
    'prioridade': ('Prioridade', ('prioridade_ordem',) + ORDEM_URGENCIA),
    'recentes': ('Mais recentes', ('-criado_em',)),
    'antigos': ('Mais antigos', ('criado_em',)),
}


class Segundos(Func):
    """Duração (interval do PostgreSQL) em segundos."""

    template = 'EXTRACT(EPOCH FROM %(expressions)s)'
    output_field = FloatField()


def anotacao_sla_consumido():
    """Fração do SLA já consumida (1.0 = 100%), calculada no banco com a mesma regra de
    Chamado.sla_percentual: descontando as pausas e congelada enquanto o chamado está pausado."""
    referencia = Coalesce('sla_pausado_em', Value(timezone.now(), output_field=DateTimeField()))
    decorrido = Segundos(ExpressionWrapper(referencia - F('criado_em'), output_field=DurationField()))
    total = Segundos(ExpressionWrapper(F('prazo_sla') - F('criado_em'), output_field=DurationField()))
    pausado = Segundos(F('sla_tempo_pausado'))
    return ExpressionWrapper((decorrido - pausado) / NullIf(total - pausado, 0), output_field=FloatField())


def versao_fila():
    """Identificador do estado da fila da equipe (chamados em aberto): muda quando um chamado entra,
    sai ou é alterado (atribuído, status...). A página da fila compara periodicamente e recarrega."""
    dados = Chamado.objects.exclude(status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO]).aggregate(
        total=models.Count('pk'), ultimo=models.Max('atualizado_em'), maior_id=models.Max('pk')
    )
    ultimo = dados['ultimo'].timestamp() if dados['ultimo'] else 0
    return f"{dados['total']}-{dados['maior_id'] or 0}-{ultimo:.6f}"


def filtro_busca_chamado(termo):
    """Busca pelo título ou pelo código: aceita "INC000007", "inc7", "REQ12" ou só o número
    ("7" encontra INC000007 e REQ000007)."""
    filtro = models.Q(titulo__icontains=termo)
    codigo = re.fullmatch(r'#?\s*(INC|REQ)?\s*0*(\d+)', termo, re.IGNORECASE)
    if codigo:
        prefixo, numero = (codigo.group(1) or '').upper(), int(codigo.group(2))
        tipos = [t for t, p in PREFIXO_CODIGO.items() if not prefixo or p == prefixo]
        filtro |= models.Q(codigo__in=[formatar_codigo(t, numero) for t in tipos])
    return filtro


class ChamadoListView(LoginRequiredMixin, ListView):
    model = Chamado
    template_name = 'chamados/chamado_list.html'
    context_object_name = 'chamados'
    paginate_by = 20

    CHAVE_SESSAO_ORDEM = 'fila_chamados_ordem'

    def get_ordem(self):
        """Ordenação da fila. A escolhida pelo usuário fica guardada na sessão, para continuar valendo
        ao recarregar a página ou voltar para a fila (até o logout). Sem escolha, o padrão é urgência
        para a equipe e mais recentes para o solicitante."""
        sessao = self.request.session
        ordem = self.request.GET.get('ordem', '')
        if ordem in ORDENACOES_CHAMADO:
            if sessao.get(self.CHAVE_SESSAO_ORDEM) != ordem:
                sessao[self.CHAVE_SESSAO_ORDEM] = ordem
            return ordem
        ordem = sessao.get(self.CHAVE_SESSAO_ORDEM, '')
        if ordem in ORDENACOES_CHAMADO:
            return ordem
        return 'recentes' if self.request.user.is_solicitante() else 'urgencia'

    def get_queryset(self):
        Chamado.fechar_resolvidos_expirados()
        usuario = self.request.user
        qs = Chamado.objects.select_related(
            'solicitante', 'solicitante__setor', 'atendente', 'atendente__setor', 'categoria', 'subcategoria', 'setor'
        )
        if usuario.is_solicitante():
            qs = qs.filter(solicitante=usuario)
        else:
            # Fila de trabalho do técnico: só chamados ainda em aberto.
            qs = qs.exclude(status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO])

        qs = qs.annotate(
            sla_pausado_ordem=Case(When(sla_pausado_em__isnull=False, then=1), default=0, output_field=IntegerField()),
            prioridade_ordem=Case(
                *[When(prioridade=valor, then=posicao) for valor, posicao in PRIORIDADE_ORDEM.items()],
                default=99,
                output_field=IntegerField(),
            ),
            sla_consumido=anotacao_sla_consumido(),
        ).order_by(*ORDENACOES_CHAMADO[self.get_ordem()][1])

        termo = self.request.GET.get('q', '').strip()
        if termo:
            qs = qs.filter(filtro_busca_chamado(termo))

        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        categoria_id = self.request.GET.get('categoria', '').strip()
        if categoria_id:
            qs = qs.filter(categoria_id=categoria_id)

        tipo = self.request.GET.get('tipo', '').strip()
        if tipo in TipoChamado.values:
            qs = qs.filter(tipo=tipo)

        if not usuario.is_solicitante():
            atendente_id = self.request.GET.get('atendente', '').strip()
            if atendente_id:
                qs = qs.filter(atendente_id=atendente_id)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        usuario = self.request.user
        context['q'] = self.request.GET.get('q', '')
        context['status_selecionado'] = self.request.GET.get('status', '')
        context['categoria_selecionada'] = self.request.GET.get('categoria', '')
        context['tipo_selecionado'] = self.request.GET.get('tipo', '')
        context['tipo_choices'] = TipoChamado.choices
        context['status_choices'] = Chamado.Status.choices
        context['categorias'] = Categoria.objects.order_by('ordem', 'nome')
        context['ordem_selecionada'] = self.get_ordem()
        context['ordenacoes'] = [(chave, rotulo) for chave, (rotulo, _) in ORDENACOES_CHAMADO.items()]
        # Filtros atuais (sem a página) para os links de paginação não perderem a busca/ordem.
        parametros = self.request.GET.copy()
        parametros.pop('page', None)
        context['filtros_querystring'] = parametros.urlencode()
        if not usuario.is_solicitante():
            context['versao_fila'] = versao_fila()
        if usuario.is_solicitante():
            # Independe de filtro/paginação: alimenta o pop-up e o aviso de "precisa da sua resposta".
            context['pendencias_solicitante'] = list(
                Chamado.objects.filter(
                    solicitante=usuario,
                    status__in=[Chamado.Status.AGUARDANDO_SOLICITANTE, Chamado.Status.RESOLVIDO],
                ).order_by('sla_pausado_em')
            )
        if not usuario.is_solicitante():
            context['atendente_selecionado'] = self.request.GET.get('atendente', '')
            context['tecnicos'] = usuario.__class__.objects.filter(
                perfil__in=[usuario.Perfil.ATENDENTE, usuario.Perfil.ADMINISTRADOR]
            ).order_by('first_name', 'username')
        return context


class ChamadoHistoricoView(AtendenteRequiredMixin, ListView):
    model = Chamado
    template_name = 'chamados/chamado_historico.html'
    context_object_name = 'chamados'
    paginate_by = 20

    def get_queryset(self):
        Chamado.fechar_resolvidos_expirados()
        qs = Chamado.objects.select_related(
            'solicitante', 'solicitante__setor', 'atendente', 'atendente__setor', 'categoria', 'subcategoria'
        ).filter(
            status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO]
        ).order_by('-atualizado_em')
        termo = self.request.GET.get('q', '').strip()
        if termo:
            qs = qs.filter(
                filtro_busca_chamado(termo)
                | models.Q(descricao__icontains=termo)
                | models.Q(solicitante__username__icontains=termo)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        return context


class ChamadoDetailView(LoginRequiredMixin, DetailView):
    model = Chamado
    template_name = 'chamados/chamado_detail.html'
    context_object_name = 'chamado'

    def get_queryset(self):
        Chamado.fechar_resolvidos_expirados()
        usuario = self.request.user
        qs = Chamado.objects.select_related('solicitante', 'atendente', 'categoria', 'subcategoria')
        if usuario.is_solicitante():
            return qs.filter(solicitante=usuario)
        return qs

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # O técnico responsável abriu o chamado: a resposta do solicitante deixa de ser "nova".
        # update() direto para não mexer em atualizado_em.
        if self.object.resposta_solicitante_em and self.object.atendente_id == request.user.pk:
            Chamado.objects.filter(pk=self.object.pk).update(resposta_solicitante_em=None)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pode_gerenciar'] = self.request.user.is_authenticated and not self.request.user.is_solicitante()
        context['pode_editar'] = context['pode_gerenciar'] and not self.object.encerrado
        if context['pode_gerenciar']:
            context['procedimento_form'] = ProcedimentoEntryForm(initial={'tipo': 'publico'})
            context['procedimentos'] = self.object.procedimentos.select_related('autor')
            Usuario = self.request.user.__class__
            context['tecnicos'] = Usuario.objects.filter(
                perfil__in=[Usuario.Perfil.ATENDENTE, Usuario.Perfil.ADMINISTRADOR]
            ).order_by('first_name', 'username')
            context['movimentacoes_pendentes'] = self.object.movimentacoes_ativo.filter(
                status=MovimentacaoAtivo.Status.PENDENTE
            ).select_related('ativo', 'setor_destino', 'funcionario_destino')
            context['movimentacoes_efetivadas'] = self.object.movimentacoes_ativo.filter(
                status=MovimentacaoAtivo.Status.EFETIVADA
            ).select_related('ativo', 'setor_origem', 'setor_destino', 'funcionario_origem', 'funcionario_destino')
            context['funcionarios_atribuiveis'] = funcionarios_atribuiveis(self.object.setor)
        else:
            # Solicitante vê procedimentos públicos e as próprias respostas, nunca as notas internas.
            context['procedimentos'] = self.object.procedimentos.exclude(
                tipo=ProcedimentoEntry.Tipo.INTERNO
            ).select_related('autor')
            context['pode_responder'] = self.object.status == Chamado.Status.AGUARDANDO_SOLICITANTE
            context['pode_confirmar'] = self.object.status == Chamado.Status.RESOLVIDO
            context['pode_avaliar'] = self.object.status == Chamado.Status.FECHADO and self.object.avaliacao is None
            context['abrir_avaliacao'] = context['pode_avaliar'] and self.request.GET.get('avaliar') == '1'
            if context['pode_responder']:
                # Última orientação pública da equipe: é o que o solicitante precisa responder.
                context['pedido_tecnico'] = self.object.procedimentos.filter(
                    tipo=ProcedimentoEntry.Tipo.PUBLICO
                ).select_related('autor').last()

        # Linha do tempo: procedimentos (conteúdo) + eventos do ciclo de vida, em ordem cronológica.
        eventos = self.object.eventos.select_related('autor')
        if not context['pode_gerenciar']:
            eventos = eventos.filter(publico=True)
        context['linha_do_tempo'] = sorted(
            [('procedimento', p) for p in context['procedimentos']] + [('evento', e) for e in eventos],
            key=lambda item: item[1].criado_em,
        )
        return context


class ChamadoCreateView(LoginRequiredMixin, CreateView):
    model = Chamado
    form_class = ChamadoCreateForm
    template_name = 'chamados/chamado_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.solicitante = self.request.user
        form.instance.titulo = form.instance.subcategoria.nome
        response = super().form_valid(form)
        chamado = self.object
        descricao = f'Abriu o chamado ({chamado.get_tipo_display().lower()}) — prioridade {chamado.get_prioridade_display()}'
        if chamado.subcategoria and chamado.prioridade != chamado.subcategoria.prioridade:
            descricao += ' (elevada por setor crítico)'
        descricao += f', prazo de SLA {timezone.localtime(chamado.prazo_sla):%d/%m/%Y %H:%M}.'
        chamado.registrar_evento(EventoChamado.Tipo.ABERTURA, self.request.user, descricao)
        messages.success(self.request, 'Chamado aberto com sucesso.')
        return response

    def get_success_url(self):
        return reverse_lazy('chamados:detail', kwargs={'pk': self.object.pk})


class ChamadoPegarView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    """"Atribuir a mim": só vale para chamado sem técnico. A linha é travada (select_for_update) para
    que dois técnicos clicando ao mesmo tempo não troquem o dono um do outro; para mudar o técnico
    de propósito existe o "Reatribuir"."""

    @transaction.atomic
    def post(self, request, pk):
        # Sem select_related: se a requisição esperou a trava, o PostgreSQL relê a linha do chamado já
        # atualizada, mas os dados do técnico vindos no JOIN seriam os da leitura antiga (vazios).
        # Buscando o técnico depois (acesso a chamado.atendente), ele vem atualizado.
        chamado = get_object_or_404(Chamado.objects.select_for_update(of=('self',)), pk=pk)
        if chamado.atendente_id == request.user.pk:
            messages.info(request, 'Este chamado já está com você.')
            return redirect('chamados:detail', pk=pk)
        if chamado.atendente_id:
            nome = chamado.atendente.get_full_name() or chamado.atendente.username
            messages.error(request, f'Este chamado já foi atribuído a {nome}. A fila foi atualizada.')
            return redirect('chamados:list')
        chamado.atribuir(request.user)
        chamado.save()
        chamado.registrar_evento(EventoChamado.Tipo.ATRIBUICAO, request.user, 'Assumiu o chamado.')
        messages.success(request, 'Chamado atribuído a você.')
        return redirect('chamados:detail', pk=pk)


class ProcedimentoEntryCreateView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        form = ProcedimentoEntryForm(request.POST)
        if form.is_valid():
            entrada = form.save(commit=False)
            entrada.chamado = chamado
            entrada.autor = request.user
            entrada.save()
            if entrada.tipo == ProcedimentoEntry.Tipo.PUBLICO and chamado.primeira_resposta_em is None:
                chamado.registrar_primeira_resposta()
                chamado.save(update_fields=['primeira_resposta_em', 'atualizado_em'])
            messages.success(request, 'Procedimento registrado.')
        else:
            messages.error(request, 'Não foi possível registrar o procedimento.')
        return redirect('chamados:detail', pk=pk)


class ChamadoConcluirView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    @transaction.atomic
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        chamado.resolver()
        chamado.save()
        prazo = 'dentro do prazo de SLA' if chamado.resolvido_no_prazo else 'fora do prazo de SLA'
        chamado.registrar_evento(
            EventoChamado.Tipo.RESOLVIDO, request.user,
            f'Marcou como resolvido ({prazo}); aguardando a confirmação do solicitante.',
        )

        pendentes = chamado.movimentacoes_ativo.filter(status=MovimentacaoAtivo.Status.PENDENTE).select_related('ativo')
        efetivadas = 0
        for movimentacao in pendentes:
            movimentacao.efetivar()
            chamado.registrar_evento(
                EventoChamado.Tipo.MOVIMENTACAO, request.user,
                f'Efetivou a movimentação de {movimentacao.ativo}: {movimentacao.origem_display} → '
                f'{movimentacao.destino_display}.',
                publico=False,
            )
            efetivadas += 1

        aviso = (
            f'Chamado resolvido. Aguardando a confirmação do solicitante '
            f'(fecha automaticamente em {Chamado.prazo_confirmacao_display()}).'
        )
        if efetivadas:
            aviso += f' {efetivadas} movimentação(ões) de ativo efetivada(s).'
        messages.success(request, aviso)
        return redirect('chamados:detail', pk=pk)


class ChamadoReatribuirView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        Usuario = request.user.__class__
        tecnico_id = request.POST.get('atendente')
        tecnico = Usuario.objects.filter(
            pk=tecnico_id, perfil__in=[Usuario.Perfil.ATENDENTE, Usuario.Perfil.ADMINISTRADOR]
        ).first()
        if not tecnico:
            messages.error(request, 'Selecione um técnico válido para reatribuir o chamado.')
            return redirect('chamados:detail', pk=pk)
        anterior = chamado.atendente
        chamado.atribuir(tecnico)
        chamado.save()
        de = f'de {anterior.get_full_name() or anterior.username} ' if anterior else ''
        chamado.registrar_evento(
            EventoChamado.Tipo.REATRIBUICAO, request.user,
            f'Reatribuiu o chamado {de}para {tecnico.get_full_name() or tecnico.username}.',
        )
        messages.success(request, f'Chamado reatribuído para {tecnico}.')
        return redirect('chamados:detail', pk=pk)


class ChamadoConfirmarSolucaoView(LoginRequiredMixin, View):
    """Solicitante confirma que o problema foi resolvido: o chamado é fechado em definitivo."""

    @transaction.atomic
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk, solicitante=request.user)
        if chamado.status != Chamado.Status.RESOLVIDO:
            messages.info(request, 'Este chamado não está aguardando a sua confirmação.')
            return redirect('chamados:detail', pk=pk)
        chamado.fechar()
        chamado.save()
        chamado.registrar_evento(
            EventoChamado.Tipo.FECHADO, request.user, 'Confirmou que o problema foi resolvido; chamado fechado.'
        )
        messages.success(request, 'Obrigado! O chamado foi fechado.')
        # Abre o pop-up de avaliação na página do chamado.
        return redirect(f"{reverse('chamados:detail', kwargs={'pk': pk})}?avaliar=1")


class ChamadoAvaliarView(LoginRequiredMixin, View):
    """Avaliação do atendimento pelo solicitante (1 a 5, CSAT), depois que o chamado foi fechado.
    Opcional e uma única vez por chamado; o comentário, se houver, vai para a linha do tempo."""

    @transaction.atomic
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk, solicitante=request.user)
        if chamado.status != Chamado.Status.FECHADO or chamado.avaliacao is not None:
            messages.info(request, 'Este chamado não pode ser avaliado.')
            return redirect('chamados:detail', pk=pk)
        nota = request.POST.get('avaliacao', '')
        if nota not in {'1', '2', '3', '4', '5'}:
            messages.error(request, 'Escolha de 1 a 5 estrelas para avaliar.')
            return redirect(f"{reverse('chamados:detail', kwargs={'pk': pk})}?avaliar=1")
        chamado.avaliacao = int(nota)
        chamado.save(update_fields=['avaliacao', 'atualizado_em'])
        classificacao = Chamado.CLASSIFICACAO_AVALIACAO[int(nota)][0]
        chamado.registrar_evento(
            EventoChamado.Tipo.AVALIADO, request.user, f'Avaliou o atendimento: {nota} de 5 estrelas ({classificacao}).'
        )
        comentario = request.POST.get('comentario', '').strip()
        if comentario:
            ProcedimentoEntry.objects.create(
                chamado=chamado, autor=request.user, tipo=ProcedimentoEntry.Tipo.RESPOSTA,
                texto=f'Comentário da avaliação: {comentario}',
            )
        messages.success(request, 'Obrigado pela avaliação!')
        return redirect('chamados:detail', pk=pk)


class ChamadoReabrirView(LoginRequiredMixin, View):
    """Solicitante informa que o problema não foi resolvido: o chamado volta para o técnico
    (em andamento), o SLA é retomado e o técnico recebe o aviso de nova resposta."""

    @transaction.atomic
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk, solicitante=request.user)
        if chamado.status != Chamado.Status.RESOLVIDO:
            messages.info(request, 'Este chamado não pode mais ser reaberto.')
            return redirect('chamados:detail', pk=pk)
        motivo = request.POST.get('texto', '').strip()
        if not motivo:
            messages.error(request, 'Conte o que ainda não foi resolvido antes de reabrir.')
            return redirect('chamados:detail', pk=pk)
        ProcedimentoEntry.objects.create(
            chamado=chamado, autor=request.user, tipo=ProcedimentoEntry.Tipo.RESPOSTA,
            texto=f'Não foi resolvido: {motivo}',
        )
        chamado.reabrir()
        chamado.save()
        chamado.registrar_evento(
            EventoChamado.Tipo.REABERTO, request.user,
            f'Informou que não foi resolvido; chamado reaberto (reabertura nº {chamado.reaberturas}).',
        )
        messages.success(request, 'Chamado reaberto. O técnico vai continuar o atendimento.')
        return redirect('chamados:detail', pk=pk)


class ChamadoAguardarSolicitanteView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    """Coloca o chamado em "aguardando solicitante": exige uma mensagem pública dizendo o que
    falta (o solicitante vê) e pausa o SLA até o atendimento ser retomado."""

    @transaction.atomic
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        if chamado.status == Chamado.Status.AGUARDANDO_SOLICITANTE:
            messages.info(request, 'Este chamado já está aguardando o solicitante.')
            return redirect('chamados:detail', pk=pk)
        texto = request.POST.get('texto', '').strip()
        if not texto:
            messages.error(request, 'Descreva o que o solicitante precisa informar ou fazer.')
            return redirect('chamados:detail', pk=pk)

        ProcedimentoEntry.objects.create(
            chamado=chamado, autor=request.user, tipo=ProcedimentoEntry.Tipo.PUBLICO, texto=texto
        )
        if not chamado.atendente_id:
            chamado.atribuir(request.user)
        chamado.registrar_primeira_resposta()
        chamado.pediu_info = True
        chamado.status = Chamado.Status.AGUARDANDO_SOLICITANTE
        chamado.pausar_sla()
        chamado.save()
        chamado.registrar_evento(
            EventoChamado.Tipo.AGUARDANDO, request.user, 'Pausou o atendimento aguardando o solicitante (SLA pausado).'
        )
        messages.success(request, 'Chamado aguardando o solicitante. O SLA está pausado.')
        return redirect('chamados:detail', pk=pk)


class ChamadoRetomarView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    """Técnico retoma o atendimento sem esperar a resposta do solicitante; o SLA volta a contar."""

    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        if chamado.status != Chamado.Status.AGUARDANDO_SOLICITANTE:
            messages.info(request, 'Este chamado não está aguardando o solicitante.')
            return redirect('chamados:detail', pk=pk)
        chamado.status = Chamado.Status.EM_ANDAMENTO
        chamado.retomar_sla()
        chamado.save()
        chamado.registrar_evento(EventoChamado.Tipo.RETOMADO, request.user, 'Retomou o atendimento (SLA retomado).')
        messages.success(request, 'Atendimento retomado. O SLA voltou a contar.')
        return redirect('chamados:detail', pk=pk)


class ChamadoResponderView(LoginRequiredMixin, ChamadoEditavelMixin, View):
    """Resposta do solicitante a um chamado que aguarda informação dele: registra a resposta na
    linha do tempo, devolve o chamado para "em andamento" e retoma o SLA."""

    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk, solicitante=request.user)
        if chamado.status != Chamado.Status.AGUARDANDO_SOLICITANTE:
            messages.info(request, 'Este chamado não está aguardando uma resposta sua.')
            return redirect('chamados:detail', pk=pk)
        texto = request.POST.get('texto', '').strip()
        if not texto:
            messages.error(request, 'Escreva sua resposta antes de enviar.')
            return redirect('chamados:detail', pk=pk)

        with transaction.atomic():
            ProcedimentoEntry.objects.create(
                chamado=chamado, autor=request.user, tipo=ProcedimentoEntry.Tipo.RESPOSTA, texto=texto
            )
            chamado.status = Chamado.Status.EM_ANDAMENTO
            chamado.retomar_sla()
            chamado.resposta_solicitante_em = timezone.now()  # notifica o técnico responsável
            chamado.save()
            chamado.registrar_evento(
                EventoChamado.Tipo.RESPONDIDO, request.user, 'Respondeu; o chamado voltou para atendimento (SLA retomado).'
            )
        messages.success(request, 'Resposta enviada. O chamado voltou para atendimento.')
        return redirect('chamados:detail', pk=pk)


def validar_movimentacao_ativo(chamado, patrimonio, funcionario_id=None):
    """Regra única da movimentação via chamado, usada tanto na verificação ao vivo quanto no registro.

    Com funcionário informado: ativo disponível na TI -> atribuído ao funcionário (ex.: notebook, celular).
    Sem funcionário:
    - ativo lotado na TI -> entrada no setor do chamado.
    - ativo lotado no setor do chamado, ou atribuído a um funcionário -> devolvido à TI.
    Retorna (ativo, setor_destino, funcionario_destino, erro); `erro` é None quando é permitida."""
    if not patrimonio:
        return None, None, None, 'Informe o número de patrimônio do ativo.'

    ativo = Ativo.objects.select_related('setor', 'funcionario').filter(patrimonio__iexact=patrimonio).first()
    if not ativo:
        return None, None, None, f'Nenhum ativo encontrado com o patrimônio "{patrimonio}".'

    if ativo.tem_movimentacao_pendente:
        return ativo, None, None, f'O ativo "{ativo}" já tem uma movimentação pendente aguardando conclusão de chamado.'

    setor_ti = Setor.objects.filter(nome='TI').first()
    if not setor_ti:
        return ativo, None, None, 'Setor "TI" não está cadastrado no sistema.'

    if ativo.funcionario_id:
        lotacao = f'atribuído a {ativo.funcionario.get_full_name() or ativo.funcionario.username}'
    elif ativo.setor_id:
        lotacao = f'lotado em {ativo.setor}'
    else:
        lotacao = 'sem lotação'

    if funcionario_id:
        funcionario = (
            funcionarios_atribuiveis(chamado.setor).filter(pk=funcionario_id).first()
            if str(funcionario_id).isdigit() else None
        )
        if not funcionario:
            return ativo, None, None, f'Selecione na lista um funcionário lotado em {chamado.setor}.'
        if ativo.funcionario_id or ativo.setor_id != setor_ti.pk:
            return ativo, None, None, (
                f'O ativo "{ativo}" está {lotacao}. Para atribuir a um funcionário, ele precisa estar '
                'disponível na TI — devolva-o à TI primeiro.'
            )
        return ativo, None, funcionario, None

    if ativo.funcionario_id:
        return ativo, setor_ti, None, None
    if ativo.setor_id == chamado.setor_id:
        return ativo, setor_ti, None, None
    if ativo.setor_id == setor_ti.pk:
        return ativo, chamado.setor, None, None
    return ativo, None, None, (
        f'O ativo "{ativo}" está {lotacao}, não na TI nem em {chamado.setor} — '
        'não é possível movimentar por este chamado.'
    )


def funcionarios_atribuiveis(setor):
    """Usuários que podem receber um ativo atribuído por um chamado: só os lotados no setor do
    chamado (ativos e visíveis no sistema)."""
    return Usuario.objects.filter(setor=setor, is_active=True, super_admin=False).order_by(
        'first_name', 'last_name', 'username'
    )


def destino_display(setor, funcionario):
    if funcionario:
        return f'{funcionario.get_full_name() or funcionario.username} (funcionário)'
    return str(setor)


class ChamadoFilaVersaoView(AtendenteRequiredMixin, View):
    """JSON consultado pela página da fila para saber se precisa recarregar."""

    def get(self, request):
        Chamado.fechar_resolvidos_expirados()
        return JsonResponse({'versao': versao_fila()})


class ChamadoNotificacoesView(AtendenteRequiredMixin, View):
    """JSON consultado periodicamente pelo navegador do técnico (base.html) para avisar, sem
    recarregar a página, quando um solicitante respondeu um chamado dele."""

    def get(self, request):
        chamados = Chamado.respostas_nao_vistas(request.user).select_related('solicitante').order_by(
            '-resposta_solicitante_em'
        )
        return JsonResponse({
            'total': len(chamados),
            'itens': [
                {
                    'id': ch.pk,
                    'codigo': ch.codigo,
                    'titulo': ch.titulo,
                    'solicitante': ch.solicitante.get_full_name() or ch.solicitante.username,
                    'em': ch.resposta_solicitante_em.isoformat(),
                    'url': reverse('chamados:detail', kwargs={'pk': ch.pk}),
                }
                for ch in chamados[:10]
            ],
        })


class ChamadoVerificarAtivoView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    """Verificação ao vivo (JSON) do patrimônio digitado, antes de registrar a movimentação."""

    def get(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        ativo, setor, funcionario, erro = validar_movimentacao_ativo(
            chamado, request.GET.get('patrimonio', '').strip(), request.GET.get('funcionario', '').strip()
        )
        if erro:
            return JsonResponse({'ok': False, 'mensagem': erro})
        if ativo.funcionario_id:
            # Devolução: deixa claro que o vínculo com a pessoa será desfeito.
            nome = ativo.funcionario.get_full_name() or ativo.funcionario.username
            mensagem = f'{ativo} será desatribuído de {nome} e devolvido à {setor}.'
        else:
            mensagem = f'{ativo} — {ativo.lotacao_display} → {destino_display(setor, funcionario)}.'
        return JsonResponse({'ok': True, 'mensagem': f'{mensagem} Será efetivada ao concluir o chamado.'})


class ChamadoMovimentarAtivoView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    """Registra a movimentação como PENDENTE a partir só do número de patrimônio (regra em
    validar_movimentacao_ativo). Nada muda de fato até o chamado ser concluído (ver ChamadoConcluirView)."""

    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        ativo, setor, funcionario, erro = validar_movimentacao_ativo(
            chamado, request.POST.get('patrimonio', '').strip(), request.POST.get('funcionario', '').strip()
        )
        if erro:
            messages.error(request, erro)
            return redirect('chamados:detail', pk=pk)

        MovimentacaoAtivo.objects.create(
            ativo=ativo,
            chamado=chamado,
            setor_origem=ativo.setor,
            funcionario_origem=ativo.funcionario,
            setor_destino=setor,
            funcionario_destino=funcionario,
            realizado_por=request.user,
            status=MovimentacaoAtivo.Status.PENDENTE,
        )
        desatribuir = ''
        if ativo.funcionario_id:
            desatribuir = f' (será desatribuído de {ativo.funcionario.get_full_name() or ativo.funcionario.username})'
        chamado.registrar_evento(
            EventoChamado.Tipo.MOVIMENTACAO, request.user,
            f'Registrou a movimentação de {ativo} para {destino_display(setor, funcionario)} (pendente até a conclusão).',
            publico=False,
        )
        messages.success(
            request,
            f'Movimentação de "{ativo}" para {destino_display(setor, funcionario)}{desatribuir} registrada como '
            'pendente — só será efetivada quando este chamado for concluído.',
        )
        return redirect('chamados:detail', pk=pk)


class CatalogoServicosView(AtendenteRequiredMixin, ListView):
    model = Categoria
    template_name = 'chamados/catalogo_list.html'
    context_object_name = 'categorias'

    def get_queryset(self):
        return Categoria.objects.prefetch_related('subcategorias').order_by('ordem', 'nome')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slas = sorted(SLAPrioridade.objects.all(), key=lambda sla: PRIORIDADE_ORDEM.get(sla.prioridade, 99))
        for sla in slas:
            sla.descricao = PRIORIDADE_DESCRICOES.get(sla.prioridade, '')
        context['slas'] = slas
        return context


class SLAEditarView(AdministradorRequiredMixin, UpdateView):
    model = SLAPrioridade
    form_class = SLAPrioridadeForm
    template_name = 'chamados/sla_form.html'
    success_url = reverse_lazy('chamados:catalogo')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'SLA de {self.object.get_prioridade_display()} atualizado para {self.object.horas}h.')
        return response


class CategoriaCadastroView(AdministradorRequiredMixin, CreateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'chamados/categoria_form.html'

    def form_valid(self, form):
        # A ordem não é mais editável na tela: categoria nova entra no fim do catálogo.
        maior_ordem = Categoria.objects.aggregate(maior=models.Max('ordem'))['maior']
        form.instance.ordem = 0 if maior_ordem is None else maior_ordem + 1
        response = super().form_valid(form)
        messages.success(self.request, f'Categoria "{self.object}" cadastrada. Agora adicione as subcategorias.')
        return response

    def get_success_url(self):
        return reverse('chamados:categoria_editar', kwargs={'pk': self.object.pk})


class CategoriaEditarView(AdministradorRequiredMixin, UpdateView):
    """Edição de uma categoria do catálogo: nome e subcategorias (adicionar, excluir e trocar a
    prioridade) — tudo concentrado aqui, fora da listagem do catálogo."""

    model = Categoria
    form_class = CategoriaForm
    template_name = 'chamados/categoria_editar.html'
    context_object_name = 'categoria'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['subcategorias'] = self.object.subcategorias.order_by('nome')
        context['prioridade_choices'] = Prioridade.choices
        context['tipo_choices'] = TipoChamado.choices
        context.setdefault('subcategoria_form', SubcategoriaForm(categoria=self.object))
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Categoria "{self.object}" atualizada.')
        return response

    def get_success_url(self):
        return reverse('chamados:categoria_editar', kwargs={'pk': self.object.pk})


class SubcategoriaAdicionarView(AdministradorRequiredMixin, View):
    def post(self, request, pk):
        categoria = get_object_or_404(Categoria, pk=pk)
        form = SubcategoriaForm(request.POST, categoria=categoria)
        if form.is_valid():
            subcategoria = form.save()
            messages.success(request, f'Subcategoria "{subcategoria.nome}" adicionada.')
            return redirect('chamados:categoria_editar', pk=pk)
        # Volta para a tela de edição mostrando os erros e mantendo o que foi digitado.
        return render(request, CategoriaEditarView.template_name, {
            'categoria': categoria,
            'object': categoria,
            'form': CategoriaForm(instance=categoria),
            'subcategorias': categoria.subcategorias.order_by('nome'),
            'prioridade_choices': Prioridade.choices,
            'tipo_choices': TipoChamado.choices,
            'subcategoria_form': form,
        })


class SubcategoriaPrioridadeView(AdministradorRequiredMixin, View):
    """Troca a prioridade padrão de uma subcategoria. Vale para os chamados abertos a partir de
    agora; os já abertos mantêm a prioridade e o SLA com que foram abertos."""

    def post(self, request, pk):
        subcategoria = get_object_or_404(Subcategoria, pk=pk)
        prioridade = request.POST.get('prioridade', '')
        if prioridade not in Prioridade.values:
            messages.error(request, 'Prioridade inválida.')
        elif prioridade != subcategoria.prioridade:
            subcategoria.prioridade = prioridade
            subcategoria.save(update_fields=['prioridade'])
            messages.success(
                request,
                f'Prioridade de "{subcategoria.nome}" alterada para {subcategoria.get_prioridade_display()} '
                '(vale para os próximos chamados).',
            )
        return redirect('chamados:categoria_editar', pk=subcategoria.categoria_id)


class SubcategoriaTipoView(AdministradorRequiredMixin, View):
    """Troca o tipo (incidente/requisição) de uma subcategoria. Vale para os chamados abertos a
    partir de agora; os já abertos mantêm o tipo com que foram abertos."""

    def post(self, request, pk):
        subcategoria = get_object_or_404(Subcategoria, pk=pk)
        tipo = request.POST.get('tipo', '')
        if tipo not in TipoChamado.values:
            messages.error(request, 'Tipo inválido.')
        elif tipo != subcategoria.tipo:
            subcategoria.tipo = tipo
            subcategoria.save(update_fields=['tipo'])
            messages.success(
                request,
                f'"{subcategoria.nome}" agora é {subcategoria.get_tipo_display().lower()} (vale para os próximos chamados).',
            )
        return redirect('chamados:categoria_editar', pk=subcategoria.categoria_id)


class SubcategoriaExcluirView(AdministradorRequiredMixin, View):
    def post(self, request, pk):
        subcategoria = get_object_or_404(Subcategoria, pk=pk)
        nome = subcategoria.nome
        try:
            subcategoria.delete()
            messages.success(request, f'Subcategoria "{nome}" excluída.')
        except ProtectedError:
            messages.error(
                request,
                f'Não é possível excluir "{nome}": existem chamados vinculados a ela.',
            )
        return redirect('chamados:categoria_editar', pk=subcategoria.categoria_id)
