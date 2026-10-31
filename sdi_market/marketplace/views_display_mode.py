from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET

from .models import DisplayModePermission, SystemSettings, User


def _is_display_mode_owner(user):
    return (
        user.is_authenticated
        and user.is_active
        and user.username == 'admin'
        and user.is_superuser
    )


def _can_change_display_mode(user):
    if _is_display_mode_owner(user):
        return True
    return (
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.role == 'admin_secondary'
        and DisplayModePermission.objects.filter(user=user).exists()
    )


def _require_display_mode_access(user):
    if not _can_change_display_mode(user):
        raise PermissionDenied


@login_required
@require_GET
def display_mode_control(request):
    _require_display_mode_access(request.user)

    is_owner = _is_display_mode_owner(request.user)
    settings_obj = SystemSettings.objects.filter(pk=1).first()
    authorized_user_ids = set(
        DisplayModePermission.objects.values_list('user_id', flat=True)
    )
    secondary_admins = User.objects.filter(
        is_active=True,
        is_staff=True,
        role='admin_secondary',
    ).order_by('username')

    return render(request, 'marketplace/control_display_mode.html', {
        'desktop_display_mode_enabled': bool(
            settings_obj and settings_obj.desktop_display_mode_enabled
        ),
        'is_display_mode_owner': is_owner,
        'secondary_admins': secondary_admins if is_owner else (),
        'authorized_display_mode_user_ids': authorized_user_ids if is_owner else set(),
    })


@login_required
@require_POST
def set_display_mode(request):
    _require_display_mode_access(request.user)
    mode = request.POST.get('mode')
    if mode not in {'desktop', 'mobile'}:
        messages.error(request, "Le mode d’affichage demandé est invalide.")
        return redirect('display_mode_control')

    settings_obj, _ = SystemSettings.objects.get_or_create(pk=1)
    settings_obj.desktop_display_mode_enabled = mode == 'desktop'
    settings_obj.save(update_fields=['desktop_display_mode_enabled'])
    messages.success(
        request,
        "Mode ordinateur activé." if mode == 'desktop' else "Mode mobile responsive activé.",
    )
    return redirect('display_mode_control')


@login_required
@require_POST
def grant_display_mode_access(request, user_id):
    if not _is_display_mode_owner(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(
        User,
        pk=user_id,
        is_active=True,
        is_staff=True,
        role='admin_secondary',
    )
    DisplayModePermission.objects.update_or_create(
        user=target_user,
        defaults={'granted_by': request.user},
    )
    messages.success(request, f"Accès au mode d’affichage accordé à {target_user.username}.")
    return redirect('display_mode_control')


@login_required
@require_POST
def revoke_display_mode_access(request, user_id):
    if not _is_display_mode_owner(request.user):
        raise PermissionDenied

    permission = get_object_or_404(DisplayModePermission, user_id=user_id)
    username = permission.user.username
    permission.delete()
    messages.success(request, f"Accès au mode d’affichage retiré à {username}.")
    return redirect('display_mode_control')
