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
        ('Perfil', {'fields': ('perfil', 'telefone', 'setor', 'vip')}),
        ('Superadministrador', {
            'fields': ('super_admin',),
            'description': (
                'Acima do administrador comum: tem todas as permissões de administrador, mas '
                'nenhum usuário (nem outro admin) pode editá-lo, resetar sua senha ou desativá-lo '
                'pela interface do sistema, e não aparece na listagem de usuários.'
            ),
        }),
    )
    list_display = ('username', 'email', 'telefone', 'setor', 'first_name', 'last_name', 'perfil', 'super_admin', 'is_staff')
    list_filter = UserAdmin.list_filter + ('perfil', 'setor', 'super_admin')
