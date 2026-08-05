from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from pilot.models import PilotProfile

from .forms import InvitationCreateForm, InviteRegistrationForm
from .models import Invitation
from .services import create_and_send_invitation, invitation_lifetime, send_invitation_email


@login_required
def home(request):
    return render(request, 'accounts/home.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:home')
    return render(request, 'accounts/registration/invitation_required.html', status=403)


def _get_invitation(token):
    try:
        return Invitation.objects.select_related('invited_by').get(token=token)
    except Invitation.DoesNotExist as exc:
        raise Http404('Invitation not found.') from exc


def invitation_accept(request, token):
    if request.user.is_authenticated:
        return redirect("pilot:profile_edit")

    invitation = _get_invitation(token)
    state = invitation.display_status
    if state != Invitation.Status.PENDING:
        return render(request, 'accounts/invitations/unavailable.html', {'invitation': invitation, 'state': state}, status=410)

    form = InviteRegistrationForm(request.POST or None, invitation=invitation)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
                if locked.display_status != Invitation.Status.PENDING:
                    messages.error(request, 'This invitation is no longer available.')
                    return redirect('accounts:invitation_accept', token=token)
                user = form.save()
                PilotProfile.objects.get_or_create(user=user, defaults={'phone': user.phone})
                locked.status = Invitation.Status.ACCEPTED
                locked.accepted_at = timezone.now()
                locked.save(update_fields=['status', 'accepted_at', 'updated_at'])
        except IntegrityError:
            form.add_error('email', 'An account with this email address already exists.')
        else:
            login(request, user)
            messages.success(request, 'Your AirSpace account has been created. Complete your pilot profile to continue.')
            return redirect("pilot:profile_edit")

    return render(request, 'accounts/invitations/accept.html', {'form': form, 'invitation': invitation})


@staff_member_required
@transaction.atomic
def invitation_list(request):
    form = InvitationCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            invitation = create_and_send_invitation(request=request, email=form.cleaned_data['email'], invited_by=request.user)
        except Exception as exc:
            messages.error(request, f'Invitation was saved but the email could not be sent: {exc}')
        else:
            messages.success(request, f'Invitation sent to {invitation.email}.')
        return redirect('accounts:invitation_list')
    return render(request, 'accounts/invitations/list.html', {'form': form, 'invitations': Invitation.objects.select_related('invited_by')})


@staff_member_required
@require_POST
def invitation_resend(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status != Invitation.Status.PENDING:
        messages.error(request, 'Only pending invitations can be resent.')
    else:
        invitation.expires_at = timezone.now() + invitation_lifetime()
        invitation.save(update_fields=['expires_at', 'updated_at'])
        try:
            send_invitation_email(request=request, invitation=invitation)
        except Exception as exc:
            messages.error(request, f'Email could not be sent: {exc}')
        else:
            messages.success(request, f'Invitation resent to {invitation.email}.')
    return redirect('accounts:invitation_list')


@staff_member_required
@require_POST
def invitation_revoke(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status == Invitation.Status.PENDING:
        invitation.status = Invitation.Status.REVOKED
        invitation.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'Invitation for {invitation.email} was revoked.')
    else:
        messages.error(request, 'Only pending invitations can be revoked.')
    return redirect('accounts:invitation_list')


@login_required
def pilot_profile_onboarding(request):
    """Backward-compatible onboarding URL for existing invitation links."""
    return redirect("pilot:profile_edit")
