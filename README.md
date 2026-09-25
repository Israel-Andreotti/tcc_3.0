# Sistema de Gerenciamento de Chamados

TCC — sistema de gerenciamento de chamados (service desk) com Django full-stack (backend + frontend via templates), PostgreSQL (ou SQLite em desenvolvimento) e RBAC por perfil de usuário (administrador, atendente, solicitante).

## Pré-requisitos

- Python 3.11+
- PostgreSQL 14+ (opcional em desenvolvimento — veja [Banco de dados](#banco-de-dados))

## Instalação

```bash
# na raiz do projeto
python -m venv venv

# ativar o ambiente virtual
venv\Scripts\activate        # Windows (cmd/PowerShell)
source venv/Scripts/activate # Windows (Git Bash)
source venv/bin/activate     # Linux/Mac

cd backend
pip install -r requirements.txt
```

## Configuração

Copie o arquivo de exemplo e ajuste se necessário:

```bash
cp .env.example .env
```

Variáveis disponíveis no `.env`:

| Variável | Descrição | Padrão |
|---|---|---|
| `SECRET_KEY` | Chave secreta do Django | valor de desenvolvimento incluso |
| `DEBUG` | Modo debug | `True` |
| `ALLOWED_HOSTS` | Hosts permitidos, separados por vírgula | `localhost,127.0.0.1` |
| `DB_ENGINE` | `sqlite` ou `postgresql` | `sqlite` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | Credenciais do PostgreSQL (usadas só se `DB_ENGINE=postgresql`) | `tcc_chamados` / `postgres` / `postgres` / `localhost` / `5432` |

## Banco de dados

**Desenvolvimento rápido (padrão):** com `DB_ENGINE=sqlite` no `.env`, nenhum setup extra é necessário — o Django cria `db.sqlite3` automaticamente.

**PostgreSQL:**
1. Crie o banco: `createdb tcc_chamados` (ou via `psql`/pgAdmin)
2. No `.env`, defina `DB_ENGINE=postgresql` e ajuste as demais variáveis `DB_*`

Depois, rode as migrations:

```bash
cd backend
python manage.py migrate
```

A migration `chamados/migrations/0003_seed_catalogo.py` já popula automaticamente o catálogo de categorias/subcategorias de chamados.

## Criando um usuário administrador

```bash
python manage.py createsuperuser
```

No admin (`/admin/`), edite o usuário criado e defina o campo **perfil** como `administrador` (por padrão todo novo usuário é criado como `solicitante`).

## Rodando o projeto

**Windows — atalho:** dê duplo clique em `run.bat` na raiz do projeto (ou rode `.\run.bat` no terminal). Ele entra em `backend/`, ativa o venv e sobe o servidor automaticamente.

**Manual:**

```bash
cd backend
python manage.py runserver
```

Acesse:
- **http://127.0.0.1:8000/usuarios/login/** — login (redireciona conforme o perfil: técnico/administrador vão para a fila de chamados, solicitante vai direto para abrir um chamado)
- **http://127.0.0.1:8000/admin/** — painel administrativo (gerenciar usuários, categorias, chamados)

## Estrutura do projeto

```
backend/
├── config/          # settings, urls raiz, wsgi/asgi
├── core/            # dashboard, mixins de RBAC (AdministradorRequiredMixin, AtendenteRequiredMixin)
├── usuarios/        # model de usuário customizado (perfil), login/logout
├── chamados/        # models de Categoria, Subcategoria, Chamado, Comentario + views/forms/templates
├── ativos/          # model de Ativo (cadastro de equipamentos) — ainda não integrado às views
└── templates/       # templates HTML (Bootstrap 5 via CDN)
```

## Perfis de usuário

| Perfil | Acesso |
|---|---|
| `solicitante` | Abre chamados e acompanha apenas os próprios |
| `atendente` (exibido como "Técnico") | Vê e gerencia (muda status/prioridade/atribuição) todos os chamados |
| `administrador` | Mesmo acesso do técnico + admin do Django |

## Testando sem escrever código

- Interface web: siga [Rodando o projeto](#rodando-o-projeto) e use o navegador
- Django admin (`/admin/`): CRUD direto nos models, sem passar pelos formulários da aplicação
- Shell interativo: `python manage.py shell`
- Testes automatizados: `python manage.py test`
