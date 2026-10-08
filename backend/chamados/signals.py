from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Anexo


@receiver(post_delete, sender=Anexo)
def apagar_arquivo_do_anexo(sender, instance, **kwargs):
    """Anexo removido (ex.: chamado excluído pelo admin): remove também o arquivo — os metadados e,
    via signal do app midia, o objeto no storage."""
    instance.arquivo.delete()
