import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import Setor, Usuario


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control', 'autofocus': True})
        self.fields['password'].widget.attrs.update({'class': 'form-control'})


class TrocarSenhaForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.update({'class': 'form-control', 'autofocus': True})
        self.fields['new_password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['new_password2'].widget.attrs.update({'class': 'form-control'})


class UsuarioCadastroForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ['username', 'first_name', 'last_name', 'email', 'telefone', 'perfil', 'setor', 'vip']
        labels = {
            'username': 'Usuário (login)',
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'vip': 'Solicitante VIP',
        }
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '(00)00000-0000',
                'inputmode': 'numeric',
                'maxlength': '14',
                'data-telefone-mask': '',
            }),
            'perfil': forms.Select(attrs={'class': 'form-select'}),
            'setor': forms.Select(attrs={'class': 'form-select'}),
            'vip': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ('first_name', 'last_name', 'email'):
            self.fields[campo].required = True
        self.fields['setor'].empty_label = 'Selecione um setor'

    def clean_telefone(self):
        telefone = self.cleaned_data.get('telefone', '')
        digitos = re.sub(r'\D', '', telefone)
        if not digitos:
            return ''
        if len(digitos) < 10 or len(digitos) > 11:
            raise forms.ValidationError('Telefone inválido. Informe o DDD e o número (10 ou 11 dígitos).')
        return digitos


class UsuarioEditarForm(UsuarioCadastroForm):
    class Meta(UsuarioCadastroForm.Meta):
        fields = ['first_name', 'last_name', 'email', 'telefone', 'perfil', 'setor', 'vip']


class SetorForm(forms.ModelForm):
    class Meta:
        model = Setor
        fields = ['nome']
        labels = {'nome': 'Nome do setor'}
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
        }
