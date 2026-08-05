from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import PilotProfile


User = get_user_model()


class PilotProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(label="Email address")

    class Meta:
        model = PilotProfile
        fields = [
            "first_name",
            "last_name",
            "business_name",
            "logo",
            "email",
            "street_address",
            "city",
            "state",
            "zip_code",
            "phone",
            "faa_certificate_number",
        ]
        labels = {
            "business_name": "Business name",
            "logo": "Business or pilot logo",
            "street_address": "Street address",
            "zip_code": "ZIP code",
            "faa_certificate_number": "FAA certificate number",
        }
        widgets = {
            "state": forms.TextInput(
                attrs={
                    "maxlength": 2,
                    "placeholder": "IN",
                    "autocomplete": "address-level1",
                }
            ),
            "zip_code": forms.TextInput(
                attrs={"autocomplete": "postal-code"}
            ),
            "phone": forms.TelInput(
                attrs={"autocomplete": "tel"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user is None:
            raise ValueError("PilotProfileForm requires a user.")

        self.user = user

        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["email"].initial = user.email

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

        self.fields["logo"].widget.attrs.update({
            "accept": "image/jpeg,image/png,image/webp",
            "class": "form-control",
        })

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        email_in_use = (
            User.objects
            .exclude(pk=self.user.pk)
            .filter(email__iexact=email)
            .exists()
        )

        if email_in_use:
            raise forms.ValidationError(
                "An account with this email address already exists."
            )

        return email

    def clean_state(self):
        return self.cleaned_data.get("state", "").strip().upper()

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)

        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"]


        profile.user = self.user

        if commit:
            user_update_fields = [
                "first_name",
                "last_name",
                "email",
            ]

            # Include this only if User actually has an updated_at field.
            if hasattr(self.user, "updated_at"):
                user_update_fields.append("updated_at")

            self.user.save(update_fields=user_update_fields)
            profile.save()

        return profile