from django.conf import settings
from django.db import models


class Ativo(models.Model):
    class Tipo(models.TextChoices):
        NOTEBOOK = 'notebook', 'Notebook'
        DESKTOP = 'desktop', 'Desktop'
        MONITOR = 'monitor', 'Monitor'
        CELULAR = 'celular', 'Celular'
        IMPRESSORA = 'impressora', 'Impressora'
        OUTRO = 'outro', 'Outro'

    class Status(models.TextChoices):
        EM_USO = 'em_uso', 'Em uso'
        DISPONIVEL = 'disponivel', 'Disponível'
        DANIFICADO = 'danificado', 'Danificado'
        TRIAGEM = 'triagem', 'Triagem'

    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.OUTRO)
    patrimonio = models.CharField('Nº de patrimônio', max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISPONIVEL)

    # Lotação atual: OU num setor, OU atribuído a um funcionário (nunca os dois).
    setor = models.ForeignKey(
        'usuarios.Setor',
        on_delete=models.SET_NULL,
        related_name='ativos_lotados',
        null=True,
        blank=True,
        verbose_name='Setor de lotação',
    )
    funcionario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='ativos_atribuidos',
        null=True,
        blank=True,
        verbose_name='Atribuído a',
    )

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['marca', 'modelo']

    def save(self, *args, **kwargs):
        if self.marca:
            self.marca = self.marca.strip().capitalize()
        if self.modelo:
            self.modelo = self.modelo.strip().capitalize()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.marca} {self.modelo} ({self.patrimonio})'

    @property
    def lotacao_display(self):
        if self.funcionario_id:
            return f'{self.funcionario.get_full_name() or self.funcionario.username} (funcionário)'
        if self.setor_id:
            return str(self.setor)
        return 'Sem lotação'

    @property
    def tem_movimentacao_pendente(self):
        return self.movimentacoes.filter(status=MovimentacaoAtivo.Status.PENDENTE).exists()


class MovimentacaoAtivo(models.Model):
    """Histórico de movimentações de um ativo, sempre vinculado ao chamado que motivou a troca.

    A movimentação fica "pendente" (o ativo só é marcado, nada muda ainda) até o
    chamado ser concluído — só nesse momento ela é "efetivada" e o ativo
    (setor/funcionário/status) é realmente atualizado. Ver Chamado.concluir_movimentacoes_pendentes().
    """

    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente'
        EFETIVADA = 'efetivada', 'Efetivada'

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    efetivada_em = models.DateTimeField(null=True, blank=True)

    ativo = models.ForeignKey(Ativo, on_delete=models.CASCADE, related_name='movimentacoes')
    chamado = models.ForeignKey(
        'chamados.Chamado', on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentacoes_ativo'
    )

    setor_origem = models.ForeignKey(
        'usuarios.Setor', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    funcionario_origem = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    setor_destino = models.ForeignKey(
        'usuarios.Setor', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    funcionario_destino = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='movimentacoes_realizadas'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Movimentação de ativo'
        verbose_name_plural = 'Movimentações de ativo'

    def __str__(self):
        return f'Movimentação de {self.ativo} em {self.criado_em:%d/%m/%Y %H:%M}'

    @property
    def origem_display(self):
        if self.funcionario_origem_id:
            return f'{self.funcionario_origem} (funcionário)'
        if self.setor_origem_id:
            return str(self.setor_origem)
        return 'Sem lotação'

    @property
    def destino_display(self):
        if self.funcionario_destino_id:
            return f'{self.funcionario_destino} (funcionário)'
        if self.setor_destino_id:
            return str(self.setor_destino)
        return 'Sem lotação'
