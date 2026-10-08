from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Arquivo
from .services import remover_do_storage_ao_confirmar


@receiver(post_delete, sender=Arquivo)
def apagar_objeto_do_storage(sender, instance, **kwargs):
    """Excluiu os metadados (inclusive em exclusão em lote): apaga também o objeto no storage."""
    remover_do_storage_ao_confirmar(instance.storage_key)
