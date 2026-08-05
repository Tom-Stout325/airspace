from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import EmailDeliveryLog, Invitation


def invitation_lifetime():
    return timedelta(hours=getattr(settings, "INVITATION_EXPIRY_HOURS", 72))


def build_invitation_url(request, invitation):
    return request.build_absolute_uri(reverse("accounts:invitation_accept", kwargs={"token": invitation.token}))


def send_invitation_email(*, request, invitation):
    invitation_url = build_invitation_url(request, invitation)
    context = {"invitation": invitation, "invitation_url": invitation_url}
    subject = "You're invited to AirSpace"
    text_body = render_to_string("accounts/email/invitation.txt", context)
    html_body = render_to_string("accounts/email/invitation.html", context)
    message = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [invitation.email])
    message.attach_alternative(html_body, "text/html")
    try:
        sent_count = message.send(fail_silently=False)
    except Exception as exc:
        EmailDeliveryLog.objects.create(
            invitation=invitation,
            recipient=invitation.email,
            subject=subject,
            status=EmailDeliveryLog.Status.FAILED,
            error_message=str(exc),
        )
        raise
    EmailDeliveryLog.objects.create(
        invitation=invitation,
        recipient=invitation.email,
        subject=subject,
        status=EmailDeliveryLog.Status.SENT,
    )
    if sent_count:
        Invitation.objects.filter(pk=invitation.pk).update(sent_at=timezone.now())
        invitation.refresh_from_db(fields=["sent_at"])
    return sent_count


def create_and_send_invitation(*, request, email, invited_by):
    with transaction.atomic():
        invitation = Invitation.objects.create_for_email(
            email=email,
            invited_by=invited_by,
            lifetime=invitation_lifetime(),
        )
    send_invitation_email(request=request, invitation=invitation)
    return invitation
