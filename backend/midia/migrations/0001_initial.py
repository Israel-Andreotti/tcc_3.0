import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Arquivo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('nome_original', models.CharField(max_length=255)),
                ('storage_key', models.CharField(max_length=255, unique=True)),
                ('tamanho', models.PositiveIntegerField(help_text='Tamanho em bytes do arquivo armazenado.')),
                ('formato', models.CharField(help_text='MIME type do arquivo armazenado.', max_length=100)),
                ('largura', models.PositiveIntegerField(blank=True, null=True)),
                ('altura', models.PositiveIntegerField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('enviado_por', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='arquivos_enviados', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Arquivo',
                'verbose_name_plural': 'Arquivos',
                'ordering': ['-criado_em'],
            },
        ),
    ]
