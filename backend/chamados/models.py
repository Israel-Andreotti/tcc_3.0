from datetime import timedelta

from django.conf import settings
from django.db import connection, models
from django.utils import timezone


class Prioridade(models.TextChoices):
    BAIXA = 'baixa', 'Baixa'
    MEDIA = 'media', 'Média'
    ALTA = 'alta', 'Alta'
    CRITICA = 'critica', 'Crítica'


class TipoChamado(models.TextChoices):
    """ITIL: incidente = interrupção ou degradação de um serviço ("a internet caiu");
    requisição de serviço = pedido de algo padrão e previsto ("instalar o leitor de PDF")."""

    INCIDENTE = 'incidente', 'Incidente'
    REQUISICAO = 'requisicao', 'Requisição'


# Código de exibição do chamado: prefixo do tipo + número sequencial próprio de cada tipo
# (INC000001, REQ000001...). Os números vêm de sequências do PostgreSQL (criadas na migration
# 0021), seguras para aberturas simultâneas. O id interno (pk) continua sendo usado em URLs e FKs.
PREFIXO_CODIGO = {TipoChamado.INCIDENTE: 'INC', TipoChamado.REQUISICAO: 'REQ'}
SEQUENCIA_CODIGO = {TipoChamado.INCIDENTE: 'chamados_codigo_inc_seq', TipoChamado.REQUISICAO: 'chamados_codigo_req_seq'}
DIGITOS_CODIGO = 6


def formatar_codigo(tipo, numero):
    return f'{PREFIXO_CODIGO[tipo]}{numero:0{DIGITOS_CODIGO}d}'


def proximo_codigo(tipo):
    with connection.cursor() as cursor:
        cursor.execute('SELECT nextval(%s)', [SEQUENCIA_CODIGO[tipo]])
        return formatar_codigo(tipo, cursor.fetchone()[0])


# Da menor para a maior: usado para subir um nível de prioridade.
NIVEIS_PRIORIDADE = [Prioridade.BAIXA, Prioridade.MEDIA, Prioridade.ALTA, Prioridade.CRITICA]


def prioridade_do_chamado(prioridade_subcategoria, setor):
    """Prioridade de um chamado novo: a da subcategoria, um nível acima se o setor for crítico
    (crítica continua crítica)."""
    if setor is not None and setor.critico:
        indice = NIVEIS_PRIORIDADE.index(prioridade_subcategoria)
        return NIVEIS_PRIORIDADE[min(indice + 1, len(NIVEIS_PRIORIDADE) - 1)]
    return prioridade_subcategoria


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
    # Incidente ou requisição de serviço: herdado pelos chamados abertos nessa subcategoria.
    tipo = models.CharField(max_length=10, choices=TipoChamado.choices, default=TipoChamado.INCIDENTE)

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
        FECHADO = 'fechado', 'Fechado'

    Prioridade = Prioridade
    Tipo = TipoChamado

    # Prazo de SLA (em horas) por prioridade, usado para calcular `prazo_sla`.
    SLA_HORAS = {
        Prioridade.CRITICA: 4,
        Prioridade.ALTA: 8,
        Prioridade.MEDIA: 24,
        Prioridade.BAIXA: 72,
    }

    # Solicitantes marcados como VIP têm o prazo de SLA reduzido nesse percentual.
    VIP_SLA_MULTIPLICADOR = 0.75

    # Avaliação do atendimento (1 a 5) -> classificação e grupo usados no pop-up, na linha do tempo e no CSAT.
    CLASSIFICACAO_AVALIACAO = {
        5: ('Muito satisfeito', 'satisfeitos'),
        4: ('Satisfeito', 'satisfeitos'),
        3: ('Neutro', 'neutros'),
        2: ('Insatisfeito', 'insatisfeitos'),
        1: ('Muito insatisfeito', 'insatisfeitos'),
    }

    # Depois que o técnico fecha o chamado, o solicitante tem esse prazo para reabri-lo; passado o
    # prazo, o fechamento é definitivo.
    DIAS_REABERTURA = 1

    titulo = models.CharField(max_length=150)
    descricao = models.TextField()
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.ABERTO)
    # Incidente ou requisição: copiado da subcategoria na abertura (ver save()).
    tipo = models.CharField(max_length=10, choices=TipoChamado.choices, default=TipoChamado.INCIDENTE)
    # Código mostrado ao usuário (INC000001 / REQ000001), gerado na abertura conforme o tipo.
    codigo = models.CharField(max_length=12, unique=True, editable=False)
    # Nunca definida por formulário de usuário: vem da subcategoria na abertura, um nível acima se o
    # setor do chamado for crítico (ver save() e prioridade_do_chamado).
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
    # Quando o técnico fechou o chamado (o último fechamento, se foi reaberto). Vazio enquanto aberto.
    fechado_em = models.DateTimeField(null=True, blank=True)
    # Pausa do SLA enquanto o chamado aguarda o solicitante: ao retomar, o tempo parado é
    # somado em `sla_tempo_pausado` e o `prazo_sla` é estendido na mesma medida.
    sla_pausado_em = models.DateTimeField(null=True, blank=True)
    sla_tempo_pausado = models.DurationField(default=timedelta(0))
    # Quando o solicitante respondeu e o técnico responsável ainda não abriu o chamado (notificação).
    resposta_solicitante_em = models.DateTimeField(null=True, blank=True)

    # ---- Dados para os indicadores de gestão (app indicadores) ----
    # Primeira atribuição a um técnico (tempo médio de atendimento = atribuição -> resolução).
    atribuido_em = models.DateTimeField(null=True, blank=True)
    # Primeira comunicação pública da equipe com o solicitante (FTR = abertura -> primeira resposta).
    primeira_resposta_em = models.DateTimeField(null=True, blank=True)
    # O último fechamento foi dentro do prazo de SLA? (nível de serviço)
    fechado_no_prazo = models.BooleanField(null=True, blank=True)
    # Quantas vezes o solicitante disse que não foi resolvido (taxa de reabertura).
    reaberturas = models.PositiveIntegerField(default=0)
    # O técnico precisou pedir informação ao solicitante (não conta como resolução no primeiro contato).
    pediu_info = models.BooleanField(default=False)
    # Avaliação do solicitante depois do fechamento, de 1 a 5 (CSAT). Zerada se o chamado for reaberto.
    avaliacao = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'{self.codigo} {self.titulo}'

    def save(self, *args, **kwargs):
        # Só na abertura: a prioridade da subcategoria pode mudar depois (catálogo), e o chamado
        # já aberto mantém a prioridade com que foi aberto — coerente com o prazo de SLA já calculado.
        if self._state.adding and self.subcategoria_id:
            self.prioridade = prioridade_do_chamado(self.subcategoria.prioridade, self.setor)
            self.tipo = self.subcategoria.tipo
        if not self.codigo:
            self.codigo = proximo_codigo(self.tipo)
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

    # ---- Eventos do atendimento (também alimentam os indicadores) ----

    def registrar_evento(self, tipo, autor, descricao, publico=True):
        """Grava um evento no log do ciclo de vida (o chamado precisa já estar salvo)."""
        return EventoChamado.objects.create(
            chamado=self, tipo=tipo, autor=autor, descricao=descricao[:255], publico=publico
        )

    def atribuir(self, tecnico):
        """Atribui o chamado a um técnico (pegar ou reatribuir). Não salva."""
        self.atendente = tecnico
        if self.atribuido_em is None:
            self.atribuido_em = timezone.now()
        if self.status == self.Status.ABERTO:
            self.status = self.Status.EM_ANDAMENTO

    def registrar_primeira_resposta(self):
        """Marca a primeira comunicação pública da equipe com o solicitante. Não salva."""
        if self.primeira_resposta_em is None:
            self.primeira_resposta_em = timezone.now()

    # ---- Ciclo de encerramento: em andamento -> fechado (técnico) -> reaberto (solicitante) ----

    def fechar(self):
        """Técnico concluiu o atendimento e fecha o chamado. O SLA fica pausado: se o solicitante
        reabrir, o relógio volta de onde parou. Não salva."""
        self.retomar_sla()  # fecha uma pausa anterior (aguardando solicitante), se houver
        self.fechado_no_prazo = bool(self.prazo_sla and timezone.now() <= self.prazo_sla)
        self.registrar_primeira_resposta()  # fechar sem nenhum registro antes também é responder
        self.pausar_sla()
        self.status = self.Status.FECHADO
        self.fechado_em = timezone.now()

    def reabrir(self):
        """Solicitante disse que não foi resolvido: volta para o técnico, com o SLA retomado. A
        avaliação anterior é descartada (vale a do próximo fechamento). Não salva."""
        self.retomar_sla()
        self.status = self.Status.EM_ANDAMENTO
        self.fechado_em = None
        self.fechado_no_prazo = None
        self.avaliacao = None
        self.reaberturas += 1
        self.resposta_solicitante_em = timezone.now()  # avisa o técnico responsável

    @classmethod
    def prazo_reabertura_display(cls):
        """'1 dia' / '3 dias' — prazo de reabertura por extenso para as mensagens."""
        return f'{cls.DIAS_REABERTURA} dia{"s" if cls.DIAS_REABERTURA != 1 else ""}'

    @property
    def prazo_reabertura(self):
        """Até quando o solicitante pode reabrir o chamado fechado."""
        if self.status == self.Status.FECHADO and self.fechado_em:
            return self.fechado_em + timedelta(days=self.DIAS_REABERTURA)
        return None

    @property
    def pode_reabrir(self):
        prazo = self.prazo_reabertura
        return bool(prazo and timezone.now() <= prazo)

    @classmethod
    def respostas_nao_vistas(cls, tecnico):
        """Chamados abertos do técnico em que o solicitante respondeu e ele ainda não abriu."""
        return cls.objects.filter(atendente=tecnico, resposta_solicitante_em__isnull=False).exclude(
            status=cls.Status.FECHADO
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
        if self.status == self.Status.FECHADO:
            return False
        return bool(self.prazo_sla and self._sla_referencia() > self.prazo_sla)

    @property
    def encerrado(self):
        """Chamado fechado fica somente leitura: nenhuma ação da equipe é aceita."""
        return self.status == self.Status.FECHADO

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
        if self.sla_pausado:
            # Aguardando o solicitante: o relógio está parado, o tempo restante não é relevante.
            return 'Pausado'
        segundos = (self.prazo_sla - timezone.now()).total_seconds()
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


class EventoChamado(models.Model):
    """Registro (auditoria) do ciclo de vida do chamado: cada mudança de estado — atribuição,
    pausa, resolução, reabertura, fechamento... — com quem fez e quando. Exibido na linha do tempo
    junto com os procedimentos. `autor` vazio = ação automática do sistema."""

    class Tipo(models.TextChoices):
        ABERTURA = 'abertura', 'Abertura'
        ATRIBUICAO = 'atribuicao', 'Atribuição'
        REATRIBUICAO = 'reatribuicao', 'Reatribuição'
        AGUARDANDO = 'aguardando', 'Aguardando solicitante'
        RETOMADO = 'retomado', 'Atendimento retomado'
        RESPONDIDO = 'respondido', 'Resposta do solicitante'
        # Só em chamados antigos: antes, o técnico "resolvia" e o fechamento vinha depois.
        RESOLVIDO = 'resolvido', 'Resolução'
        REABERTO = 'reaberto', 'Reabertura'
        FECHADO = 'fechado', 'Fechamento'
        AVALIADO = 'avaliado', 'Avaliação'
        MOVIMENTACAO = 'movimentacao', 'Movimentação de ativo'

    ICONES = {
        'abertura': 'bi-plus-circle', 'atribuicao': 'bi-person-check', 'reatribuicao': 'bi-arrow-left-right',
        'aguardando': 'bi-pause-circle', 'retomado': 'bi-play-circle', 'respondido': 'bi-reply',
        'resolvido': 'bi-check-circle', 'reaberto': 'bi-arrow-counterclockwise', 'fechado': 'bi-lock',
        'avaliado': 'bi-star', 'movimentacao': 'bi-pc-display',
    }

    chamado = models.ForeignKey(Chamado, on_delete=models.CASCADE, related_name='eventos')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    descricao = models.CharField(max_length=255)
    # Eventos internos (ex.: movimentação de ativo) aparecem só para a equipe.
    publico = models.BooleanField(default=True)
    criado_em = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['criado_em', 'pk']
        verbose_name = 'Evento do chamado'
        verbose_name_plural = 'Eventos do chamado'

    def __str__(self):
        return f'{self.get_tipo_display()} em #{self.chamado_id}'

    @property
    def icone(self):
        return self.ICONES.get(self.tipo, 'bi-dot')

    @property
    def autor_display(self):
        if self.autor is None:
            return 'Sistema'
        return self.autor.get_full_name() or self.autor.username

