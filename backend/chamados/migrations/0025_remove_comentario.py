from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chamados', '0024_comentarios_para_procedimentos'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Comentario',
        ),
    ]
