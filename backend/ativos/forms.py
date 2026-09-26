from django import forms

from .models import Ativo


class AtivoCadastroForm(forms.ModelForm):
    """Cadastro inicial: todo ativo novo entra disponível, lotado na TI."""

    class Meta:
        model = Ativo
        fields = ['marca', 'modelo', 'tipo', 'patrimonio']
        labels = {'patrimonio': 'Nº de patrimônio'}
        widgets = {
            'marca': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
            'modelo': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'patrimonio': forms.TextInput(attrs={'class': 'form-control'}),
        }


class AtivoEditarForm(forms.ModelForm):
    class Meta:
        model = Ativo
        fields = ['marca', 'modelo', 'tipo', 'patrimonio', 'status', 'setor', 'funcionario']
        labels = {'patrimonio': 'Nº de patrimônio'}
        widgets = {
            'marca': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
            'modelo': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'patrimonio': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'setor': forms.Select(attrs={'class': 'form-select'}),
            'funcionario': forms.HiddenInput(),
        }
        help_texts = {
            'setor': 'Deixe em branco se o ativo estiver atribuído a um funcionário.',
            'funcionario': 'Deixe em branco se o ativo estiver lotado num setor.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['setor'].required = False
        self.fields['setor'].empty_label = 'Sem setor'
        self.fields['funcionario'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('setor') and cleaned_data.get('funcionario'):
            raise forms.ValidationError(
                'Um ativo não pode estar lotado num setor e atribuído a um funcionário ao mesmo tempo. Escolha só um.'
            )
        return cleaned_data
