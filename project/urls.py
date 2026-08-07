from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('airspace/', include('airspace.urls', namespace='airspace')),
    path('pilot/', include('pilot.urls', namespace='pilot')),
    path('drones/', include('drones.urls', namespace='drones')),
    path(
        '',
        login_required(
            RedirectView.as_view(
                pattern_name='pilot:dashboard',
                permanent=False,
            )
        ),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
