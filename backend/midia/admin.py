from django.contrib import admin
from django.utils.html import format_html

from .models import Arquivo


@admin.register(Arquivo)
class ArquivoAdmin(admin.ModelAdmin):
    """Somente consulta: arquivos entram pelo serviço de upload (validação e otimização)."""

    list_display = ('nome_original', 'formato', 'tamanho', 'dimensoes', 'enviado_por', 'criado_em', 'link')
    list_filter = ('formato', 'criado_em')
    search_fields = ('nome_original', 'storage_key')
    readonly_fields = (
        'id', 'nome_original', 'storage_key', 'tamanho', 'formato', 'largura', 'altura', 'enviado_por',
        'criado_em', 'link',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Dimensões')
    def dimensoes(self, obj):
        return f'{obj.largura}×{obj.altura}' if obj.largura else '—'

    @admin.display(description='Arquivo')
    def link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">abrir</a>', obj.url)
