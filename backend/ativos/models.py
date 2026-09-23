from django.db import models


class Ativo(models.Model):
    class Situacao(models.TextChoices):
        ATIVO = 'ativo', 'Ativo'
        MANUTENCAO = 'manutencao', 'Em manutenção'
        INATIVO = 'inativo', 'Inativo'

    nome = models.CharField(max_length=150)
    patrimonio = models.CharField('Nº de patrimônio', max_length=50, unique=True)
    localizacao = models.CharField(max_length=150, blank=True)
    situacao = models.CharField(max_length=20, choices=Situacao.choices, default=Situacao.ATIVO)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} ({self.patrimonio})'
