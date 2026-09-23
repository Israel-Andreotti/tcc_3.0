from django.contrib.auth.mixins import UserPassesTestMixin


class PerfilRequiredMixin(UserPassesTestMixin):
    """Libera a view apenas para usuários com um dos perfis em `perfis_permitidos`."""

    perfis_permitidos = ()

    def test_func(self):
        usuario = self.request.user
        return usuario.is_authenticated and usuario.perfil in self.perfis_permitidos


class AdministradorRequiredMixin(PerfilRequiredMixin):
    perfis_permitidos = ('administrador',)


class AtendenteRequiredMixin(PerfilRequiredMixin):
    perfis_permitidos = ('administrador', 'atendente')
