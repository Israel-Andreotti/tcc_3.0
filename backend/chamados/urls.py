from django.urls import path

from . import views

app_name = 'chamados'

urlpatterns = [
    path('', views.ChamadoListView.as_view(), name='list'),
    path('historico/', views.ChamadoHistoricoView.as_view(), name='historico'),
    path('novo/', views.ChamadoCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ChamadoDetailView.as_view(), name='detail'),
    path('<int:pk>/pegar/', views.ChamadoPegarView.as_view(), name='pegar'),
    path('<int:pk>/procedimento/', views.ProcedimentoEntryCreateView.as_view(), name='procedimento_add'),
    path('<int:pk>/concluir/', views.ChamadoConcluirView.as_view(), name='concluir'),
    path('<int:pk>/gerenciar/', views.ChamadoGerenciarView.as_view(), name='gerenciar'),
]
