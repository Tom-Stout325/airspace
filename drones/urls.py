from django.urls import path
from . import views

app_name = "drones"
urlpatterns = [
    path("", views.drone_list, name="list"),
    path("add/", views.drone_create, name="create"),
    path("safety-profiles/suggest/", views.drone_profile_suggest, name="profile_suggest"),
    path("safety-profiles/", views.drone_safety_profile_list, name="drone_safety_profile_list"),
    path("safety-profiles/add/", views.drone_safety_profile_create, name="drone_safety_profile_create"),
    path("safety-profiles/<int:pk>/edit/", views.drone_safety_profile_edit, name="drone_safety_profile_edit"),
    path("safety-profiles/<int:pk>/delete/", views.drone_safety_profile_delete, name="drone_safety_profile_delete"),
    path("<int:pk>/", views.drone_detail, name="detail"),
    path("<int:pk>/edit/", views.drone_update, name="update"),
    path("<int:pk>/delete/", views.drone_delete, name="delete"),
    path("<int:pk>/faa-certificate/", views.faa_certificate_download, name="faa_certificate_download"),
]
