from django.urls import path
from . import views

app_name = "pilot"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("profile/delete/", views.profile_delete, name="profile_delete"),
    path("profile/logo/", views.logo_download, name="logo_download"),
]
