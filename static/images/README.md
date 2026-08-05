# AirSpace Logo Assets

Copy this folder into:

    static/images/

## Included files

- `airspace-logo.png` — full logo on white background
- `airspace-logo-light.png` — transparent-background version for light pages
- `airspace-logo-dark.png` — full logo on dark navy background
- `airspace-navbar-logo.png` — compact wordmark for the navbar
- `airspace-icon.png` — square application icon
- `favicon.ico` — browser favicon with multiple sizes
- `apple-touch-icon.png` — 180×180 Apple home-screen icon
- `og-image.png` — 1200×630 social-sharing image

## Django usage

At the top of the template:

    {% load static %}

Navbar logo:

    <img src="{% static 'images/airspace-navbar-logo.png' %}"
         alt="AirSpace"
         height="38">

Full logo:

    <img src="{% static 'images/airspace-logo.png' %}"
         alt="AirSpace — FAA drone waivers, CONOPS, and pilot management"
         class="img-fluid">

Favicon in `index.html`:

    <link rel="icon" href="{% static 'images/favicon.ico' %}">
    <link rel="apple-touch-icon" href="{% static 'images/apple-touch-icon.png' %}">

Open Graph image:

    <meta property="og:image"
          content="{{ request.scheme }}://{{ request.get_host }}{% static 'images/og-image.png' %}">

## Note

These assets were derived from the generated PNG artwork. They are high-resolution raster assets, not a true editable vector master.