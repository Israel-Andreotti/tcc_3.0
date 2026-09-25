from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from core.mixins import AdministradorRequiredMixin, AtendenteRequiredMixin

from .forms import (
    CategoriaForm,
    ChamadoCreateForm,
    ProcedimentoEntryForm,
    SLAPrioridadeForm,
    SubcategoriaForm,
)
from .models import Anexo, Categoria, Chamado, SLAPrioridade, Subcategoria

# Ordem de urgência (mais urgente primeiro) e descrição curta de cada prioridade,
# usadas na tela do catálogo de serviços.
PRIORIDADE_ORDEM = {'critica': 0, 'alta': 1, 'media': 2, 'baixa': 3}
PRIORIDADE_DESCRICOES = {
    'critica': 'Sistema fora do ar ou impacto crítico no atendimento',
    'alta': 'Funcionalidade essencial comprometida',
    'media': 'Impacto moderado no trabalho do solicitante',
    'baixa': 'Sem impacto imediato na operação',
}


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
            # fila de trabalho do técnico: só chamados ainda em aberto
            qs = qs.exclude(status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO])

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
        qs = Chamado.objects.select_related('solicitante', 'atendente', 'categoria', 'subcategoria').prefetch_related('anexos')
        if usuario.is_solicitante():
            return qs.filter(solicitante=usuario)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pode_gerenciar'] = self.request.user.is_authenticated and not self.request.user.is_solicitante()
        if context['pode_gerenciar']:
            context['procedimento_form'] = ProcedimentoEntryForm(initial={'tipo': 'publico'})
            context['procedimentos'] = self.object.procedimentos.select_related('autor')
            Usuario = self.request.user.__class__
            context['tecnicos'] = Usuario.objects.filter(
                perfil__in=[Usuario.Perfil.ATENDENTE, Usuario.Perfil.ADMINISTRADOR]
            ).order_by('first_name', 'username')
        else:
            context['procedimentos'] = self.object.procedimentos.filter(tipo='publico').select_related('autor')
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
        for arquivo in form.cleaned_data.get('anexos') or []:
            Anexo.objects.create(chamado=self.object, arquivo=arquivo, enviado_por=self.request.user)
        messages.success(self.request, 'Chamado aberto com sucesso.')
        return response

    def get_success_url(self):
        return reverse_lazy('chamados:detail', kwargs={'pk': self.object.pk})


class ChamadoPegarView(AtendenteRequiredMixin, View):
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        chamado.atendente = request.user
        if chamado.status == Chamado.Status.ABERTO:
            chamado.status = Chamado.Status.EM_ANDAMENTO
        chamado.save()
        messages.success(request, 'Chamado atribuído a você.')
        return redirect('chamados:detail', pk=pk)


class ProcedimentoEntryCreateView(AtendenteRequiredMixin, View):
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


class ChamadoConcluirView(AtendenteRequiredMixin, View):
    def post(self, request, pk):
        chamado = get_object_or_404(Chamado, pk=pk)
        chamado.status = Chamado.Status.RESOLVIDO
        chamado.fechado_em = timezone.now()
        chamado.save()
        messages.success(request, 'Chamado concluído.')
        return redirect('chamados:detail', pk=pk)


class ChamadoReatribuirView(AtendenteRequiredMixin, View):
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
