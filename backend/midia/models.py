import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models


class Arquivo(models.Model):
    """Metadados de um arquivo enviado. O binário NÃO fica no banco: fica no storage configurado
    (object storage S3/R2 em produção, pasta `uploads/` em desenvolvimento), sob `storage_key`.

    Criado sempre por `midia.services.salvar_upload`, que valida, otimiza e grava o arquivo.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome_original = models.CharField(max_length=255)
    # Caminho do objeto no storage, gerado a partir de um UUID (nunca do nome enviado).
    storage_key = models.CharField(max_length=255, unique=True)
    tamanho = models.PositiveIntegerField(help_text='Tamanho em bytes do arquivo armazenado.')
    formato = models.CharField(max_length=100, help_text='MIME type do arquivo armazenado.')
    largura = models.PositiveIntegerField(null=True, blank=True)
    altura = models.PositiveIntegerField(null=True, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='arquivos_enviados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    # Tipos que o navegador pode exibir direto (imagens já otimizadas e PDF); o resto é baixado.
    FORMATOS_IMAGEM = ('image/jpeg', 'image/png', 'image/webp')
    FORMATOS_EXIBIVEIS = FORMATOS_IMAGEM + ('application/pdf',)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Arquivo'
        verbose_name_plural = 'Arquivos'

    def __str__(self):
        return self.nome_original

    @property
    def url(self):
        """URL pública do arquivo, pronta para <img src> / <a href>."""
        return default_storage.url(self.storage_key)

    @property
    def is_imagem(self):
        return self.formato in self.FORMATOS_IMAGEM

    @property
    def exibivel_no_navegador(self):
        return self.formato in self.FORMATOS_EXIBIVEIS

    def como_dict(self):
        """Representação JSON usada pela API."""
        return {
            'id': str(self.id),
            'nome_original': self.nome_original,
            'url': self.url,
            'tamanho': self.tamanho,
            'formato': self.formato,
            'largura': self.largura,
            'altura': self.altura,
            'criado_em': self.criado_em.isoformat(),
        }
