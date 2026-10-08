"""Anexos passam a ser guardados no banco (BinaryField) em vez de arquivos em MEDIA_ROOT.

Copia o conteúdo dos arquivos que existirem em disco para o banco; anexos cujo arquivo
não existe mais (ex.: disco apagado pela hospedagem) não têm como ser recuperados e são removidos.
"""

import mimetypes
import os

from django.conf import settings
from django.db import migrations, models


def copiar_arquivos_para_o_banco(apps, schema_editor):
    Anexo = apps.get_model('chamados', 'Anexo')
    media_root = getattr(settings, 'MEDIA_ROOT', None) or os.path.join(settings.BASE_DIR, 'media')
    for anexo in Anexo.objects.all():
        caminho = os.path.join(media_root, anexo.arquivo.name) if anexo.arquivo else ''
        if not caminho or not os.path.isfile(caminho):
            anexo.delete()
            continue
        with open(caminho, 'rb') as f:
            conteudo = f.read()
        nome = anexo.arquivo.name.rsplit('/', 1)[-1]
        anexo.nome = nome[:255]
        anexo.content_type = (mimetypes.guess_type(nome)[0] or '')[:100]
        anexo.tamanho = len(conteudo)
        anexo.conteudo = conteudo
        anexo.save(update_fields=['nome', 'content_type', 'tamanho', 'conteudo'])


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0013_resposta_solicitante_em'),
    ]

    operations = [
        migrations.AddField(
            model_name='anexo',
            name='nome',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='anexo',
            name='content_type',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='anexo',
            name='tamanho',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='anexo',
            name='conteudo',
            field=models.BinaryField(editable=False, null=True),
        ),
        migrations.RunPython(copiar_arquivos_para_o_banco, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='anexo',
            name='arquivo',
        ),
        migrations.AlterField(
            model_name='anexo',
            name='conteudo',
            field=models.BinaryField(editable=False),
        ),
    ]
