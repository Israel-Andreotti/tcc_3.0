# Melhorias propostas com base no ITIL 4

Análise do sistema de chamados à luz das práticas do ITIL 4: o que já está alinhado e o que
pode ser melhorado. Os itens estão numerados para referência; a coluna **Situação** é atualizada
conforme forem implementados.

## O que já está alinhado ao ITIL

| Prática ITIL | Como o sistema atende |
|---|---|
| Central de Serviços (Service Desk) | Ponto único de contato: abertura de chamados, fila da equipe, atribuição e linha do tempo do atendimento |
| Gerenciamento de Nível de Serviço | SLA por prioridade, pausa quando a espera é do usuário, nível de serviço medido no painel |
| Catálogo de Serviços | Categorias e subcategorias com prioridade padrão, editáveis pelo administrador |
| Gerenciamento de Incidentes | Registro → atribuição → diagnóstico → resolução → confirmação pelo usuário → fechamento, com reabertura |
| Gestão de Ativos de TI | Patrimônio, lotação (setor ou funcionário) e trilha de auditoria de todas as movimentações |
| Medição e Relatórios | Painel com FTR, tempos médios de atendimento e resolução, resolução no 1º contato, reabertura, nível de serviço e CSAT |

## Pontos de melhoria

| # | Melhoria | Prática ITIL | Situação |
|---|---|---|---|
| 1 | Incidente × Requisição de Serviço | Gerenciamento de Incidentes / de Requisições | **Implementado** |
| 2 | Prioridade por matriz Impacto × Urgência | Gerenciamento de Incidentes | Proposto |
| 3 | Registro completo do ciclo de vida (log de eventos) | Gerenciamento de Incidentes / auditoria | **Implementado** |
| 4 | Escalonamento funcional e hierárquico | Central de Serviços / Nível de Serviço | Proposto |
| 5 | Código de resolução e Base de Conhecimento | Gerenciamento do Conhecimento | Proposto |
| 6 | Gerenciamento de Problemas | Gerenciamento de Problemas | Proposto |
| 7 | SLA em horário útil e SLA de primeira resposta | Gerenciamento de Nível de Serviço | Proposto |
| 8 | Itens de configuração (CMDB) ligados aos chamados | Gerenciamento de Configuração | Proposto |
| 9 | Comunicação por e-mail | Central de Serviços | Proposto |
| 10 | Incidente Grave (Major Incident) | Gerenciamento de Incidentes | Proposto |

### 1. Diferenciar Incidente de Requisição de Serviço — implementado

O ITIL separa **incidente** (interrupção ou degradação de um serviço: "a internet caiu") de
**requisição de serviço** (pedido de algo padrão e previsto: "instalar o leitor de PDF", "reset
de senha"). Hoje tudo é tratado como "chamado".

**Implementado:** cada subcategoria do catálogo tem um *tipo* (incidente ou requisição), editável
pelo administrador na tela da categoria e herdado pelo chamado na abertura. O tipo aparece na
abertura (com a explicação), no catálogo, na fila (com filtro), no histórico e no detalhe do chamado.
O painel de indicadores tem filtro por tipo e a comparação "Incidentes × requisições" (volume, nível
de serviço e tempo médio de resolução). O catálogo existente foi classificado: pedidos padrão (reset
de senha, instalações, acessos, toner, ponto de rede...) como requisição; falhas como incidente.

**Evolução possível:** SLA próprio para requisições (hoje o SLA segue só a prioridade).

### 2. Prioridade por matriz Impacto × Urgência

No ITIL a prioridade resulta do cruzamento de **impacto** (quantas pessoas ou serviços são
afetados) com **urgência** (quanto tempo o negócio suporta a interrupção). Hoje a prioridade vem
da subcategoria, com o setor crítico subindo um nível — uma aproximação do impacto.

**Proposta:** na abertura, o solicitante informa o alcance ("só eu / meu setor / vários setores")
e a urgência; o sistema calcula a prioridade pela matriz, e o setor crítico continua pesando no
impacto.

### 3. Registro completo do ciclo de vida (log de eventos) — implementado

A linha do tempo registrava procedimentos e respostas, mas não as mudanças de estado do chamado
(atribuições, reatribuições, pausas, resolução, reabertura, fechamento) nem quem as fez e quando.
Para o ITIL e para auditoria, o histórico do incidente deve ser completo.

**Implementado:** cada ação gera automaticamente um evento (quem, o quê, quando), exibido na
linha do tempo do chamado junto com os procedimentos. Os chamados antigos receberam os eventos que
puderam ser reconstruídos (abertura, resolução e fechamento).

### 4. Escalonamento funcional e hierárquico

- **Funcional:** níveis de suporte (N1 → N2 → N3) ou grupos especializados (Redes, Sistemas,
  Suporte de campo), com filas por grupo em vez de uma fila única.
- **Hierárquico:** alerta automático ao gestor quando o SLA de um chamado passa de 70% ou 90%,
  antes de estourar.

### 5. Código de resolução e Base de Conhecimento

Ao resolver, o técnico não registra como resolveu nem qual foi a causa.

**Proposta:** exigir, na resolução, um código de causa/solução (configuração, hardware, erro do
usuário, falha de sistema...) e um resumo da solução. Com isso, montar uma base de conhecimento:
soluções reaproveitáveis sugeridas ao técnico e ao solicitante na abertura (autoatendimento).

### 6. Gerenciamento de Problemas

Vários incidentes com a mesma causa (por exemplo, dez chamados de "Wi-Fi da ala B") indicam um
**problema**. O ITIL prevê registrar o problema, investigar a **causa raiz** e documentar o
**erro conhecido** e a **solução de contorno**.

**Proposta:** registro de problemas com vários chamados vinculados; o painel aponta categorias e
setores com incidentes recorrentes como candidatos a problema.

### 7. SLA em horário útil e SLA de primeira resposta

O SLA conta 24 horas por dia, 7 dias por semana. Faz sentido para setores 24h (UTI, Emergência),
mas não para os administrativos.

**Proposta:** calendário de expediente e feriados, com o SLA contando apenas em horário útil
(configurável por setor ou prioridade); medir também o SLA de **primeira resposta**, além do de
resolução.

### 8. Itens de configuração (CMDB) ligados aos chamados

O chamado já tem um campo `ativo`, mas ele não é usado em nenhuma tela. No ITIL o incidente aponta
o **item de configuração afetado** ("o notebook 100006 da Juliana").

**Proposta:** informar o ativo afetado ao abrir ou atender o chamado e mostrar o histórico de
chamados de cada ativo, revelando equipamentos problemáticos.

### 9. Comunicação por e-mail

Os avisos existem apenas dentro do sistema. O ITIL reforça manter o usuário informado nos marcos do
atendimento (aberto, aguardando você, resolvido).

**Proposta:** e-mails nos eventos principais (depende de configurar um serviço de envio).

### 10. Incidente Grave (Major Incident)

Quando algo crítico afeta muitos usuários (por exemplo, o prontuário eletrônico fora do ar), o
ITIL prevê um fluxo próprio: destaque na fila, comunicação centralizada e vínculo dos chamados
duplicados ao incidente principal.

## Prioridade sugerida

Pela relação entre esforço e valor para o TCC: **1** (implementado), **2**, **3** (implementado) e **5**. Os
itens 4, 6 e 7 agregam bastante, mas exigem mais trabalho; o 9 depende de infraestrutura de
e-mail.
