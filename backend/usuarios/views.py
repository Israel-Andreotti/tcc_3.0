from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.crypto import get_random_string
from django.views.generic import CreateView, ListView, UpdateView, View

from core.mixins import AdministradorRequiredMixin, AtendenteRequiredMixin

from .forms import LoginForm, SetorForm, TrocarSenhaForm, UsuarioCadastroForm, UsuarioEditarForm
from .models import Setor, Usuario

SENHA_TEMPORARIA_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'


def gerar_senha_temporaria():
    return get_random_string(10, allowed_chars=SENHA_TEMPORARIA_CHARS)


def perfil_redirect_url(usuario):
    if usuario.perfil in (Usuario.Perfil.ADMINISTRADOR, Usuario.Perfil.ATENDENTE):
        return reverse_lazy('chamados:list')
    return reverse_lazy('chamados:create')


class LoginView(auth_views.LoginView):
    template_name = 'usuarios/login.html'
    authentication_form = LoginForm

    def get_success_url(self):
        redirect_url = self.get_redirect_url()
        if redirect_url:
            return redirect_url
        return perfil_redirect_url(self.request.user)


class LogoutView(auth_views.LogoutView):
    pass


class TrocarSenhaView(LoginRequiredMixin, auth_views.PasswordChangeView):
    template_name = 'usuarios/trocar_senha.html'
    form_class = TrocarSenhaForm

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.deve_trocar_senha = False
        self.request.user.save(update_fields=['deve_trocar_senha'])
        return response

    def get_success_url(self):
        return perfil_redirect_url(self.request.user)


class UsuarioCadastroView(AtendenteRequiredMixin, CreateView):
    model = Usuario
    form_class = UsuarioCadastroForm
    template_name = 'usuarios/usuario_form.html'

    def form_valid(self, form):
        self.object = form.save(commit=False)
        senha_temporaria = gerar_senha_temporaria()
        self.object.set_password(senha_temporaria)
        self.object.deve_trocar_senha = True
        self.object.save()
        return render(self.request, 'usuarios/usuario_resumo.html', {
            'usuario': self.object,
            'senha_temporaria': senha_temporaria,
        })


class UsuarioEditarView(AtendenteRequiredMixin, UpdateView):
    model = Usuario
    form_class = UsuarioEditarForm
    template_name = 'usuarios/usuario_editar.html'
    success_url = reverse_lazy('usuarios:list')

    def dispatch(self, request, *args, **kwargs):
        usuario = get_object_or_404(Usuario, pk=kwargs['pk'])
        if usuario.super_admin:
            messages.error(request, 'Contas de superadministrador não podem ser editadas por aqui.')
            return redirect('usuarios:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Cadastro de {self.object} atualizado.')
        return response


class UsuarioListView(AtendenteRequiredMixin, ListView):
    model = Usuario
    template_name = 'usuarios/usuario_list.html'
    context_object_name = 'usuarios'
    paginate_by = 25

    def get_queryset(self):
        qs = Usuario.objects.filter(super_admin=False).select_related('setor').order_by('first_name', 'username')
        termo = self.request.GET.get('q', '').strip()
        if termo:
            qs = qs.filter(
                Q(username__icontains=termo)
                | Q(first_name__icontains=termo)
                | Q(last_name__icontains=termo)
                | Q(matricula__icontains=termo)
            )
        perfil = self.request.GET.get('perfil', '').strip()
        if perfil:
            qs = qs.filter(perfil=perfil)
        status = self.request.GET.get('status', '').strip()
        if status == 'ativo':
            qs = qs.filter(is_active=True)
        elif status == 'inativo':
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        context['perfil_selecionado'] = self.request.GET.get('perfil', '')
        context['status_selecionado'] = self.request.GET.get('status', '')
        context['perfil_choices'] = Usuario.Perfil.choices
        return context


class UsuarioToggleAtivoView(AtendenteRequiredMixin, View):
    def post(self, request, pk):
        usuario = get_object_or_404(Usuario, pk=pk)
        if usuario == request.user:
            messages.error(request, 'Você não pode desativar a própria conta.')
            return redirect('usuarios:list')
        if usuario.super_admin:
            messages.error(request, 'Contas de superadministrador não podem ser desativadas.')
            return redirect('usuarios:list')
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=['is_active'])
        if usuario.is_active:
            messages.success(request, f'{usuario} reativado.')
        else:
            messages.success(request, f'{usuario} desativado.')
        return redirect('usuarios:list')


class UsuarioResetarSenhaView(AtendenteRequiredMixin, View):
    def post(self, request, pk):
        usuario = get_object_or_404(Usuario, pk=pk)
        if usuario.super_admin:
            messages.error(request, 'A senha de uma conta de superadministrador não pode ser resetada por aqui.')
            return redirect('usuarios:list')
        senha_temporaria = gerar_senha_temporaria()
        usuario.set_password(senha_temporaria)
        usuario.deve_trocar_senha = True
        usuario.save()
        return render(request, 'usuarios/usuario_resumo.html', {
            'usuario': usuario,
            'senha_temporaria': senha_temporaria,
            'reset_senha': True,
        })


class SetorListView(AdministradorRequiredMixin, ListView):
    model = Setor
    template_name = 'usuarios/setor_list.html'
    context_object_name = 'setores'

    def get_queryset(self):
        return Setor.objects.order_by('nome')


class SetorCadastroView(AdministradorRequiredMixin, CreateView):
    model = Setor
    form_class = SetorForm
    template_name = 'usuarios/setor_form.html'
    success_url = reverse_lazy('usuarios:setores')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Setor "{self.object}" cadastrado.')
        return response
