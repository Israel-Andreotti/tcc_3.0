from django.apps import AppConfig


class MidiaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'midia'
    verbose_name = 'Mídia'

    def ready(self):
        from . import signals  # noqa: F401  (registra os receivers)
