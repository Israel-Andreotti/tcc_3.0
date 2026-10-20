# Helpdesk TI — Sistema de Gerenciamento de Chamados

TCC: central de serviços (service desk) de TI voltada a um ambiente hospitalar, com abertura e
atendimento de chamados, SLA, catálogo de serviços, gestão de ativos e painel de indicadores,
seguindo práticas do ITIL 4.

**Em produção:** https://tcc30-production.up.railway.app

Django 5.2 full-stack (templates renderizados no servidor + Bootstrap 5), PostgreSQL, sem API REST
nem frontend separado.

## Funcionalidades

**Chamados**
- Abertura pelo catálogo de serviços (categoria → subcategoria). Cada subcategoria define a
  **prioridade** e o **tipo** ITIL do chamado: *incidente* (algo parou de funcionar) ou
  *requisição* (pedido de algo previsto). O usuário nunca escolhe a prioridade; setores marcados
  como **críticos** (UTI, Emergência...) sobem um nível.
- Código legível por tipo: `INC000001`, `REQ000001`.
- **SLA** por prioridade (horas editáveis pelo administrador), desconto para solicitantes VIP,
  barra de consumo e alerta de estouro. O SLA **pausa** enquanto o chamado aguarda o solicitante.
- Fila da equipe com filtros, busca, seis ordenações (urgência, % do SLA consumido, prioridade...)
  e **atualização automática** quando chega algo novo. "Atribuir a mim" é seguro contra dois
  técnicos clicando ao mesmo tempo.
- Fluxo: aberto → em andamento → (aguardando solicitante) → fechado. Depois de fechado, o
  solicitante pode **reabrir** em até 1 dia e **avaliar** o atendimento (1 a 5 estrelas).
- Linha do tempo com procedimentos públicos, notas internas (só a equipe vê) e o **log de eventos**
  de todo o ciclo de vida (quem fez o quê e quando).
- Notificações dentro do sistema: aviso ao solicitante quando precisam dele e avisos ao técnico
  quando o solicitante responde.

**Ativos**
- Cadastro com número de patrimônio automático; cada ativo fica em um setor **ou** com um funcionário.
- Movimentação pelo chamado (entrega e devolução), validada ao vivo e efetivada só quando o chamado
  é fechado.
- **Trilha de auditoria** completa de toda mudança de lotação (origem, destino, quem e quando).

**Indicadores** (`/indicadores/`)
- **Visão executiva** (administrador): volume, nível de serviço, tempo até a primeira resposta,
  tempos de atendimento e resolução, resolução no primeiro contato, taxa de reabertura, satisfação
  (CSAT), comparação incidentes × requisições e desempenho por técnico, setor e categoria.
- **Visão operacional** (técnicos): fila agora, chamados sem técnico, SLA estourado, carga e
  chamados parados por técnico.
- Filtros por período, técnico, setor, categoria e tipo.

**Usuários e segurança**
- Perfis: solicitante, técnico e administrador (detalhes abaixo).
- Senha temporária gerada pelo sistema e troca obrigatória no primeiro acesso.
- Bloqueio de login por 15 minutos após 5 senhas erradas seguidas.
- Sessão encerrada após 30 minutos sem uso e ao fechar o navegador.
- Em produção: HTTPS com HSTS, cookies seguros e logs de erro.

## Perfis de usuário

| Perfil | O que pode fazer |
|---|---|
| **Solicitante** | Abre chamados e acompanha apenas os próprios; responde, reabre e avalia |
| **Técnico** | Atende a fila, gerencia ativos e usuários, vê a visão operacional dos indicadores |
| **Administrador** | Tudo do técnico + catálogo de serviços, SLA, setores, exclusão de ativos e visão executiva |

Existe ainda o **superadministrador** (concedido apenas pelo admin do Django), que não aparece na
lista de usuários e não pode ser alterado pela aplicação.

## Estrutura do projeto

```
backend/
├── config/        # settings, urls raiz, wsgi
├── core/          # mixins de permissão (RBAC), middlewares (troca de senha, sessão inativa), filtros de template
├── usuarios/      # usuário customizado (perfil, matrícula, setor), setores, login e gestão de usuários
├── chamados/      # catálogo, SLA, chamados, procedimentos, log de eventos e todo o fluxo de atendimento
├── ativos/        # ativos e movimentações (trilha de auditoria)
├── indicadores/   # painel de gestão; todas as fórmulas em metricas.py
├── templates/     # templates HTML por app
├── static/        # CSS próprio
└── tests/         # testes automatizados, separados por área
docs/melhorias-itil.md   # análise ITIL: o que já atende e melhorias propostas
```

## Rodando localmente

Pré-requisitos: **Python 3.11** e **PostgreSQL 14+**.

```bash
# na raiz do projeto
python -m venv venv
venv\Scripts\activate          # Windows (cmd/PowerShell)
source venv/Scripts/activate   # Windows (Git Bash)
source venv/bin/activate       # Linux/Mac

cd backend
pip install -r requirements-dev.txt   # dependências da aplicação + ferramentas de teste
cp .env.example .env                  # ajuste as credenciais do PostgreSQL
createdb tcc_chamados                 # ou crie o banco pelo pgAdmin
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

No Windows, depois da instalação, basta dar duplo clique em `run.bat`, na raiz do projeto.

Acesse http://127.0.0.1:8000/usuarios/login/. Técnicos e administradores entram na fila de
chamados e solicitantes vão direto para a abertura de chamado. O admin do Django fica em `/admin/`.

As migrations já criam dados iniciais: catálogo de serviços, prazos de SLA, setores e alguns
chamados e usuários de demonstração.

### Variáveis do `.env`

| Variável | Para que serve | Padrão |
|---|---|---|
| `SECRET_KEY` | Chave secreta do Django | valor de desenvolvimento |
| `DEBUG` | Modo de desenvolvimento | `True` |
| `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` | Domínios aceitos | `localhost,127.0.0.1` / vazio |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL local | `tcc_chamados`, `postgres`, `postgres`, `localhost`, `5432` |
| `DATABASE_URL` | Banco de produção; tem prioridade sobre as `DB_*` | — |
| `LOGIN_RAPIDO` | Só para testes locais: botões "Entrar como..." sem senha. Só funciona com `DEBUG=True` | `False` |
| `SESSAO_INATIVIDADE_MINUTOS` | Minutos sem uso até a sessão expirar | `30` |
| `LOG_LEVEL` | Nível dos logs do Django | `WARNING` |

## Testes

```bash
cd backend
python manage.py test                              # suíte completa (precisa do PostgreSQL local)
python manage.py test tests.chamados.test_sla      # um módulo
coverage run manage.py test && coverage report     # com cobertura
```

São cerca de 180 testes em `backend/tests/`, separados por área (SLA, códigos, fluxo de
atendimento, fechamento, atribuição concorrente, permissões, fila, catálogo, ativos, usuários,
indicadores e segurança), com cobertura de 99%. As fórmulas dos indicadores são conferidas contra
um cenário com resultados calculados à mão.

A cada push na `master` e em cada pull request, o **GitHub Actions** sobe um PostgreSQL, verifica
o projeto e as migrations e roda a suíte com cobertura (`.github/workflows/testes.yml`).

## Deploy (Railway)

Projeto no [Railway](https://railway.com) (plano Hobby) com dois serviços: **Postgres** e o
repositório. Todo push na `master` gera um deploy automático.

| Configuração do serviço | Valor |
|---|---|
| Root Directory | `/backend` |
| Custom Start Command | `bash start.sh` |
| Healthcheck Path | `/usuarios/login/` |
| Public Networking | domínio gerado na porta `8080` |

| Variável de ambiente | Valor |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `.up.railway.app,healthcheck.railway.app` (o segundo é exigido pelo healthcheck) |
| `CSRF_TRUSTED_ORIGINS` | `https://*.up.railway.app` |
| `PORT` | `8080` |
| `SECRET_KEY` | valor aleatório: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` | administrador inicial |

A cada inicialização, `backend/start.sh` roda `collectstatic`, aplica as migrations,
cria ou atualiza o administrador inicial (sincronizando a senha com `DJANGO_SUPERUSER_PASSWORD`) e
sobe o gunicorn. Os logs de erro aparecem na aba **Deploy Logs** do serviço.

### Backup do banco de produção

`backup_railway.bat`, na raiz do projeto, salva um `.dump` do banco do Railway em
`Documents\tcc_backups`. O script pede a **DATABASE_PUBLIC_URL**, que fica em
Railway > Postgres > Variables. Para restaurar num banco local:

```bash
createdb tcc_restaurado
pg_restore --no-owner --no-acl -d tcc_restaurado caminho\do\arquivo.dump
```
