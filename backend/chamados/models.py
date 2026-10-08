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


class SLAPrioridade(models.Model):
    """Prazo de SLA (em horas) configurável por prioridade. Editável apenas por administradores."""

    prioridade = models.CharField(max_length=10, choices=Prioridade.choices, unique=True)
    horas = models.PositiveIntegerField(help_text='Prazo, em horas, para resolver um chamado dessa prioridade.')

    class Meta:
        ordering = ['prioridade']
        verbose_name = 'SLA por prioridade'
        verbose_name_plural = 'SLAs por prioridade'

    def __str__(self):
        return f'{self.get_prioridade_display()} — {self.horas}h'


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

    # Solicitantes marcados como VIP têm o prazo de SLA reduzido nesse percentual.
    VIP_SLA_MULTIPLICADOR = 0.75

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
    # Pausa do SLA enquanto o chamado aguarda o solicitante: ao retomar, o tempo parado é
    # somado em `sla_tempo_pausado` e o `prazo_sla` é estendido na mesma medida.
    sla_pausado_em = models.DateTimeField(null=True, blank=True)
    sla_tempo_pausado = models.DurationField(default=timedelta(0))
    # Quando o solicitante respondeu e o técnico responsável ainda não abriu o chamado (notificação).
    resposta_solicitante_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'#{self.pk} {self.titulo}'

    def save(self, *args, **kwargs):
        if self.subcategoria_id:
            self.prioridade = self.subcategoria.prioridade
        if not self.prazo_sla:
            self.prazo_sla = timezone.now() + timedelta(hours=self.sla_horas_configurado())
        super().save(*args, **kwargs)

    def sla_horas_configurado(self):
        horas = SLAPrioridade.objects.filter(prioridade=self.prioridade).values_list('horas', flat=True).first()
        if horas is None:
            horas = self.SLA_HORAS.get(self.prioridade, 24)
        if self.solicitante_id and getattr(self.solicitante, 'vip', False):
            horas *= self.VIP_SLA_MULTIPLICADOR
        return horas

    @classmethod
    def respostas_nao_vistas(cls, tecnico):
        """Chamados abertos do técnico em que o solicitante respondeu e ele ainda não abriu."""
        return cls.objects.filter(atendente=tecnico, resposta_solicitante_em__isnull=False).exclude(
            status__in=[cls.Status.RESOLVIDO, cls.Status.FECHADO]
        )

    @property
    def sla_pausado(self):
        return self.sla_pausado_em is not None

    def pausar_sla(self):
        """Congela o relógio do SLA (não salva — quem chama salva o chamado)."""
        if not self.sla_pausado:
            self.sla_pausado_em = timezone.now()

    def retomar_sla(self):
        """Volta a contar o SLA, estendendo o prazo pelo tempo que ficou pausado (não salva)."""
        if self.sla_pausado:
            pausa = timezone.now() - self.sla_pausado_em
            self.sla_tempo_pausado += pausa
            if self.prazo_sla:
                self.prazo_sla += pausa
            self.sla_pausado_em = None

    def _sla_referencia(self):
        # Enquanto pausado, o "agora" do SLA fica parado no início da pausa.
        return self.sla_pausado_em or timezone.now()

    @property
    def sla_estourado(self):
        if self.status in (self.Status.RESOLVIDO, self.Status.FECHADO):
            return False
        return bool(self.prazo_sla and self._sla_referencia() > self.prazo_sla)

    @property
    def encerrado(self):
        """Chamado resolvido/fechado fica somente leitura: nenhuma ação da equipe é aceita."""
        return self.status in (self.Status.RESOLVIDO, self.Status.FECHADO)

    @property
    def sla_concluido(self):
        return self.encerrado

    @property
    def sla_percentual(self):
        """Percentual do prazo de SLA já decorrido, de 0 a 100 (100 = estourado), descontando as pausas."""
        if not self.prazo_sla:
            return 0
        total = (self.prazo_sla - self.criado_em - self.sla_tempo_pausado).total_seconds()
        decorrido = (self._sla_referencia() - self.criado_em - self.sla_tempo_pausado).total_seconds()
        if total <= 0:
            return 100
        return max(0, min(100, round(decorrido / total * 100)))

    @property
    def sla_cor(self):
        if self.sla_pausado:
            return 'pausado'
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
        delta = self.prazo_sla - self._sla_referencia()
        segundos = delta.total_seconds()
        horas = int(abs(segundos) // 3600)
        minutos = int((abs(segundos) % 3600) // 60)
        texto = f'{horas}h {minutos}min'
        texto = f'Atrasado há {texto}' if segundos < 0 else f'{texto} restantes'
        return f'Pausado · {texto}' if self.sla_pausado else texto


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
    # Não é mais usada (anexos ficam no banco), mas a migration 0008 ainda a referencia.
    return f'chamados/{instance.chamado_id}/{filename}'


class Anexo(models.Model):
    """Arquivo anexado a um chamado. O arquivo em si é um `midia.Arquivo`: metadados no banco e
    binário no object storage, acessado direto pela URL pública (`anexo.arquivo.url`)."""

    QUANTIDADE_MAXIMA = 5  # por envio

    chamado = models.ForeignKey(Chamado, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.OneToOneField('midia.Arquivo', on_delete=models.PROTECT, related_name='anexo')
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em']
        verbose_name = 'Anexo'
        verbose_name_plural = 'Anexos'

    def __str__(self):
        return self.arquivo.nome_original

    @classmethod
    def criar(cls, chamado, arquivo_enviado, enviado_por):
        """Valida/otimiza e grava o arquivo no storage (midia) e o vincula ao chamado."""
        from midia.services import salvar_upload

        arquivo = salvar_upload(arquivo_enviado, enviado_por, somente_imagens=False)
        return cls.objects.create(chamado=chamado, arquivo=arquivo, enviado_por=enviado_por)

    @classmethod
    def criar_varios(cls, chamado, arquivos_enviados, enviado_por):
        """Tudo ou nada: se um arquivo for recusado, apaga do storage os que já tinham sido gravados
        e relança o erro (quem chama deve estar numa transação, para desfazer os registros)."""
        from django.core.files.storage import default_storage

        criados = []
        try:
            for arquivo_enviado in arquivos_enviados:
                criados.append(cls.criar(chamado, arquivo_enviado, enviado_por))
        except Exception:
            for anexo in criados:
                default_storage.delete(anexo.arquivo.storage_key)
            raise
        return criados


class ProcedimentoEntry(models.Model):
    """Linha do time do procedimento de atendimento — cada uma pública (visível ao
    solicitante) ou interna (restrita à equipe técnica), na ordem em que foi registrada."""

    class Tipo(models.TextChoices):
        PUBLICO = 'publico', 'Procedimento'
        INTERNO = 'interno', 'Nota interna'
        # Registrada pelo próprio solicitante ao responder um chamado "aguardando solicitante".
        RESPOSTA = 'resposta', 'Resposta do solicitante'

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
