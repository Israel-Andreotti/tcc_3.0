from django.contrib import admin

from .models import Anexo, Categoria, Chamado, Comentario, ProcedimentoEntry, Subcategoria


class SubcategoriaInline(admin.TabularInline):
    model = Subcategoria
    extra = 1
    fields = ('nome', 'prioridade')


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ordem')
    ordering = ('ordem', 'nome')
    inlines = [SubcategoriaInline]


class ComentarioInline(admin.TabularInline):
    model = Comentario
    extra = 0
    readonly_fields = ('autor', 'criado_em')


class ProcedimentoEntryInline(admin.TabularInline):
    model = ProcedimentoEntry
    extra = 0
    readonly_fields = ('autor', 'criado_em')


class AnexoInline(admin.TabularInline):
    model = Anexo
    extra = 0
    readonly_fields = ('enviado_por', 'criado_em')


@admin.register(Chamado)
class ChamadoAdmin(admin.ModelAdmin):
    list_display = ('id', 'titulo', 'categoria', 'subcategoria', 'status', 'prioridade', 'solicitante', 'atendente', 'criado_em')
    list_filter = ('status', 'prioridade', 'categoria')
    search_fields = ('titulo', 'descricao')
    readonly_fields = ('prioridade',)  # deriva sempre da subcategoria, ver Chamado.save()
    inlines = [ProcedimentoEntryInline, AnexoInline, ComentarioInline]
