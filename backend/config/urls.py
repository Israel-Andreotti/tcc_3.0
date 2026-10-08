from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('chamados/', include('chamados.urls')),
    path('ativos/', include('ativos.urls')),
]
