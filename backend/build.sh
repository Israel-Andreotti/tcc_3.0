#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
python manage.py shell -c "
import os
from usuarios.models import Usuario

username = os.environ['DJANGO_SUPERUSER_USERNAME']
password = os.environ['DJANGO_SUPERUSER_PASSWORD']
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

usuario, _ = Usuario.objects.get_or_create(username=username, defaults={'email': email})
usuario.is_staff = True
usuario.is_superuser = True
usuario.is_active = True
usuario.perfil = Usuario.Perfil.ADMINISTRADOR
usuario.deve_trocar_senha = False
usuario.set_password(password)
usuario.save()
"
fi
