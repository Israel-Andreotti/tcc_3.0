#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py createsuperuser --no-input || true

if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
python manage.py shell -c "
from usuarios.models import Usuario
Usuario.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').update(perfil=Usuario.Perfil.ADMINISTRADOR)
"
fi
