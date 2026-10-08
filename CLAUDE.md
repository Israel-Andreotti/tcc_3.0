# CLAUDE.md

Service desk / helpdesk de TI (TCC). Django 5.2 full-stack: server-rendered templates + Bootstrap 5 via CDN, no separate frontend, no REST API. All code, UI text, model/field names and commit messages are in **Portuguese** — keep it that way.

## Commands

All Django commands run from `backend/` with the root `venv/` activated.

```bash
cd backend
python manage.py runserver          # or double-click run.bat at repo root
python manage.py makemigrations && python manage.py migrate
python manage.py test               # tests.py files are empty stubs — there is no real test suite yet
python manage.py test chamados      # single app
python manage.py check
```

Config comes from `backend/.env` via `python-decouple` (template: `backend/.env.example`). PostgreSQL only (no SQLite): `config/settings.py` uses `DATABASE_URL` when set (prod/Render), otherwise the `DB_*` variables (local Postgres, database `tcc_chamados`).

## Deploy (Render)

`render.yaml` (Blueprint, `autoDeploy: false`, root `backend/`) runs `build.sh`: install deps → `collectstatic` → `migrate` → upsert the `DJANGO_SUPERUSER_USERNAME` user as superuser/administrador and **reset its password from `DJANGO_SUPERUSER_PASSWORD` on every deploy**. Served by gunicorn + WhiteNoise (`CompressedManifestStaticFilesStorage` — a template referencing a missing static file will 500 in prod). Media (`Anexo` uploads) is only served when `DEBUG=True` and Render's disk is ephemeral.

## Architecture

```
backend/
  config/     settings, root urls
  core/       dashboard, RBAC mixins, ForcarTrocaSenhaMiddleware, template filters (chamado_extras)
  usuarios/   custom user model Usuario (AUTH_USER_MODEL), Setor, login/senha, user management
  chamados/   Categoria/Subcategoria (service catalog), SLAPrioridade, Chamado, Comentario, Anexo, ProcedimentoEntry
  ativos/     Ativo (equipment) and MovimentacaoAtivo
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

- **Priority is never chosen by users**: `Chamado.save()` copies it from `subcategoria.prioridade`. Title is set to the subcategoria name on create.
- **SLA**: `prazo_sla` is set once on first save = now + hours from `SLAPrioridade` (DB, admin-editable; seeded by migration `0011`), falling back to `Chamado.SLA_HORAS`. VIP solicitantes get `× 0.75`. Display helpers: `sla_percentual`, `sla_cor`, `sla_estourado`, `sla_tempo_restante_display`.
- Status flow: `aberto` → `em_andamento` (when a técnico "pega" or is reatribuído) → `resolvido` (via `concluir`, sets `fechado_em`). The técnico queue excludes `resolvido`/`fechado` (those appear in `historico/`) and is ordered by SLA urgency: SLA-paused last, then `prazo_sla` ascending (overdue first). The solicitante's "Meus chamados" keeps the model default (`-criado_em`). Once `chamado.encerrado` (resolvido/fechado) it is read-only: action views use `ChamadoEditavelMixin` (server-side block) and the detail template gates forms on `pode_editar`.
- `aguardando_solicitante`: técnico enters it via `aguardar_solicitante` (requires a public message) and leaves via `retomar`; the solicitante leaves it by replying (`responder`, creates a `ProcedimentoEntry` of tipo `resposta`). While waiting the SLA is **paused**: `pausar_sla()`/`retomar_sla()` on `Chamado` track `sla_pausado_em`/`sla_tempo_pausado` and extend `prazo_sla` by the paused time; all SLA properties use `_sla_referencia()` so they freeze during a pause. Concluding a paused chamado closes the pause first.
- Notifications (no email): solicitante sees a modal/banner in "Meus chamados" + navbar badge for chamados awaiting their reply. A reply sets `resposta_solicitante_em`; the assigned técnico gets non-blocking toasts via `base.html` polling `chamados:notificacoes` (JSON, every 30s) + navbar badge + "Nova resposta" row badge; cleared when that técnico opens the chamado (`ChamadoDetailView.get`). Counts come from simple tags in `core/templatetags/chamado_extras.py` and `Chamado.respostas_nao_vistas()`.
- `ProcedimentoEntry` is the attendance timeline: `publico` entries are visible to the solicitante, `interno` only to staff.
- Service catalog (Categoria → Subcategoria) is seeded by migration `0003_seed_catalogo` (healthcare-oriented IT catalog). Categoria/Subcategoria/Chamado FKs use `PROTECT`; delete views catch `ProtectedError`.

### Ativos ↔ Chamados

`patrimonio` is auto-generated in `Ativo.save()` (sequential from `100001`, same pattern as `matricula`; only 6-digit values count for the sequence) and is not editable in forms. An Ativo is located **either** in a `setor` **or** assigned to a `funcionario`, never both (validated in `AtivoEditarForm.clean`). Moving an asset happens through a chamado (`ChamadoMovimentarAtivoView`) by patrimônio number:
- Rules live in one function, `validar_movimentacao_ativo` (chamados/views.py), shared by the live JSON check (`chamados:verificar_ativo`, used by the detail page JS to show red/green feedback and enable the button) and the POST. With a funcionário chosen (only active users lotados in the chamado's setor — `funcionarios_atribuiveis(setor)`): asset must be in TI → assigned to that person. Without: asset in setor **"TI"** → chamado's setor; asset in the chamado's setor or assigned to someone → back to TI. Anything else is rejected. Depends on a `Setor` literally named `TI` existing.
- The movement is created as `PENDENTE` (one pending per asset); `ChamadoConcluirView` applies it via `MovimentacaoAtivo.efetivar()`, which re-captures the real origin at that moment, updates the asset (status `em_uso`) and marks it `EFETIVADA`.

`MovimentacaoAtivo` is the **audit trail of every lotação change** (setor/funcionário origem→destino, `realizado_por`, `data_hora` = `efetivada_em or criado_em`). Rules that keep it complete — preserve them:
- Manual edits in `AtivoEditarView` that change setor/funcionário create an already-`EFETIVADA` movement with no chamado; they are blocked while the asset has a pending movement.
- `ativo` FK is `PROTECT` (assets with history can't be deleted; UI suggests marking "Danificado"), and the Django admin for movements is read-only.
- History page: `ativos:historico` (`/ativos/<pk>/historico/`).

## Conventions

- Model choices use nested `TextChoices` (`Usuario.Perfil`, `Chamado.Status`, `Prioridade`); templates compare against the raw string values (e.g. `user.perfil == 'administrador'`).
- Form widgets get Bootstrap classes (`form-control` / `form-select`) in the form's `Meta.widgets`, not in templates.
- Data seeding is done in data migrations, not fixtures.
- `README.md` is partly outdated (e.g. says ativos isn't integrated; omits super_admin, setores, SLA) — trust the code.
