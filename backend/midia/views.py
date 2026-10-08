"""API de imagens (JSON).

POST /midia/imagens/         multipart/form-data com o campo `imagem` -> 201 + metadados e URL pública
GET  /midia/imagens/<uuid>/  -> metadados e URL pública, para usar em <img src="...">

Autenticação pela sessão do sistema (usuário logado). O POST exige o token CSRF, como qualquer
formulário Django (cabeçalho `X-CSRFToken` ou campo `csrfmiddlewaretoken`).
"""

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from .models import Arquivo
from .services import salvar_upload


class ApiLoginObrigatorioMixin:
    """Como LoginRequiredMixin, mas responde 401 em JSON em vez de redirecionar para o login."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'erro': 'Autenticação necessária.'}, status=401)
        return super().dispatch(request, *args, **kwargs)


class ImagemUploadView(ApiLoginObrigatorioMixin, View):
    def post(self, request):
        arquivo = request.FILES.get('imagem')
        if not arquivo:
            return JsonResponse({'erro': 'Envie a imagem no campo "imagem" (multipart/form-data).'}, status=400)
        try:
            imagem = salvar_upload(arquivo, request.user, somente_imagens=True)
        except ValidationError as erro:
            return JsonResponse({'erro': ' '.join(erro.messages)}, status=400)
        return JsonResponse(imagem.como_dict(), status=201)


class ImagemDetalheView(ApiLoginObrigatorioMixin, View):
    def get(self, request, pk):
        imagem = get_object_or_404(Arquivo, pk=pk, formato__in=Arquivo.FORMATOS_IMAGEM)
        return JsonResponse(imagem.como_dict())
