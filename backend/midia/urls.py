from django.urls import path

from . import views

app_name = 'midia'

urlpatterns = [
    path('imagens/', views.ImagemUploadView.as_view(), name='imagem_upload'),
    path('imagens/<uuid:pk>/', views.ImagemDetalheView.as_view(), name='imagem_detalhe'),
]
