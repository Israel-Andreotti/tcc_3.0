from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Prioridade(models.TextChoices):
    BAIXA = 'baixa', 'Baixa'
    MEDIA = 'media', 'Média'
    ALTA = 'alta', 'Alta'
    CRITICA = 'critica', 'Crítica'


class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['ordem', 'nome']
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'

    def __str__(self):
        return self.nome


class Subcategoria(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='subcategorias')
    nome = models.CharField(max_length=100)
    # Prioridade padrão de qualquer chamado aberto nessa subcategoria — é ela quem
    # define a prioridade do chamado, nenhum usuário escolhe isso manualmente.
    prioridade = models.CharField(max_length=10, choices=Prioridade.choices, default=Prioridade.MEDIA)

    class Meta:
        ordering = ['nome']
        unique_together = ('categoria', 'nome')
        verbose_name = 'Subcategoria'
        verbose_name_plural = 'Subcategorias'

    def __str__(self):
        return f'{self.categoria} > {self.nome}'


class Chamado(models.Model):
    class Status(models.TextChoices):
        ABERTO = 'aberto', 'Aberto'
        EM_ANDAMENTO = 'em_andamento', 'Em andamento'
        AGUARDANDO_SOLICITANTE = 'aguardando_solicitante', 'Aguardando solicitante'
        RESOLVIDO = 'resolvido', 'Resolvido'
        FECHADO = 'fechado', 'Fechado'

    Prioridade = Prioridade

    # Prazo de SLA (em horas) por prioridade, usado para calcular `prazo_sla`.
    SLA_HORAS = {
        Prioridade.CRITICA: 4,
        Prioridade.ALTA: 8,
        Prioridade.MEDIA: 24,
        Prioridade.BAIXA: 72,
    }

    titulo = models.CharField(max_length=150)
    descricao = models.TextField()
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.ABERTO)
    # Nunca definida por formulário de usuário: sempre espelha a prioridade da subcategoria (ver save()).
    prioridade = models.CharField(max_length=10, choices=Prioridade.choices, default=Prioridade.MEDIA)

    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name='chamados',
        null=True,
        blank=True,
    )
    subcategoria = models.ForeignKey(
        Subcategoria,
        on_delete=models.PROTECT,
        related_name='chamados',
        null=True,
        blank=True,
    )

    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='chamados_solicitados',
    )
    setor = models.ForeignKey(
        'usuarios.Setor',
        on_delete=models.PROTECT,
        related_name='chamados',
        null=True,
        blank=True,
        help_text='Setor padrão é o de lotação do solicitante, mas pode ser alterado.',
    )
    atendente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='chamados_atendidos',
        null=True,
        blank=True,
    )
    ativo = models.ForeignKey(
        'ativos.Ativo',
        on_delete=models.SET_NULL,
        related_name='chamados',
        null=True,
        blank=True,
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    prazo_sla = models.DateTimeField(null=True, blank=True)
    fechado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'#{self.pk} {self.titulo}'

    def save(self, *args, **kwargs):
        if self.subcategoria_id:
            self.prioridade = self.subcategoria.prioridade
        if not self.prazo_sla:
            horas = self.SLA_HORAS.get(self.prioridade, 24)
            self.prazo_sla = timezone.now() + timedelta(hours=horas)
        super().save(*args, **kwargs)

    @property
    def sla_estourado(self):
        if self.status in (self.Status.RESOLVIDO, self.Status.FECHADO):
            return False
        return bool(self.prazo_sla and timezone.now() > self.prazo_sla)

    @property
    def sla_concluido(self):
        return self.status in (self.Status.RESOLVIDO, self.Status.FECHADO)

    @property
    def sla_percentual(self):
        """Percentual do prazo de SLA já decorrido, de 0 a 100 (100 = estourado)."""
        if not self.prazo_sla:
            return 0
        total = (self.prazo_sla - self.criado_em).total_seconds()
        decorrido = (timezone.now() - self.criado_em).total_seconds()
        if total <= 0:
            return 100
        return max(0, min(100, round(decorrido / total * 100)))

    @property
    def sla_cor(self):
        percentual = self.sla_percentual
        if percentual >= 100:
            return 'critico'
        if percentual >= 70:
            return 'atencao'
        return 'ok'

    @property
    def sla_tempo_restante_display(self):
        if not self.prazo_sla:
            return '-'
        delta = self.prazo_sla - timezone.now()
        segundos = delta.total_seconds()
        horas = int(abs(segundos) // 3600)
        minutos = int((abs(segundos) % 3600) // 60)
        texto = f'{horas}h {minutos}min'
        return f'Atrasado há {texto}' if segundos < 0 else f'{texto} restantes'


class Comentario(models.Model):
    chamado = models.ForeignKey(Chamado, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    texto = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em']

    def __str__(self):
        return f'Comentário de {self.autor} em #{self.chamado_id}'


def anexo_upload_path(instance, filename):
    return f'chamados/{instance.chamado_id}/{filename}'


class Anexo(models.Model):
    EXTENSOES_IMAGEM = ('.png', '.jpg', '.jpeg', '.gif', '.webp')

    chamado = models.ForeignKey(Chamado, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.FileField(upload_to=anexo_upload_path)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em']
        verbose_name = 'Anexo'
        verbose_name_plural = 'Anexos'

    def __str__(self):
        return self.arquivo.name

    @property
    def nome(self):
        return self.arquivo.name.rsplit('/', 1)[-1]

    @property
    def is_imagem(self):
        return self.nome.lower().endswith(self.EXTENSOES_IMAGEM)


class ProcedimentoEntry(models.Model):
    """Linha do time do procedimento de atendimento — cada uma pública (visível ao
    solicitante) ou interna (restrita à equipe técnica), na ordem em que foi registrada."""

    class Tipo(models.TextChoices):
        PUBLICO = 'publico', 'Procedimento'
        INTERNO = 'interno', 'Nota interna'

    chamado = models.ForeignKey(Chamado, on_delete=models.CASCADE, related_name='procedimentos')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.PUBLICO)
    texto = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em']
        verbose_name = 'Entrada de procedimento'
        verbose_name_plural = 'Entradas de procedimento'

    def __str__(self):
        return f'{self.get_tipo_display()} de {self.autor} em #{self.chamado_id}'
