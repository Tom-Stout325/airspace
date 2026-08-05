from django import forms
from django.db import transaction

from .models import PilotProfile


class PilotProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(label="Email address")

    class Meta:
        model = PilotProfile
        fields = [
            "first_name", "last_name", "business_name", "email",
            "street_address", "city", "state", "zip_code", "phone",
            "license_number",
        ]
        labels = {
            "business_name": "Business name",
            "street_address": "Street address",
            "zip_code": "ZIP code",
            "license_number": "FAA certificate number",
        }
        widgets = {
            "state": forms.TextInput(attrs={"maxlength": 2, "placeholder": "IN"}),
            "zip_code": forms.TextInput(attrs={"autocomplete": "postal-code"}),
            "phone": forms.TelInput(attrs={"autocomplete": "tel"}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["email"].initial = user.email
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if type(self.user).objects.exclude(pk=self.user.pk).filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean_state(self):
        return self.cleaned_data.get("state", "").strip().upper()

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"]
        self.user.phone = self.cleaned_data.get("phone", "").strip()
        profile.user = self.user
        if commit:
            self.user.save(update_fields=["first_name", "last_name", "email", "phone", "updated_at"])
            profile.save()
        return profile
