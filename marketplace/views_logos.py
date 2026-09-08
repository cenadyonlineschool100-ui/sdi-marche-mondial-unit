"""Vues pour la gestion des logos du site"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import HttpResponseForbidden
from .models import SiteConfiguration, SiteConfigurationPermission, User


def is_superuser(user):
    """Vérifie si l'utilisateur est superutilisateur"""
    return user.is_superuser


def can_edit_logos(user):
    """Vérifie si l'utilisateur peut modifier les logos"""
    if user.is_superuser:
        return True
    try:
        perm = user.logo_permission
        return perm.can_edit_logos
    except:
        return False


@login_required
def manage_logos(request):
    """Page pour gérer les logos (admin principal seulement)"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Accès refusé. Seul l'admin principal peut gérer les logos.")
    
    logos = SiteConfiguration.objects.all()
    permissions = SiteConfigurationPermission.objects.filter(can_edit_logos=True).select_related('user', 'granted_by')
    all_users = User.objects.exclude(is_superuser=True).order_by('username')
    
    context = {
        'logos': logos,
        'permissions': permissions,
        'all_users': all_users,
    }
    
    return render(request, 'marketplace/manage_logos.html', context)


@login_required
@require_POST
def update_logo(request, logo_id):
    """Mettre à jour un logo"""
    if not can_edit_logos(request.user):
        return HttpResponseForbidden("Vous n'avez pas la permission de modifier les logos.")
    
    logo = get_object_or_404(SiteConfiguration, id=logo_id)
    
    if 'image' in request.FILES:
        logo.image = request.FILES['image']
    
    if 'alt_text' in request.POST:
        logo.alt_text = request.POST.get('alt_text', '')
    
    if 'width' in request.POST:
        try:
            logo.width = int(request.POST.get('width', logo.width))
        except:
            pass
    
    if 'height' in request.POST:
        try:
            logo.height = int(request.POST.get('height', logo.height))
        except:
            pass
    
    logo.updated_by = request.user
    logo.save()
    
    messages.success(request, f"Logo '{logo.get_config_type_display()}' mis à jour avec succès!")
    return redirect('manage_logos')


@login_required
@require_POST
def grant_logo_permission(request, user_id):
    """Accorder la permission de modifier les logos à un utilisateur"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Seul l'admin principal peut accorder les permissions.")
    
    user = get_object_or_404(User, id=user_id)
    perm, created = SiteConfigurationPermission.objects.get_or_create(user=user)
    perm.can_edit_logos = True
    perm.granted_by = request.user
    perm.save()
    
    messages.success(request, f"Permission accordée à {user.username} pour modifier les logos!")
    return redirect('manage_logos')


@login_required
@require_POST
def revoke_logo_permission(request, user_id):
    """Retirer la permission de modifier les logos à un utilisateur"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Seul l'admin principal peut retirer les permissions.")
    
    user = get_object_or_404(User, id=user_id)
    try:
        perm = user.logo_permission
        perm.can_edit_logos = False
        perm.save()
        messages.warning(request, f"Permission retirée à {user.username}!")
    except:
        messages.error(request, f"Aucune permission trouvée pour {user.username}.")
    
    return redirect('manage_logos')
