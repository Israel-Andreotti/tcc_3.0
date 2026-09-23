from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from core.mixins import AtendenteRequiredMixin

from .forms import ChamadoCreateForm, ChamadoGerenciarForm, ProcedimentoEntryForm
from .models import Anexo, Chamado


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
            return qs.filter(solicitante=usuario)
        # fila de trabalho do técnico: só chamados ainda em aberto
        return qs.exclude(status__in=[Chamado.Status.RESOLVIDO, Chamado.Status.FECHADO])


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


class ChamadoGerenciarView(AtendenteRequiredMixin, UpdateView):
    model = Chamado
    form_class = ChamadoGerenciarForm
    template_name = 'chamados/chamado_gerenciar.html'

    def form_valid(self, form):
        messages.success(self.request, 'Chamado atualizado.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('chamados:detail', kwargs={'pk': self.object.pk})
