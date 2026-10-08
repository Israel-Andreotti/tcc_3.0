from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('chamados/', include('chamados.urls')),
    path('ativos/', include('ativos.urls')),
    path('midia/', include('midia.urls')),
]

if settings.DEBUG and not settings.STORAGE_BUCKET:
    # Desenvolvimento sem object storage: serve a pasta local de uploads.
    # Em produção os arquivos são servidos direto pela URL pública do bucket.
    urlpatterns += [
        re_path(r'^uploads/(?P<path>.*)$', serve, {'document_root': settings.BASE_DIR / 'uploads'}),
    ]
