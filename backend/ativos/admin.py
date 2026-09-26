from django.contrib import admin

from .models import Ativo, MovimentacaoAtivo


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ('marca', 'modelo', 'tipo', 'patrimonio', 'status', 'setor', 'funcionario')
    list_filter = ('status', 'tipo', 'setor')
    search_fields = ('marca', 'modelo', 'patrimonio')


@admin.register(MovimentacaoAtivo)
class MovimentacaoAtivoAdmin(admin.ModelAdmin):
    list_display = ('ativo', 'chamado', 'setor_origem', 'setor_destino', 'realizado_por', 'criado_em')
    readonly_fields = ('criado_em',)
    list_filter = ('criado_em',)
