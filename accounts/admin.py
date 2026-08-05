from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .forms import AdminUserCreationForm, AdminUserChangeForm
from .models import EmailDeliveryLog, Invitation, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = AdminUserCreationForm
    form = AdminUserChangeForm
    model = User
    ordering = ('email',)
    list_display = ('email', 'first_name', 'last_name', 'phone', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('email', 'first_name', 'last_name', 'phone')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'phone')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'first_name', 'last_name', 'phone', 'password1', 'password2', 'is_staff', 'is_superuser', 'is_active'),
            },
        ),
    )
    readonly_fields = ('date_joined', 'last_login', 'created_at', 'updated_at')


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "display_status", "invited_by", "sent_at", "expires_at", "accepted_at")
    list_filter = ("status", "sent_at", "expires_at")
    search_fields = ("email", "invited_by__email")
    readonly_fields = ("token", "created_at", "updated_at", "sent_at", "accepted_at")


@admin.register(EmailDeliveryLog)
class EmailDeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("recipient", "status", "subject", "attempted_at")
    list_filter = ("status", "attempted_at")
    search_fields = ("recipient", "subject", "error_message")
    readonly_fields = ("invitation", "recipient", "subject", "status", "error_message", "attempted_at")
    def has_add_permission(self, request):
        return False
