"""Serviço de upload: valida, otimiza e grava arquivos no storage, registrando os metadados.

Fluxo de `salvar_upload`:
1. Limite de tamanho do envio.
2. Identificação do tipo pelo CONTEÚDO (Pillow / assinatura do arquivo), nunca pelo nome ou
   pelo Content-Type informado pelo navegador — ambos são controlados pelo cliente.
3. Imagens (JPEG, PNG, WebP): corrige a rotação EXIF, reduz para no máximo 1920px no maior
   lado e recodifica em WebP. Isso remove metadados (GPS etc.) e costuma reduzir bastante o tamanho.
4. O objeto é gravado com uma chave nova baseada em UUID (sem colisão nem sobrescrita).
5. Os metadados vão para a tabela `midia_arquivo`; se o banco falhar, o objeto gravado é removido.
"""

import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Arquivo

TAMANHO_MAXIMO_ENVIO = 10 * 1024 * 1024  # 10 MB (antes da otimização)
DIMENSAO_MAXIMA = 1920  # px no maior lado
QUALIDADE_WEBP = 82
# Proteção contra "bombas de descompressão" (arquivo pequeno que vira uma imagem gigante na memória).
PIXELS_MAXIMOS = 40_000_000

FORMATOS_IMAGEM_ACEITOS = {'JPEG', 'PNG', 'WEBP'}

# Extensões mantidas para arquivos que não são imagem (anexos). Qualquer outra vira `.bin`, para o
# arquivo nunca ser servido como HTML/SVG/JS executável. São sempre entregues como download.
EXTENSOES_DOCUMENTO = {
    '.txt', '.csv', '.log', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp', '.rtf', '.zip', '.7z', '.rar',
}


class ImagemProcessada:
    def __init__(self, conteudo, largura, altura):
        self.conteudo = conteudo
        self.largura = largura
        self.altura = altura


def _processar_imagem(dados):
    """Valida e otimiza uma imagem. Retorna `ImagemProcessada` ou None se não for uma imagem aceita."""
    try:
        with Image.open(io.BytesIO(dados)) as teste:
            formato = teste.format
            largura, altura = teste.size
            teste.verify()  # detecta arquivo truncado/corrompido
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return None

    if formato not in FORMATOS_IMAGEM_ACEITOS:
        return None
    if largura * altura > PIXELS_MAXIMOS:
        raise ValidationError('A imagem tem resolução grande demais.')

    # verify() inutiliza o objeto: reabre para processar.
    with Image.open(io.BytesIO(dados)) as imagem:
        imagem = ImageOps.exif_transpose(imagem)  # aplica a rotação da câmera antes de descartar o EXIF
        tem_transparencia = imagem.mode in ('RGBA', 'LA', 'PA') or (
            imagem.mode == 'P' and 'transparency' in imagem.info
        )
        imagem = imagem.convert('RGBA' if tem_transparencia else 'RGB')
        imagem.thumbnail((DIMENSAO_MAXIMA, DIMENSAO_MAXIMA), Image.Resampling.LANCZOS)

        saida = io.BytesIO()
        imagem.save(saida, format='WEBP', quality=QUALIDADE_WEBP, method=4)
        return ImagemProcessada(saida.getvalue(), imagem.width, imagem.height)


def _gerar_chave(prefixo, extensao):
    agora = timezone.now()
    return f'{prefixo}/{agora:%Y/%m}/{uuid.uuid4().hex}{extensao}'


def salvar_upload(arquivo_enviado, usuario, *, somente_imagens=True):
    """Valida, otimiza e grava um arquivo enviado (UploadedFile). Retorna o `Arquivo` criado.

    `somente_imagens=False` aceita também outros arquivos (anexos de chamados): PDF é mantido como
    PDF; os demais são guardados sem alteração e sempre entregues como download.
    Lança `ValidationError` com mensagem amigável quando o arquivo é recusado.
    """
    nome_original = (arquivo_enviado.name or 'arquivo').rsplit('/', 1)[-1].rsplit('\\', 1)[-1][:255]
    if not arquivo_enviado.size:
        raise ValidationError(f'O arquivo "{nome_original}" está vazio.')
    if arquivo_enviado.size > TAMANHO_MAXIMO_ENVIO:
        limite = TAMANHO_MAXIMO_ENVIO // (1024 * 1024)
        raise ValidationError(f'O arquivo "{nome_original}" passa do limite de {limite} MB.')

    dados = arquivo_enviado.read()
    imagem = _processar_imagem(dados)

    if imagem:
        conteudo, formato, extensao, prefixo = imagem.conteudo, 'image/webp', '.webp', 'imagens'
    elif somente_imagens:
        raise ValidationError(f'"{nome_original}" não é uma imagem válida. Envie JPEG, PNG ou WebP.')
    elif dados.startswith(b'%PDF-'):
        conteudo, formato, extensao, prefixo = dados, 'application/pdf', '.pdf', 'arquivos'
    else:
        extensao = ('.' + nome_original.rsplit('.', 1)[-1].lower()) if '.' in nome_original else ''
        if extensao not in EXTENSOES_DOCUMENTO:
            extensao = '.bin'
        conteudo, formato, prefixo = dados, 'application/octet-stream', 'arquivos'

    objeto = ContentFile(conteudo)
    # O backend S3 usa este atributo como Content-Type do objeto (senão adivinharia pela extensão).
    objeto.content_type = formato
    chave = default_storage.save(_gerar_chave(prefixo, extensao), objeto)

    try:
        return Arquivo.objects.create(
            nome_original=nome_original,
            storage_key=chave,
            tamanho=len(conteudo),
            formato=formato,
            largura=imagem.largura if imagem else None,
            altura=imagem.altura if imagem else None,
            enviado_por=usuario if getattr(usuario, 'is_authenticated', False) else None,
        )
    except Exception:
        default_storage.delete(chave)  # não deixa objeto órfão no storage
        raise


def remover_do_storage_ao_confirmar(chave):
    """Apaga o objeto do storage só depois que a transação do banco confirmar a exclusão."""
    transaction.on_commit(lambda: default_storage.delete(chave))
