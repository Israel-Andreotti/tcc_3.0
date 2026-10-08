from django.urls import path

from . import views

app_name = 'chamados'

urlpatterns = [
    path('', views.ChamadoListView.as_view(), name='list'),
    path('historico/', views.ChamadoHistoricoView.as_view(), name='historico'),
    path('notificacoes/', views.ChamadoNotificacoesView.as_view(), name='notificacoes'),
    path('catalogo/', views.CatalogoServicosView.as_view(), name='catalogo'),
    path('catalogo/sla/<int:pk>/editar/', views.SLAEditarView.as_view(), name='sla_editar'),
    path('catalogo/categoria/cadastrar/', views.CategoriaCadastroView.as_view(), name='categoria_cadastrar'),
    path('catalogo/subcategoria/cadastrar/', views.SubcategoriaCadastroView.as_view(), name='subcategoria_cadastrar'),
    path('catalogo/categoria/<int:pk>/excluir/', views.CategoriaExcluirView.as_view(), name='categoria_excluir'),
    path('catalogo/subcategoria/<int:pk>/excluir/', views.SubcategoriaExcluirView.as_view(), name='subcategoria_excluir'),
    path('novo/', views.ChamadoCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ChamadoDetailView.as_view(), name='detail'),
    path('<int:pk>/pegar/', views.ChamadoPegarView.as_view(), name='pegar'),
    path('<int:pk>/procedimento/', views.ProcedimentoEntryCreateView.as_view(), name='procedimento_add'),
    path('<int:pk>/concluir/', views.ChamadoConcluirView.as_view(), name='concluir'),
    path('<int:pk>/reatribuir/', views.ChamadoReatribuirView.as_view(), name='reatribuir'),
    path('<int:pk>/aguardar-solicitante/', views.ChamadoAguardarSolicitanteView.as_view(), name='aguardar_solicitante'),
    path('<int:pk>/retomar/', views.ChamadoRetomarView.as_view(), name='retomar'),
    path('<int:pk>/responder/', views.ChamadoResponderView.as_view(), name='responder'),
    path('<int:pk>/movimentar-ativo/', views.ChamadoMovimentarAtivoView.as_view(), name='movimentar_ativo'),
    path('<int:pk>/verificar-ativo/', views.ChamadoVerificarAtivoView.as_view(), name='verificar_ativo'),
]
