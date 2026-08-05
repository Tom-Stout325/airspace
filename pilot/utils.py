import base64
import mimetypes


def image_field_to_data_uri(image_field):
    """Return a storage-independent data URI for generated HTML/PDF documents."""
    if not image_field:
        return ""

    try:
        with image_field.open("rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
    except (FileNotFoundError, OSError, ValueError):
        return ""

    content_type, _ = mimetypes.guess_type(image_field.name)
    return f"data:{content_type or 'image/png'};base64,{encoded}"
