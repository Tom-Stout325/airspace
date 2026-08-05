from django import forms

from .models import Drone, DroneSafetyProfile
from .services import find_best_drone_profile


class DateInput(forms.DateInput):
    input_type = "date"


class DroneForm(forms.ModelForm):
    safety_profile = forms.ModelChoiceField(
    queryset=DroneSafetyProfile.objects.none(),
    required=True,
    label="Drone model",
    empty_label="Select a drone model",
    widget=forms.Select(
        attrs={
            "class": "form-select",
        }
    ),
)

    class Meta:
        model = Drone
        fields = [
            "safety_profile", "manufacturer", "model", "nickname", "serial_number",
            "faa_registration_number", "registration_date",
            "registration_expiration", "date_purchased", "status",
            "safety_features", "notes", "faa_certificate",
        ]
        widgets = {
            "manufacturer": forms.HiddenInput(),
            "model": forms.HiddenInput(),
            "registration_date": DateInput(),
            "registration_expiration": DateInput(),
            "date_purchased": DateInput(),
            "safety_features": forms.Textarea(attrs={"rows": 7}),
            "notes": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["safety_profile"].queryset = (
            DroneSafetyProfile.objects
            .filter(active=True)
            .order_by("brand", "model_name")
        )
        self.fields["manufacturer"].required = False
        self.fields["model"].required = False

        self.matched_safety_profile = None
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        selected_profile = cleaned.get("safety_profile")
        manufacturer = (cleaned.get("manufacturer") or "").strip()
        model_name = (cleaned.get("model") or "").strip()

        if selected_profile:
            previous_profile_id = self.instance.safety_profile_id if self.instance.pk else None
            profile_changed = previous_profile_id != selected_profile.pk

            cleaned["manufacturer"] = selected_profile.brand
            cleaned["model"] = selected_profile.model_name
            self.matched_safety_profile = selected_profile

            safety_features = (cleaned.get("safety_features") or "").strip()
            if not safety_features or profile_changed:
                cleaned["safety_features"] = selected_profile.safety_features
        else:
            if not manufacturer:
                self.add_error("manufacturer", "Enter a manufacturer or select a drone model.")
            if not model_name:
                self.add_error("model", "Enter a model or select a drone model.")

            if manufacturer and model_name:
                self.matched_safety_profile = find_best_drone_profile(manufacturer, model_name)
                if self.matched_safety_profile:
                    cleaned["safety_profile"] = self.matched_safety_profile
                    if not (cleaned.get("safety_features") or "").strip():
                        cleaned["safety_features"] = self.matched_safety_profile.safety_features

        return cleaned

    def save(self, commit=True):
        drone = super().save(commit=False)
        selected_profile = self.cleaned_data.get("safety_profile") or self.matched_safety_profile

        if selected_profile:
            drone.safety_profile = selected_profile
            drone.manufacturer = selected_profile.brand
            drone.model = selected_profile.model_name
            if not (drone.safety_features or "").strip():
                drone.safety_features = selected_profile.safety_features

        if commit:
            drone.save()
            self.save_m2m()
        return drone


class DroneSafetyProfileForm(forms.ModelForm):
    class Meta:
        model = DroneSafetyProfile
        fields = ["brand", "model_name", "full_display_name", "year_released",
                  "is_enterprise", "safety_features", "aka_names", "active"]
        widgets = {
            "brand": forms.Select(attrs={"class": "form-select"}),
            "model_name": forms.TextInput(attrs={"class": "form-control"}),
            "full_display_name": forms.TextInput(attrs={"class": "form-control"}),
            "year_released": forms.NumberInput(attrs={"class": "form-control", "min": 2000, "max": 2100}),
            "is_enterprise": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "safety_features": forms.Textarea(attrs={"class": "form-control", "rows": 7}),
            "aka_names": forms.TextInput(attrs={"class": "form-control", "placeholder": "Alternate names separated by commas or new lines"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
