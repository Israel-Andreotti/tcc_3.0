from django.views.generic import TemplateView

from chamados.models import Categoria, TipoChamado
from core.mixins import AtendenteRequiredMixin
from usuarios.models import Setor, Usuario

from .metricas import PERIODOS, Filtros, visao_executiva, visao_operacional


class PainelIndicadoresView(AtendenteRequiredMixin, TemplateView):
    """Painel de gestão: visão executiva (indicadores do período, só administradores) e operacional
    (fila agora, administradores e técnicos)."""

    template_name = 'indicadores/painel.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtros = Filtros.do_request(self.request.GET)
        pode_ver_executiva = self.request.user.is_administrador()
        if not pode_ver_executiva or self.request.GET.get('visao') == 'operacional':
            visao = 'operacional'
        else:
            visao = 'executiva'
        context.update({
            'visao': visao,
            'pode_ver_executiva': pode_ver_executiva,
            'filtros': filtros,
            'periodos': [(chave, f'Últimos {dias} dias') for chave, dias in PERIODOS.items()],
            'tecnicos': Usuario.objects.filter(
                perfil__in=[Usuario.Perfil.ATENDENTE, Usuario.Perfil.ADMINISTRADOR]
            ).order_by('first_name', 'username'),
            'setores': Setor.objects.order_by('nome'),
            'categorias': Categoria.objects.order_by('nome'),
            'tipos': TipoChamado.choices,
            'dados': visao_executiva(filtros) if visao == 'executiva' else visao_operacional(filtros),
        })
        return context
