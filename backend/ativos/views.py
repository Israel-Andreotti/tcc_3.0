from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from core.mixins import AdministradorRequiredMixin, AtendenteRequiredMixin
from usuarios.models import Setor

from .forms import AtivoCadastroForm, AtivoEditarForm
from .models import Ativo


class AtivoListView(AtendenteRequiredMixin, ListView):
    model = Ativo
    template_name = 'ativos/ativo_list.html'
    context_object_name = 'ativos'
    paginate_by = 25

    def get_queryset(self):
        qs = Ativo.objects.select_related('setor', 'funcionario').order_by('marca', 'modelo')
        termo = self.request.GET.get('q', '').strip()
        if termo:
            qs = qs.filter(
                Q(marca__icontains=termo) | Q(modelo__icontains=termo) | Q(patrimonio__icontains=termo)
            )
        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)
        tipo = self.request.GET.get('tipo', '').strip()
        if tipo:
            qs = qs.filter(tipo=tipo)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        context['status_selecionado'] = self.request.GET.get('status', '')
        context['tipo_selecionado'] = self.request.GET.get('tipo', '')
        context['status_choices'] = Ativo.Status.choices
        context['tipo_choices'] = Ativo.Tipo.choices
        return context


class AtivoCadastroView(AtendenteRequiredMixin, CreateView):
    model = Ativo
    form_class = AtivoCadastroForm
    template_name = 'ativos/ativo_form.html'
    success_url = reverse_lazy('ativos:list')

    def form_valid(self, form):
        setor_ti, _ = Setor.objects.get_or_create(nome='TI')
        form.instance.setor = setor_ti
        form.instance.status = Ativo.Status.DISPONIVEL
        response = super().form_valid(form)
        messages.success(self.request, f'Ativo "{self.object}" cadastrado e lotado na TI como disponível.')
        return response


class AtivoEditarView(AtendenteRequiredMixin, UpdateView):
    model = Ativo
    form_class = AtivoEditarForm
    template_name = 'ativos/ativo_form.html'
    success_url = reverse_lazy('ativos:list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Ativo "{self.object}" atualizado.')
        return response


class AtivoExcluirView(AdministradorRequiredMixin, View):
    def post(self, request, pk):
        ativo = get_object_or_404(Ativo, pk=pk)
        nome = str(ativo)
        ativo.delete()
        messages.success(request, f'Ativo "{nome}" excluído.')
        return redirect('ativos:list')
