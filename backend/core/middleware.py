import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


class ExpirarSessaoInativaMiddleware:
    """Encerra a sessão depois de `SESSAO_INATIVIDADE_MINUTOS` sem uso (computadores compartilhados).

    As consultas automáticas da página (notificações e versão da fila, a cada 15–30s) não contam como
    uso — senão a sessão nunca expiraria. Quando uma delas encontra a sessão vencida, responde 401 e o
    JavaScript recarrega a página; é esse acesso normal que faz o logout e leva ao login com o aviso.
    """

    CHAVE = 'ultima_atividade'
    CONSULTAS_AUTOMATICAS = ('chamados:notificacoes', 'chamados:fila_versao')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            agora = int(time.time())
            automatica = request.path in [reverse(nome) for nome in self.CONSULTAS_AUTOMATICAS]
            ultima = request.session.get(self.CHAVE)
            if ultima is not None and agora - ultima > settings.SESSAO_INATIVIDADE_MINUTOS * 60:
                if automatica:
                    return JsonResponse({'sessao_expirada': True}, status=401)
                logout(request)
                messages.info(request, 'Sua sessão expirou por inatividade. Entre novamente.')
                return redirect_to_login(request.get_full_path())
            if not automatica:
                request.session[self.CHAVE] = agora
        return self.get_response(request)


class ForcarTrocaSenhaMiddleware:
    """Redireciona usuários com `deve_trocar_senha=True` para a tela de troca
    de senha antes de liberar qualquer outra página do sistema."""

    CAMINHOS_LIVRES = ('usuarios:trocar_senha', 'usuarios:logout')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, 'user', None)
        if (
            not settings.LOGIN_RAPIDO  # testes locais: não obriga a trocar a senha
            and usuario
            and usuario.is_authenticated
            and getattr(usuario, 'deve_trocar_senha', False)
            and not request.path.startswith(settings.STATIC_URL)
        ):
            caminhos_livres = [reverse(nome) for nome in self.CAMINHOS_LIVRES]
            if request.path not in caminhos_livres:
                return redirect('usuarios:trocar_senha')
        return self.get_response(request)
