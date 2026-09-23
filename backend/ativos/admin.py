from django.contrib import admin

from .models import Ativo


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'patrimonio', 'localizacao', 'situacao')
    list_filter = ('situacao',)
    search_fields = ('nome', 'patrimonio')
