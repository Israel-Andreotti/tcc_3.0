from django.conf import settings
from django.db import models
from django.utils import timezone


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
    # Gerado automaticamente no save() (sequencial, a partir de 100001).
    patrimonio = models.CharField('Nº de patrimônio', max_length=50, unique=True, blank=True, editable=False)
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

    @staticmethod
    def _gerar_patrimonio():
        # Considera só patrimônios no formato gerado (6 dígitos), ignorando os cadastrados manualmente antes.
        ultimo = (
            Ativo.objects.filter(patrimonio__regex=r'^[0-9]{6}$')
            .order_by('-patrimonio')
            .values_list('patrimonio', flat=True)
            .first()
        )
        proximo = int(ultimo) + 1 if ultimo else 100001
        return str(proximo)

    def save(self, *args, **kwargs):
        if not self.patrimonio:
            self.patrimonio = self._gerar_patrimonio()
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
    """Registro (auditoria) de toda alteração de lotação de um ativo: setor/funcionário de
    origem e destino, data/hora e o técnico que executou.

    Duas origens possíveis:
    - Via chamado: fica "pendente" (nada muda no ativo) até o chamado ser concluído; só então
      é efetivada por efetivar(), que também captura a origem real naquele momento.
    - Edição manual do ativo: já nasce efetivada, sem chamado vinculado.

    Os registros nunca são apagados: o ativo usa PROTECT e o Django admin é somente leitura.
    """

    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente'
        EFETIVADA = 'efetivada', 'Efetivada'

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    efetivada_em = models.DateTimeField(null=True, blank=True)

    ativo = models.ForeignKey(Ativo, on_delete=models.PROTECT, related_name='movimentacoes')
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

    @property
    def data_hora(self):
        """Momento em que a lotação de fato mudou (ou o registro, se ainda pendente)."""
        return self.efetivada_em or self.criado_em

    def efetivar(self):
        """Aplica a movimentação pendente ao ativo, registrando a lotação real de origem neste momento."""
        ativo = self.ativo
        self.setor_origem = ativo.setor
        self.funcionario_origem = ativo.funcionario
        ativo.setor = self.setor_destino
        ativo.funcionario = self.funcionario_destino
        # Voltou pro estoque da TI fica disponível; qualquer outro destino está em uso.
        if self.setor_destino_id and not self.funcionario_destino_id and self.setor_destino.nome == 'TI':
            ativo.status = Ativo.Status.DISPONIVEL
        else:
            ativo.status = Ativo.Status.EM_USO
        ativo.save()
        self.status = self.Status.EFETIVADA
        self.efetivada_em = timezone.now()
        self.save()
