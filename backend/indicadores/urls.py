from django.urls import path

from . import views

app_name = 'indicadores'

urlpatterns = [
    path('', views.PainelIndicadoresView.as_view(), name='painel'),
]
