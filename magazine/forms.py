from django import forms


class SearchForm(forms.Form):
    query = forms.CharField(
        label="",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Search Forward in Flight...",
                "class": "form-control",
            }
        ),
    )
