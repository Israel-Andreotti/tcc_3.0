"""Anexos -> object storage (2/3): copia o conteúdo de cada anexo para o storage do app `midia`.

Cada anexo existente tem o conteúdo gravado no storage configurado (bucket S3/R2 ou pasta
`uploads/`) sob uma chave UUID e ganha um registro `midia.Arquivo` com os metadados (o binário
antigo é removido na migration 0017).
"""

import io
import mimetypes
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import migrations
from django.utils import timezone

# Mesma política do serviço de upload: só imagens/PDF ficam exibíveis no navegador; o resto vira
# download, e extensões fora da lista viram `.bin` (nunca HTML/SVG/JS executável).
EXIBIVEIS = {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}
EXTENSOES_DOCUMENTO = {
    '.txt', '.csv', '.log', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp', '.rtf', '.zip', '.7z', '.rar',
}


def _dimensoes(dados):
    try:
        from PIL import Image

        with Image.open(io.BytesIO(dados)) as imagem:
            return imagem.size
    except Exception:
        return None, None


def mover_anexos_para_o_storage(apps, schema_editor):
    Anexo = apps.get_model('chamados', 'Anexo')
    Arquivo = apps.get_model('midia', 'Arquivo')

    for anexo in Anexo.objects.all():
        dados = bytes(anexo.conteudo or b'')
        nome = anexo.nome or 'arquivo'
        formato = mimetypes.guess_type(nome)[0] or 'application/octet-stream'
        extensao = ('.' + nome.rsplit('.', 1)[-1].lower()) if '.' in nome else ''
        if formato in EXIBIVEIS:
            prefixo = 'imagens' if formato.startswith('image/') else 'arquivos'
        else:
            formato, prefixo = 'application/octet-stream', 'arquivos'
            if extensao not in EXTENSOES_DOCUMENTO:
                extensao = '.bin'

        objeto = ContentFile(dados)
        objeto.content_type = formato
        chave = default_storage.save(
            f'{prefixo}/{anexo.criado_em or timezone.now():%Y/%m}/{uuid.uuid4().hex}{extensao}', objeto
        )
        largura, altura = _dimensoes(dados) if formato.startswith('image/') else (None, None)
        arquivo = Arquivo.objects.create(
            nome_original=nome[:255],
            storage_key=chave,
            tamanho=len(dados),
            formato=formato,
            largura=largura,
            altura=altura,
            enviado_por_id=anexo.enviado_por_id,
        )
        anexo.arquivo = arquivo
        anexo.save(update_fields=['arquivo'])


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0015_anexo_em_object_storage'),
    ]

    operations = [
        migrations.RunPython(mover_anexos_para_o_storage, migrations.RunPython.noop),
    ]
