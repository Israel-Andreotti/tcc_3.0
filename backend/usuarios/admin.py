from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Setor, Usuario


@admin.register(Setor)
class SetorAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Perfil', {'fields': ('perfil', 'telefone', 'setor')}),
    )
    list_display = ('username', 'email', 'telefone', 'setor', 'first_name', 'last_name', 'perfil', 'is_staff')
    list_filter = UserAdmin.list_filter + ('perfil', 'setor')
