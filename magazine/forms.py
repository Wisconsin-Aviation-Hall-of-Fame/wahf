from django import forms


class SearchForm(forms.Form):
    query = forms.CharField(
        label="",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Search...",
                "class": "form-control",  # Useful if you use Bootstrap
            }
        ),
    )
