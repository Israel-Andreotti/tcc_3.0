# CLAUDE.md

Service desk / helpdesk de TI (TCC). Django 5.2 full-stack: server-rendered templates + Bootstrap 5 via CDN, no separate frontend, no REST API. All code, UI text, model/field names and commit messages are in **Portuguese** — keep it that way.

## Commands

All Django commands run from `backend/` with the root `venv/` activated.

```bash
cd backend
python manage.py runserver          # or double-click run.bat at repo root
python manage.py makemigrations && python manage.py migrate
python manage.py test               # real tests only in chamados/tests.py (incl. a concurrency test for "Atribuir a mim"); other tests.py are stubs
python manage.py test chamados      # single app
python manage.py check
```

Config comes from `backend/.env` via `python-decouple` (template: `backend/.env.example`). For local testing, `LOGIN_RAPIDO=True` in `.env` adds an "Entrar como..." one-click passwordless login to the login page (`usuarios:login_rapido`) and disables the forced password change; `settings.LOGIN_RAPIDO` is `DEBUG and LOGIN_RAPIDO`, so it can never be active in production (`DEBUG=False`) — keep it that way. PostgreSQL only (no SQLite): `config/settings.py` uses `DATABASE_URL` when set (prod/Railway), otherwise the `DB_*` variables (local Postgres, database `tcc_chamados`).

## Deploy (Railway)

Railway project (Hobby plan) with two services: `Postgres` and the GitHub repo (`tcc_3.0`), auto-deployed on every push to `master`; live at https://tcc30-production.up.railway.app. Service settings live in the Railway UI (not in the repo): Root Directory `/backend`, start command `bash start.sh`, healthcheck path `/usuarios/login/`, domain on port 8080. Env vars: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `DEBUG=False`, `ALLOWED_HOSTS=.up.railway.app,healthcheck.railway.app` (the healthcheck host is required or Django answers 400 and the deploy fails), `CSRF_TRUSTED_ORIGINS=https://*.up.railway.app`, `PORT=8080`, `SECRET_KEY`, `DJANGO_SUPERUSER_*`. Railpack builds it (Python from `.python-version`). `start.sh` runs on every boot: `collectstatic` → `migrate` → upsert the `DJANGO_SUPERUSER_USERNAME` user as superuser/administrador and **reset its password from `DJANGO_SUPERUSER_PASSWORD`** → gunicorn on `$PORT`. `.gitattributes` keeps `*.sh`/`Procfile` with LF endings (repo is developed on Windows). With `DEBUG=False`, settings trust `X-Forwarded-Proto` and use secure cookies; `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` come from env. Static files via WhiteNoise (`CompressedManifestStaticFilesStorage` — a template referencing a missing static file will 500 in prod). There is no file upload feature (attachments were removed on purpose); `chamados/migrations/0008_anexo.py` keeps a local `anexo_upload_path` only so the historical migration still loads, and `0014_remove_anexo` drops the table.

## Architecture

```
backend/
  config/     settings, root urls
  core/       dashboard, RBAC mixins, ForcarTrocaSenhaMiddleware, template filters (chamado_extras)
  usuarios/   custom user model Usuario (AUTH_USER_MODEL), Setor, login/senha, user management
  chamados/   Categoria/Subcategoria (service catalog), SLAPrioridade, Chamado, Comentario, ProcedimentoEntry
  ativos/     Ativo (equipment) and MovimentacaoAtivo
  indicadores/ management dashboard (no models): metricas.py computes everything, one staff-only view
  templates/  all templates, per app subfolder; base.html holds the navbar + shared JS (user info modal, etc.)
  static/css/style.css   custom styles (status-*/prioridade-* badge classes)
```

Views are class-based (generic CBVs, plus plain `View` with `post()` for actions); every action ends with `messages.*` + `redirect`. URLs are namespaced (`core:`, `usuarios:`, `chamados:`, `ativos:`).

### Roles / RBAC

`Usuario.perfil`: `solicitante` (default), `atendente` (displayed as **"Técnico"**), `administrador`. Access is enforced with mixins in [core/mixins.py](backend/core/mixins.py):
- `AtendenteRequiredMixin` → atendente + administrador (chamado queue/actions, user management, ativos CRUD)
- `AdministradorRequiredMixin` → administrador only (catálogo/SLA editing, setores, deleting ativos)
- Solicitantes only see their own chamados — enforced by filtering `get_queryset()` in list/detail views.

`super_admin=True` (granted only via Django admin) forces `perfil=administrador` in `save()`, hides the user from the user list, and blocks edit/reset/deactivate from the app UI. Other admins have no restrictions between each other.

Login redirects by role (`perfil_redirect_url`): staff → `chamados:list`, solicitante → `chamados:create`. New users and password resets get a random temporary password shown once on `usuario_resumo.html` and `deve_trocar_senha=True`; `ForcarTrocaSenhaMiddleware` then locks them into `usuarios:trocar_senha` until changed. `matricula` is auto-generated sequentially starting at `100001`.

### Chamados — key business rules

- **Priority is never chosen by users**: `Chamado.save()` sets it **only on creation** (`_state.adding`) via `prioridade_do_chamado()`: the subcategoria's priority, raised one level if the chamado's `Setor.critico` is set (admin toggles it on the Setores page; crítica stays crítica). The SLA follows the resulting priority (VIP discount still applies on top). Set only on creation, so later changes to a subcategoria's priority don't alter open chamados (their SLA was already computed). Title is set to the subcategoria name on create.
- **Incidente × requisição (ITIL)**: `TipoChamado` (`incidente`/`requisicao`) lives on `Subcategoria.tipo` (admin edits it on `categoria_editar` via `chamados:subcategoria_tipo`) and is copied to `Chamado.tipo` on creation, like priority. Shown with the `{% tipo_badge %}` inclusion tag (icon + text); the queue and the indicadores panel filter by `?tipo=`; the executive view compares both types. Migration `0020` classified the seeded catalog by name.
- **Chamado code**: users see `Chamado.codigo` (`INC000001` / `REQ000001`), never the pk — generated in `save()` on creation from the type, each type with its own PostgreSQL sequence (`chamados_codigo_inc_seq` / `_req_seq`, created in migration `0021`; concurrency-safe, may leave gaps). The pk still drives URLs and FKs. Search (`filtro_busca_chamado`) accepts the full code, `inc16` or just the number. Always display `codigo`, not `#{{ pk }}`.
- **SLA**: `prazo_sla` is set once on first save = now + hours from `SLAPrioridade` (DB, admin-editable; seeded by migration `0011`), falling back to `Chamado.SLA_HORAS`. VIP solicitantes get `× 0.75`. Display helpers: `sla_percentual`, `sla_cor`, `sla_estourado`, `sla_tempo_restante_display`.
- Status flow: `aberto` → `em_andamento` (when a técnico "pega" or is reatribuído) → `fechado` (técnico closes via `chamados:fechar` → `Chamado.fechar()`: sets `fechado_em`/`fechado_no_prazo` and pauses the SLA). There is **no "resolvido" status and no confirmation step** (removed in migration `0023`, which turned old `resolvido` chamados into `fechado` and renamed `resolvido_em`/`resolvido_no_prazo` to `fechado_em`/`fechado_no_prazo`). Within `Chamado.DIAS_REABERTURA` days of closing (`pode_reabrir`/`prazo_reabertura`; use `Chamado.prazo_reabertura_display()` in messages) the solicitante may reopen with a reason (`reabrir` → `reabrir()`: back to `em_andamento`, SLA resumed/extended, `fechado_em` and `avaliacao` cleared, técnico notified via `resposta_solicitante_em`); the técnico then closes it again. After the deadline the close is final. The técnico queue excludes `fechado` (those appear in `historico/`) and has an "Ordenar por" select (`?ordem=`, options in `ORDENACOES_CHAMADO` in chamados/views.py): `urgencia` (default for staff: SLA-paused last, then `prazo_sla` ascending, overdue first — also the tie-breaker of the other options), `consumido` (% of SLA used, highest first — computed in SQL by `anotacao_sla_consumido()` with the same rule as `Chamado.sla_percentual`; PostgreSQL-specific `EXTRACT(EPOCH ...)`), `categoria`, `prioridade`, `recentes` (default for solicitante), `antigos`. The chosen ordering is remembered in the session (`fila_chamados_ordem`, until logout), so it survives reloads and navigating away. Pagination links keep the current filters (`filtros_querystring`). The staff queue auto-refreshes: the page polls `chamados:fila_versao` every 15s (JSON with `versao_fila()` = count/max id/max `atualizado_em` of open chamados) and reloads when it changes, unless the tab is hidden or a form field is focused. "Atribuir a mim" (`ChamadoPegarView`) only takes unassigned chamados, under `select_for_update(of=('self',))`, so concurrent clicks can't steal an assignment (changing owner is what "Reatribuir" is for). Once `chamado.encerrado` (fechado) it is read-only: action views use `ChamadoEditavelMixin` (server-side block) and the detail template gates forms on `pode_editar`.
- `aguardando_solicitante`: técnico enters it via `aguardar_solicitante` (requires a public message) and leaves via `retomar`; the solicitante leaves it by replying (`responder`, creates a `ProcedimentoEntry` of tipo `resposta`). While waiting the SLA is **paused**: `pausar_sla()`/`retomar_sla()` on `Chamado` track `sla_pausado_em`/`sla_tempo_pausado` and extend `prazo_sla` by the paused time; all SLA properties use `_sla_referencia()` so they freeze during a pause. Closing a paused chamado closes the pause first.
- Notifications (no email): solicitante sees a modal/banner in "Meus chamados" + navbar badge for chamados needing their action (`pendencias_solicitante`: chamados `aguardando_solicitante`). A reply sets `resposta_solicitante_em`; the assigned técnico gets non-blocking toasts via `base.html` polling `chamados:notificacoes` (JSON, every 30s) + navbar badge + "Nova resposta" row badge; cleared when that técnico opens the chamado (`ChamadoDetailView.get`). Counts come from simple tags in `core/templatetags/chamado_extras.py` and `Chamado.respostas_nao_vistas()`.
- `ProcedimentoEntry` holds the attendance content (procedures/notes/replies): `publico` entries are visible to the solicitante, `interno` only to staff.
- **Lifecycle audit log** (`EventoChamado`): every state change is recorded with who/what/when — abertura, atribuição, reatribuição, aguardando, retomado, respondido, reaberto, fechado, avaliado (tipo `resolvido` and automatic closes with `autor=None` = "Sistema" only exist in old chamados), movimentação de ativo (`publico=False`, staff only). Record new state changes with `chamado.registrar_evento(tipo, autor, descricao, publico=True)` after saving; descriptions start with a verb because the timeline renders "<autor> <descrição>". The detail page merges procedimentos + eventos chronologically (`linha_do_tempo`); the Django admin shows them read-only. Migration `0019` reconstructed abertura/atribuição/resolução/fechamento for old chamados. Proposed ITIL improvements are tracked in `docs/melhorias-itil.md`.
- Service catalog (Categoria → Subcategoria) is seeded by migration `0003_seed_catalogo` (healthcare-oriented IT catalog). Categoria/Subcategoria/Chamado FKs use `PROTECT`; delete views catch `ProtectedError`. The catalog list only shows an "Editar" button per categoria; renaming the categoria and adding/deleting subcategorias or changing their priority (`chamados:subcategoria_prioridade`) all happen on `chamados:categoria_editar` (admin only). Categorias cannot be deleted in the app (only via Django admin).

### Indicadores (management dashboard)

`/indicadores/` (`indicadores:painel`, staff only) has two views (`?visao=`): **executiva** (admin only — técnicos are always served the operational view; period-based KPIs + Chart.js charts via cdnjs) and **operacional** (current queue: unassigned, SLA overdue, load and stuck chamados per técnico — the period filter doesn't apply). Filters: period (7/30/90/365 days or custom `de`/`ate`), técnico, setor (departamento), categoria (tipo de incidente) — parsed by `Filtros.do_request`. All math lives in `indicadores/metricas.py` (definitions in its docstring): volume metrics use `criado_em`, resolution metrics use `fechado_em`. They depend on event fields on `Chamado` filled by model methods — keep using them instead of setting fields directly: `atribuir()` (`atribuido_em`), `registrar_primeira_resposta()` (`primeira_resposta_em`, on the first public staff entry, aguardar or resolve), `fechar()` (`fechado_no_prazo`), `reabrir()` (`reaberturas`); `pediu_info` is set in the aguardar view and `avaliacao` (1–5, CSAT) via `chamados:avaliar` — a closed, unrated chamado shows the solicitante an "Avaliar atendimento" card (star-rating modal, also auto-opened by `?avaliar=1`; optional comment goes to the timeline); one rating per close (reopening clears it). Rating labels/groups live in `Chamado.CLASSIFICACAO_AVALIACAO` (5 muito satisfeito, 4 satisfeito, 3 neutro, 2 insatisfeito, 1 muito insatisfeito → groups satisfeitos 4–5 / neutros 3 / insatisfeitos 1–2); CSAT = satisfeitos ÷ avaliações, and the executive view shows the per-grade distribution with a validated diverging palette (red–gray–blue). Migration `0018` backfilled what was recoverable for old chamados.

### Ativos ↔ Chamados

`patrimonio` is auto-generated in `Ativo.save()` (sequential from `100001`, same pattern as `matricula`; only 6-digit values count for the sequence) and is not editable in forms. An Ativo is located **either** in a `setor` **or** assigned to a `funcionario`, never both (validated in `AtivoEditarForm.clean`). Moving an asset happens through a chamado (`ChamadoMovimentarAtivoView`) by patrimônio number:
- Rules live in one function, `validar_movimentacao_ativo` (chamados/views.py), shared by the live JSON check (`chamados:verificar_ativo`, used by the detail page JS to show red/green feedback and enable the button) and the POST. With a funcionário chosen (only active users lotados in the chamado's setor — `funcionarios_atribuiveis(setor)`): asset must be in TI → assigned to that person. Without: asset in setor **"TI"** → chamado's setor; asset in the chamado's setor or assigned to someone → back to TI. Anything else is rejected. Depends on a `Setor` literally named `TI` existing.
- The movement is created as `PENDENTE` (one pending per asset); `ChamadoFecharView` applies it via `MovimentacaoAtivo.efetivar()`, which re-captures the real origin at that moment, updates the asset (status `em_uso`) and marks it `EFETIVADA`.

`MovimentacaoAtivo` is the **audit trail of every lotação change** (setor/funcionário origem→destino, `realizado_por`, `data_hora` = `efetivada_em or criado_em`). Rules that keep it complete — preserve them:
- Manual edits in `AtivoEditarView` that change setor/funcionário create an already-`EFETIVADA` movement with no chamado; they are blocked while the asset has a pending movement.
- `ativo` FK is `PROTECT` (assets with history can't be deleted; UI suggests marking "Danificado"), and the Django admin for movements is read-only.
- History page: `ativos:historico` (`/ativos/<pk>/historico/`).

## Conventions

- Model choices use nested `TextChoices` (`Usuario.Perfil`, `Chamado.Status`, `Prioridade`); templates compare against the raw string values (e.g. `user.perfil == 'administrador'`).
- Form widgets get Bootstrap classes (`form-control` / `form-select`) in the form's `Meta.widgets`, not in templates.
- Data seeding is done in data migrations, not fixtures.
- `README.md` is partly outdated (e.g. says ativos isn't integrated; omits super_admin, setores, SLA) — trust the code.
