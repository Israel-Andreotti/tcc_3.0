from django import forms

from .models import Chamado, ProcedimentoEntry, Subcategoria


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Campo de upload que aceita vários arquivos, retornando uma lista em cleaned_data."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(d, initial) for d in data]
        return single_file_clean(data, initial)


class SubcategoriaSelect(forms.Select):
    """Select que anota cada <option> com data-categoria, para o JS de cascata filtrar no template."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ''):
            subcategoria = self.choices.queryset.get(pk=value.value)
            option['attrs']['data-categoria'] = subcategoria.categoria_id
        return option


class ChamadoCreateForm(forms.ModelForm):
    class Meta:
        model = Chamado
        fields = ['categoria', 'subcategoria', 'setor', 'titulo', 'descricao']
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select', 'id': 'id_categoria'}),
            'subcategoria': SubcategoriaSelect(attrs={'class': 'form-select', 'id': 'id_subcategoria'}),
            'setor': forms.Select(attrs={'class': 'form-select'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    anexos = MultipleFileField(
        required=False,
        label='Anexos',
        help_text='Capturas de tela ou outros arquivos que ajudem a entender o problema.',
    )

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].required = True
        self.fields['categoria'].empty_label = 'Selecione uma categoria'
        self.fields['subcategoria'].required = True
        self.fields['subcategoria'].empty_label = 'Selecione uma subcategoria'
        self.fields['subcategoria'].queryset = Subcategoria.objects.select_related('categoria')
        self.fields['setor'].required = True
        self.fields['setor'].empty_label = 'Selecione um setor'
        self.fields['anexos'].widget.attrs.update({'class': 'form-control'})
        if usuario is not None and usuario.setor_id and not self.is_bound:
            self.fields['setor'].initial = usuario.setor_id

    def clean(self):
        cleaned_data = super().clean()
        categoria = cleaned_data.get('categoria')
        subcategoria = cleaned_data.get('subcategoria')
        if categoria and subcategoria and subcategoria.categoria_id != categoria.id:
            self.add_error('subcategoria', 'Selecione uma subcategoria pertencente à categoria escolhida.')
        return cleaned_data


class ChamadoGerenciarForm(forms.ModelForm):
    class Meta:
        model = Chamado
        fields = ['status', 'atendente']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'atendente': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        Usuario = self.fields['atendente'].queryset.model
        self.fields['atendente'].queryset = Usuario.objects.filter(
            perfil__in=[Usuario.Perfil.ATENDENTE, Usuario.Perfil.ADMINISTRADOR]
        )
        self.fields['atendente'].required = False


class ProcedimentoEntryForm(forms.ModelForm):
    class Meta:
        model = ProcedimentoEntry
        fields = ['tipo', 'texto']
        widgets = {
            'tipo': forms.HiddenInput(),
            'texto': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Descreva o procedimento realizado...',
            }),
        }
