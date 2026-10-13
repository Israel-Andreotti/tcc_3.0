from django import forms

from .models import Categoria, Chamado, ProcedimentoEntry, SLAPrioridade, Subcategoria


class PlaceholderSelect(forms.Select):
    """Select em que a opção vazia ("Selecione...") funciona como placeholder: fica desabilitada e
    oculta na lista, e o campo aparece em cinza enquanto nada foi escolhido (CSS .hd-select-placeholder)."""

    def __init__(self, attrs=None, choices=()):
        attrs = {**(attrs or {})}
        attrs['class'] = f"{attrs.get('class', 'form-select')} hd-select-placeholder".strip()
        super().__init__(attrs, choices)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value in (None, ''):
            option['attrs']['disabled'] = True
            option['attrs']['hidden'] = True
        return option


class SubcategoriaSelect(PlaceholderSelect):
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
        fields = ['categoria', 'subcategoria', 'setor', 'descricao']
        widgets = {
            'categoria': PlaceholderSelect(attrs={'class': 'form-select', 'id': 'id_categoria'}),
            'subcategoria': SubcategoriaSelect(attrs={'class': 'form-select', 'id': 'id_subcategoria'}),
            'setor': PlaceholderSelect(attrs={'class': 'form-select'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].required = True
        self.fields['categoria'].empty_label = 'Selecione uma categoria'
        self.fields['subcategoria'].required = True
        self.fields['subcategoria'].empty_label = 'Selecione uma subcategoria'
        self.fields['subcategoria'].queryset = Subcategoria.objects.select_related('categoria')
        self.fields['setor'].required = True
        self.fields['setor'].empty_label = 'Selecione um setor'
        self.fields['setor'].label_from_instance = lambda setor: f'{setor.nome} (setor crítico)' if setor.critico else setor.nome
        if usuario is not None and usuario.setor_id and not self.is_bound:
            self.fields['setor'].initial = usuario.setor_id

    def clean(self):
        cleaned_data = super().clean()
        categoria = cleaned_data.get('categoria')
        subcategoria = cleaned_data.get('subcategoria')
        if categoria and subcategoria and subcategoria.categoria_id != categoria.id:
            self.add_error('subcategoria', 'Selecione uma subcategoria pertencente à categoria escolhida.')
        return cleaned_data


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome']
        labels = {'nome': 'Nome da categoria'}
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
        }


class SubcategoriaForm(forms.ModelForm):
    """Adiciona uma subcategoria a uma categoria já definida (tela de edição da categoria)."""

    class Meta:
        model = Subcategoria
        fields = ['nome', 'prioridade']
        labels = {'nome': 'Nome da subcategoria', 'prioridade': 'Prioridade padrão'}
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex.: Impressora'}),
            'prioridade': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, categoria, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.categoria = categoria

    def clean_nome(self):
        # unique_together (categoria, nome) não é validado pelo form porque `categoria` não é campo dele.
        nome = self.cleaned_data['nome'].strip()
        if Subcategoria.objects.filter(categoria=self.instance.categoria, nome__iexact=nome).exists():
            raise forms.ValidationError(f'Já existe a subcategoria "{nome}" nesta categoria.')
        return nome


class SLAPrioridadeForm(forms.ModelForm):
    class Meta:
        model = SLAPrioridade
        fields = ['horas']
        labels = {'horas': 'Prazo (em horas)'}
        widgets = {
            'horas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }


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

    def clean_tipo(self):
        # "Resposta do solicitante" só é criada pela view do solicitante, nunca pela equipe.
        tipo = self.cleaned_data.get('tipo')
        if tipo not in (ProcedimentoEntry.Tipo.PUBLICO, ProcedimentoEntry.Tipo.INTERNO):
            raise forms.ValidationError('Tipo de registro inválido.')
        return tipo
