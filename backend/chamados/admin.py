from django.contrib import admin

from .models import Categoria, Chamado, Comentario, EventoChamado, ProcedimentoEntry, SLAPrioridade, Subcategoria


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


class EventoChamadoInline(admin.TabularInline):
    """Log de auditoria do ciclo de vida: somente leitura."""

    model = EventoChamado
    extra = 0
    fields = ('criado_em', 'tipo', 'autor', 'descricao', 'publico')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ProcedimentoEntryInline(admin.TabularInline):
    model = ProcedimentoEntry
    extra = 0
    readonly_fields = ('autor', 'criado_em')


@admin.register(SLAPrioridade)
class SLAPrioridadeAdmin(admin.ModelAdmin):
    list_display = ('prioridade', 'horas')


@admin.register(Chamado)
class ChamadoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'titulo', 'categoria', 'subcategoria', 'status', 'prioridade', 'solicitante', 'atendente', 'criado_em')
    list_filter = ('status', 'prioridade', 'categoria')
    search_fields = ('codigo', 'titulo', 'descricao')
    readonly_fields = ('prioridade',)  # deriva sempre da subcategoria, ver Chamado.save()
    inlines = [EventoChamadoInline, ProcedimentoEntryInline, ComentarioInline]
