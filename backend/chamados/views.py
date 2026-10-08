from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models, transaction
from django.db.models import Case, F, IntegerField, ProtectedError, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
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
from .models import Categoria, Chamado, ProcedimentoEntry, SLAPrioridade, Subcategoria

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


class ChamadoListView(LoginRequiredMixin, ListView):
    model = Chamado
    template_name = 'chamados/chamado_list.html'
    context_object_name = 'chamados'
    paginate_by = 20

    def get_queryset(self):
        usuario = self.request.user
        qs = Chamado.objects.select_related(
            'solicitante', 'solicitante__setor', 'atendente', 'atendente__setor', 'categoria', 'subcategoria'
        )
        if usuario.is_solicitante():
            qs = qs.filter(solicitante=usuario)
        else:
            # Fila de trabalho do técnico: só chamados ainda em aberto, por urgência:
            # 1. SLA correndo antes de SLA pausado (aguardando o solicitante vai pro fim);
            # 2. prazo de SLA mais próximo primeiro — estourados já ficam no topo, e a prioridade
            #    entra por tabela (crítico tem prazo bem menor que baixa).
            qs = qs.exclude(status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO]).annotate(
                sla_pausado_ordem=Case(When(sla_pausado_em__isnull=False, then=1), default=0, output_field=IntegerField())
            ).order_by('sla_pausado_ordem', F('prazo_sla').asc(nulls_last=True), 'criado_em')

        termo = self.request.GET.get('q', '').strip()
        if termo:
            termo_id = termo.lstrip('#')
            filtro = models.Q(titulo__icontains=termo)
            if termo_id.isdigit():
                filtro |= models.Q(pk=int(termo_id))
            qs = qs.filter(filtro)

        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        categoria_id = self.request.GET.get('categoria', '').strip()
        if categoria_id:
            qs = qs.filter(categoria_id=categoria_id)

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
        context['status_choices'] = Chamado.Status.choices
        context['categorias'] = Categoria.objects.order_by('ordem', 'nome')
        if usuario.is_solicitante():
            # Independe de filtro/paginação: alimenta o pop-up e o aviso de "precisa da sua resposta".
            context['aguardando_resposta'] = list(
                Chamado.objects.filter(solicitante=usuario, status=Chamado.Status.AGUARDANDO_SOLICITANTE)
                .select_related('subcategoria')
                .order_by('sla_pausado_em')
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
        qs = Chamado.objects.select_related(
            'solicitante', 'solicitante__setor', 'atendente', 'atendente__setor', 'categoria', 'subcategoria'
        ).filter(
            status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO]
        ).order_by('-atualizado_em')
        termo = self.request.GET.get('q', '').strip()
        if termo:
            qs = qs.filter(
                models.Q(titulo__icontains=termo)
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
            if context['pode_responder']:
                # Última orientação pública da equipe: é o que o solicitante precisa responder.
                context['pedido_tecnico'] = self.object.procedimentos.filter(
                    tipo=ProcedimentoEntry.Tipo.PUBLICO
                ).select_related('autor').last()
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
        messages.success(self.request, 'Chamado aberto com sucesso.')
        return response

    def get_success_url(self):
        return reverse_lazy('chamados:detail', kwargs={'pk': self.object.pk})


class ChamadoPegarView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        chamado.atendente = request.user
        if chamado.status == Chamado.Status.ABERTO:
            chamado.status = Chamado.Status.EM_ANDAMENTO
        chamado.save()
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
            messages.success(request, 'Procedimento registrado.')
        else:
            messages.error(request, 'Não foi possível registrar o procedimento.')
        return redirect('chamados:detail', pk=pk)


class ChamadoConcluirView(AtendenteRequiredMixin, ChamadoEditavelMixin, View):
    @transaction.atomic
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        chamado.retomar_sla()  # se estava aguardando o solicitante, contabiliza a pausa até agora
        chamado.status = Chamado.Status.RESOLVIDO
        chamado.fechado_em = timezone.now()
        chamado.save()

        pendentes = chamado.movimentacoes_ativo.filter(status=MovimentacaoAtivo.Status.PENDENTE).select_related('ativo')
        efetivadas = 0
        for movimentacao in pendentes:
            movimentacao.efetivar()
            efetivadas += 1

        if efetivadas:
            messages.success(request, f'Chamado concluído. {efetivadas} movimentação(ões) de ativo efetivada(s).')
        else:
            messages.success(request, 'Chamado concluído.')
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
        chamado.atendente = tecnico
        if chamado.status == Chamado.Status.ABERTO:
            chamado.status = Chamado.Status.EM_ANDAMENTO
        chamado.save()
        messages.success(request, f'Chamado reatribuído para {tecnico}.')
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
            chamado.atendente = request.user
        chamado.status = Chamado.Status.AGUARDANDO_SOLICITANTE
        chamado.pausar_sla()
        chamado.save()
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
    success_url = reverse_lazy('chamados:catalogo')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Categoria "{self.object}" cadastrada.')
        return response


class SubcategoriaCadastroView(AdministradorRequiredMixin, CreateView):
    model = Subcategoria
    form_class = SubcategoriaForm
    template_name = 'chamados/subcategoria_form.html'
    success_url = reverse_lazy('chamados:catalogo')

    def get_initial(self):
        initial = super().get_initial()
        categoria_id = self.request.GET.get('categoria')
        if categoria_id:
            initial['categoria'] = categoria_id
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Subcategoria "{self.object.nome}" cadastrada.')
        return response


class CategoriaExcluirView(AdministradorRequiredMixin, View):
    def post(self, request, pk):
        categoria = get_object_or_404(Categoria, pk=pk)
        nome = str(categoria)
        try:
            categoria.delete()
            messages.success(request, f'Categoria "{nome}" excluída.')
        except ProtectedError:
            messages.error(
                request,
                f'Não é possível excluir "{nome}": existem subcategorias ou chamados vinculados a ela.',
            )
        return redirect('chamados:catalogo')


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
        return redirect('chamados:catalogo')
