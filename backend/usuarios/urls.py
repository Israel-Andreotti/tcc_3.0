from django.urls import path

from . import views

app_name = 'usuarios'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('cadastrar/', views.UsuarioCadastroView.as_view(), name='cadastrar'),
    path('trocar-senha/', views.TrocarSenhaView.as_view(), name='trocar_senha'),
    path('', views.UsuarioListView.as_view(), name='list'),
    path('<int:pk>/desativar/', views.UsuarioToggleAtivoView.as_view(), name='toggle_ativo'),
    path('<int:pk>/resetar-senha/', views.UsuarioResetarSenhaView.as_view(), name='resetar_senha'),
]
