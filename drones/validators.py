from django.core.exceptions import ValidationError


MAX_FAA_CERTIFICATE_SIZE = 5 * 1024 * 1024


def validate_faa_certificate_size(uploaded_file):
    if uploaded_file.size > MAX_FAA_CERTIFICATE_SIZE:
        raise ValidationError("FAA certificate files may not exceed 5 MB.")
