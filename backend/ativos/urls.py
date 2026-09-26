from django.urls import path

from . import views

app_name = 'ativos'

urlpatterns = [
    path('', views.AtivoListView.as_view(), name='list'),
    path('cadastrar/', views.AtivoCadastroView.as_view(), name='cadastrar'),
    path('<int:pk>/editar/', views.AtivoEditarView.as_view(), name='editar'),
    path('<int:pk>/excluir/', views.AtivoExcluirView.as_view(), name='excluir'),
]
