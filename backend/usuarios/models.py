from django.contrib.auth.models import AbstractUser
from django.db import models


class Setor(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Setor'
        verbose_name_plural = 'Setores'

    def __str__(self):
        return self.nome


class Usuario(AbstractUser):
    class Perfil(models.TextChoices):
        ADMINISTRADOR = 'administrador', 'Administrador'
        ATENDENTE = 'atendente', 'Atendente'
        SOLICITANTE = 'solicitante', 'Solicitante'

    perfil = models.CharField(
        max_length=20,
        choices=Perfil.choices,
        default=Perfil.SOLICITANTE,
    )
    telefone = models.CharField(max_length=20, blank=True)
    setor = models.ForeignKey(
        Setor,
        on_delete=models.SET_NULL,
        related_name='usuarios',
        null=True,
        blank=True,
        verbose_name='Setor de lotação',
        help_text='Setor padrão usado ao abrir um chamado.',
    )
    matricula = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    deve_trocar_senha = models.BooleanField(
        default=False,
        verbose_name='Deve trocar a senha no próximo login',
    )

    def is_administrador(self):
        return self.perfil == self.Perfil.ADMINISTRADOR

    def is_atendente(self):
        return self.perfil == self.Perfil.ATENDENTE

    def is_solicitante(self):
        return self.perfil == self.Perfil.SOLICITANTE

    @staticmethod
    def _gerar_matricula():
        ultima = (
            Usuario.objects.exclude(matricula='')
            .order_by('-matricula')
            .values_list('matricula', flat=True)
            .first()
        )
        proxima = int(ultima) + 1 if ultima else 100001
        return str(proxima)

    def save(self, *args, **kwargs):
        if not self.matricula:
            self.matricula = self._gerar_matricula()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.get_perfil_display()})'
