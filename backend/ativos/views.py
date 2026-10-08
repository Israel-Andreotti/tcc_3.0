from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from core.mixins import AdministradorRequiredMixin, AtendenteRequiredMixin
from usuarios.models import Setor

from .forms import AtivoCadastroForm, AtivoEditarForm
from .models import Ativo, MovimentacaoAtivo


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

    @transaction.atomic
    def form_valid(self, form):
        # Lotação como está no banco, antes da edição (form.instance já tem os valores novos).
        anterior = Ativo.objects.get(pk=self.object.pk)
        mudou_lotacao = (anterior.setor_id, anterior.funcionario_id) != (self.object.setor_id, self.object.funcionario_id)
        if mudou_lotacao and anterior.tem_movimentacao_pendente:
            form.add_error(
                None,
                'Este ativo tem uma movimentação pendente em um chamado. Conclua o chamado antes de alterar a lotação.',
            )
            return self.form_invalid(form)
        response = super().form_valid(form)
        if mudou_lotacao:
            agora = timezone.now()
            MovimentacaoAtivo.objects.create(
                ativo=self.object,
                setor_origem=anterior.setor,
                funcionario_origem=anterior.funcionario,
                setor_destino=self.object.setor,
                funcionario_destino=self.object.funcionario,
                realizado_por=self.request.user,
                status=MovimentacaoAtivo.Status.EFETIVADA,
                efetivada_em=agora,
            )
            messages.success(self.request, f'Ativo "{self.object}" atualizado. Movimentação registrada no histórico.')
        else:
            messages.success(self.request, f'Ativo "{self.object}" atualizado.')
        return response


class AtivoHistoricoView(AtendenteRequiredMixin, DetailView):
    model = Ativo
    template_name = 'ativos/ativo_historico.html'
    context_object_name = 'ativo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['movimentacoes'] = self.object.movimentacoes.select_related(
            'chamado', 'setor_origem', 'setor_destino', 'funcionario_origem', 'funcionario_destino', 'realizado_por'
        ).order_by(Coalesce('efetivada_em', 'criado_em').desc())
        return context


class AtivoExcluirView(AdministradorRequiredMixin, View):
    def post(self, request, pk):
        ativo = get_object_or_404(Ativo, pk=pk)
        nome = str(ativo)
        try:
            ativo.delete()
            messages.success(request, f'Ativo "{nome}" excluído.')
        except ProtectedError:
            messages.error(
                request,
                f'Não é possível excluir "{nome}": ele tem histórico de movimentações, que precisa ser mantido. '
                'Se o equipamento saiu de uso, altere a situação para "Danificado".',
            )
        return redirect('ativos:list')
