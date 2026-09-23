from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcarTrocaSenhaMiddleware:
    """Redireciona usuários com `deve_trocar_senha=True` para a tela de troca
    de senha antes de liberar qualquer outra página do sistema."""

    CAMINHOS_LIVRES = ('usuarios:trocar_senha', 'usuarios:logout')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, 'user', None)
        if (
            usuario
            and usuario.is_authenticated
            and getattr(usuario, 'deve_trocar_senha', False)
            and not request.path.startswith(settings.STATIC_URL)
            and not request.path.startswith(settings.MEDIA_URL)
        ):
            caminhos_livres = [reverse(nome) for nome in self.CAMINHOS_LIVRES]
            if request.path not in caminhos_livres:
                return redirect('usuarios:trocar_senha')
        return self.get_response(request)
