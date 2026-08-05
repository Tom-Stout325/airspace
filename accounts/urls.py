from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .forms import (
    AppPasswordChangeForm,
    AppPasswordResetForm,
    AppSetPasswordForm,
    EmailAuthenticationForm,
)
from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.home, name='home'),
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='accounts/registration/login.html',
            authentication_form=EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(
            template_name='accounts/registration/logged_out.html',
        ),
        name='logout',
    ),
    path('register/', views.register, name='register'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/registration/password_reset_form.html',
            email_template_name='accounts/registration/password_reset_email.html',
            subject_template_name='accounts/registration/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
            form_class=AppPasswordResetForm,
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/registration/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
            form_class=AppSetPasswordForm,
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path(
        'password-change/',
        auth_views.PasswordChangeView.as_view(
            template_name='accounts/registration/password_change_form.html',
            success_url=reverse_lazy('accounts:password_change_done'),
            form_class=AppPasswordChangeForm,
        ),
        name='password_change',
    ),
    path(
        'password-change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='accounts/registration/password_change_done.html',
        ),
        name='password_change_done',
    ),
]
