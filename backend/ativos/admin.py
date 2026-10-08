from django.contrib import admin

from .models import Ativo, MovimentacaoAtivo


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ('marca', 'modelo', 'tipo', 'patrimonio', 'status', 'setor', 'funcionario')
    list_filter = ('status', 'tipo', 'setor')
    search_fields = ('marca', 'modelo', 'patrimonio')
    readonly_fields = ('patrimonio',)


@admin.register(MovimentacaoAtivo)
class MovimentacaoAtivoAdmin(admin.ModelAdmin):
    """Registro de auditoria: somente leitura, ninguém cria, altera ou apaga por aqui."""

    list_display = (
        'ativo', 'status', 'setor_origem', 'setor_destino', 'funcionario_origem', 'funcionario_destino',
        'realizado_por', 'chamado', 'criado_em', 'efetivada_em',
    )
    list_filter = ('status', 'criado_em')
    search_fields = ('ativo__patrimonio', 'ativo__marca', 'ativo__modelo')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
