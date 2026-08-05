from django.core.exceptions import ValidationError

MAX_LOGO_SIZE = 5 * 1024 * 1024


def validate_logo_file_size(uploaded_file):
    if uploaded_file and uploaded_file.size > MAX_LOGO_SIZE:
        raise ValidationError("Logo files must be 5 MB or smaller.")
