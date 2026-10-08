import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from chamados.models import Anexo, Categoria, Chamado, Subcategoria
from usuarios.models import Setor, Usuario

from .models import Arquivo
from .services import DIMENSAO_MAXIMA

PASTA_TESTE = tempfile.mkdtemp(prefix='hd-uploads-teste-')
STORAGE_TESTE = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'OPTIONS': {'location': PASTA_TESTE, 'base_url': '/uploads/'},
    },
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def arquivos_no_storage():
    return {str(p.relative_to(PASTA_TESTE)) for p in Path(PASTA_TESTE).rglob('*') if p.is_file()}


def imagem_bytes(formato='PNG', tamanho=(64, 48), modo='RGB', exif=None):
    buffer = io.BytesIO()
    imagem = Image.new(modo, tamanho, color=(200, 30, 30) if modo == 'RGB' else None)
    argumentos = {'exif': exif} if exif else {}
    imagem.save(buffer, format=formato, **argumentos)
    return buffer.getvalue()


@override_settings(STORAGES=STORAGE_TESTE)
class BaseMidiaTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PASTA_TESTE, ignore_errors=True)

    def setUp(self):
        self.usuario = Usuario.objects.create_user('ana', password='x')
        self.client.force_login(self.usuario)


class ImagemUploadApiTests(BaseMidiaTestCase):
    url = reverse('midia:imagem_upload')

    def enviar(self, nome, conteudo, content_type='image/png'):
        return self.client.post(self.url, {'imagem': SimpleUploadedFile(nome, conteudo, content_type)})

    def test_upload_png_e_otimizado_para_webp_com_chave_uuid(self):
        resposta = self.enviar('foto.png', imagem_bytes('PNG'))

        self.assertEqual(resposta.status_code, 201)
        dados = resposta.json()
        arquivo = Arquivo.objects.get(pk=dados['id'])
        self.assertEqual(arquivo.formato, 'image/webp')
        self.assertEqual(arquivo.nome_original, 'foto.png')
        self.assertRegex(arquivo.storage_key, r'^imagens/\d{4}/\d{2}/[0-9a-f]{32}\.webp$')
        self.assertTrue(default_storage.exists(arquivo.storage_key))
        self.assertEqual(dados['url'], f'/uploads/{arquivo.storage_key}')
        self.assertEqual((dados['largura'], dados['altura']), (64, 48))

    def test_imagem_grande_e_redimensionada(self):
        resposta = self.enviar('grande.jpg', imagem_bytes('JPEG', (4000, 3000)), 'image/jpeg')

        dados = resposta.json()
        self.assertEqual(max(dados['largura'], dados['altura']), DIMENSAO_MAXIMA)
        self.assertEqual(dados['altura'], 1440)  # mantém a proporção 4:3

    def test_metadados_exif_sao_removidos(self):
        exif = Image.Exif()
        exif[0x010F] = 'CameraSecreta'  # Make
        resposta = self.enviar('com-exif.jpg', imagem_bytes('JPEG', exif=exif), 'image/jpeg')

        arquivo = Arquivo.objects.get(pk=resposta.json()['id'])
        with default_storage.open(arquivo.storage_key) as f, Image.open(f) as salva:
            self.assertNotIn(0x010F, salva.getexif())

    def test_mime_e_verificado_pelo_conteudo_nao_pelo_nome(self):
        resposta = self.enviar('falsa.png', b'<script>alert(1)</script>', 'image/png')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('não é uma imagem válida', resposta.json()['erro'])
        self.assertFalse(Arquivo.objects.exists())

    def test_formato_fora_da_lista_e_recusado(self):
        resposta = self.enviar('anim.gif', imagem_bytes('GIF'), 'image/gif')

        self.assertEqual(resposta.status_code, 400)

    def test_campo_ausente(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 400)

    def test_exige_login(self):
        self.client.logout()
        resposta = self.enviar('foto.png', imagem_bytes())

        self.assertEqual(resposta.status_code, 401)


class ImagemLeituraApiTests(BaseMidiaTestCase):
    def test_retorna_url_publica_para_outro_usuario(self):
        resposta = self.client.post(
            reverse('midia:imagem_upload'), {'imagem': SimpleUploadedFile('f.png', imagem_bytes(), 'image/png')}
        )
        outro = Usuario.objects.create_user('bruno', password='x')
        self.client.force_login(outro)

        dados = self.client.get(reverse('midia:imagem_detalhe', args=[resposta.json()['id']])).json()

        self.assertTrue(dados['url'].endswith('.webp'))
        self.assertEqual(dados['formato'], 'image/webp')

    def test_inexistente_ou_nao_imagem_da_404(self):
        documento = Arquivo.objects.create(
            nome_original='a.pdf', storage_key='arquivos/x.pdf', tamanho=1, formato='application/pdf'
        )
        self.assertEqual(self.client.get(reverse('midia:imagem_detalhe', args=[documento.pk])).status_code, 404)
        self.assertEqual(
            self.client.get('/midia/imagens/00000000-0000-0000-0000-000000000000/').status_code, 404
        )


class RemocaoTests(BaseMidiaTestCase):
    def test_excluir_metadados_apaga_objeto_do_storage(self):
        resposta = self.client.post(
            reverse('midia:imagem_upload'), {'imagem': SimpleUploadedFile('f.png', imagem_bytes(), 'image/png')}
        )
        arquivo = Arquivo.objects.get(pk=resposta.json()['id'])

        with self.captureOnCommitCallbacks(execute=True):
            arquivo.delete()

        self.assertFalse(default_storage.exists(arquivo.storage_key))


class AnexosDeChamadoTests(BaseMidiaTestCase):
    def setUp(self):
        super().setUp()
        self.setor = Setor.objects.create(nome='Recepção')
        self.usuario.setor = self.setor
        self.usuario.save()
        categoria = Categoria.objects.create(nome='Teste')
        self.subcategoria = Subcategoria.objects.create(categoria=categoria, nome='Impressora teste')

    def abrir_chamado(self, *anexos):
        return self.client.post(reverse('chamados:create'), {
            'categoria': self.subcategoria.categoria_id,
            'subcategoria': self.subcategoria.pk,
            'setor': self.setor.pk,
            'descricao': 'teste',
            'anexos': list(anexos),
        })

    def test_anexos_vao_para_o_storage_com_politica_de_tipo(self):
        resposta = self.abrir_chamado(
            SimpleUploadedFile('print.png', imagem_bytes(), 'image/png'),
            SimpleUploadedFile('manual.pdf', b'%PDF-1.4 conteudo', 'application/pdf'),
            SimpleUploadedFile('pagina.html', b'<script>alert(1)</script>', 'text/html'),
        )

        self.assertEqual(resposta.status_code, 302)
        formatos = {a.arquivo.nome_original: a.arquivo for a in Anexo.objects.select_related('arquivo')}
        self.assertEqual(formatos['print.png'].formato, 'image/webp')
        self.assertEqual(formatos['manual.pdf'].formato, 'application/pdf')
        # HTML nunca fica executável: vira download binário com extensão neutra.
        self.assertEqual(formatos['pagina.html'].formato, 'application/octet-stream')
        self.assertTrue(formatos['pagina.html'].storage_key.endswith('.bin'))

    def test_anexo_recusado_desfaz_chamado_e_limpa_storage(self):
        # Imagem válida + imagem com resolução acima do limite (recusada só no processamento).
        gigante = SimpleUploadedFile('gigante.png', imagem_bytes('PNG', (8000, 6000), modo='1'), 'image/png')
        antes = arquivos_no_storage()
        resposta = self.abrir_chamado(SimpleUploadedFile('ok.png', imagem_bytes(), 'image/png'), gigante)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'resolução grande demais')
        self.assertFalse(Chamado.objects.exists())
        self.assertFalse(Arquivo.objects.exists())
        # A imagem válida chegou a ser gravada antes da recusa da segunda: deve ter sido apagada.
        self.assertEqual(arquivos_no_storage(), antes)


class ConfiguracaoS3Tests(TestCase):
    def test_url_publica_do_bucket_sem_assinatura(self):
        from storages.backends.s3 import S3Storage

        storage = S3Storage(
            bucket_name='tcc', access_key='a', secret_key='b', endpoint_url='https://conta.r2.cloudflarestorage.com',
            custom_domain='pub-123.r2.dev', querystring_auth=False, default_acl=None,
        )

        self.assertEqual(storage.url('imagens/2026/10/abc.webp'), 'https://pub-123.r2.dev/imagens/2026/10/abc.webp')
