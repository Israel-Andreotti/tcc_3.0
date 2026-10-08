#!/usr/bin/env bash
# Inicialização em produção (Koyeb): prepara arquivos estáticos e banco, garante o admin e sobe o servidor.
# As dependências já foram instaladas pela hospedagem a partir do requirements.txt.
set -o errexit

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Cria/atualiza o administrador inicial a partir das variáveis de ambiente
# (a senha é sincronizada a cada inicialização).
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

exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
