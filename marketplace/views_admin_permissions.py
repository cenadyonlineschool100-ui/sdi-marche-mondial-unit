# Gestion des permissions des administrateurs
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth.models import Permission, Group
from django.contrib.contenttypes.models import ContentType

from .models import User, CommissionConfig


def is_super_admin(user):
    """Vérifier si l'utilisateur est un super admin"""
    return user.is_superuser or user.role == 'super_admin'


@login_required
def manage_admin_permissions(request):
    """Page de gestion des permissions des administrateurs"""
    
    # Seul le super admin ou un admin avec la permission peut accéder à cette page
    if not (is_super_admin(request.user) or request.user.has_perm('marketplace.manage_admin_permissions')):
        messages.error(request, "Vous n'avez pas la permission d'accéder à cette page.")
        return redirect('dashboard')
    
    # Récupérer tous les admins
    admins = User.objects.filter(is_staff=True).order_by('username')
    
    # Créer ou récupérer les permissions
    content_type = ContentType.objects.get_for_model(User)
    
    withdrawal_perm, _ = Permission.objects.get_or_create(
        codename='manage_withdrawal_commissions',
        defaults={
            'name': 'Peut gérer les commissions de retrait',
            'content_type': content_type,
        }
    )
    deposit_perm, _ = Permission.objects.get_or_create(
        codename='manage_deposit_commissions',
        defaults={
            'name': 'Peut gérer les commissions de dépôt',
            'content_type': content_type,
        }
    )
    admin_perm, _ = Permission.objects.get_or_create(
        codename='manage_admin_permissions',
        defaults={
            'name': 'Peut gérer les permissions des admins',
            'content_type': content_type,
        }
    )
    view_commission_perm, _ = Permission.objects.get_or_create(
        codename='view_commission',
        defaults={
            'name': 'Peut voir les commissions',
            'content_type': content_type,
        }
    )
    edit_commission_perm, _ = Permission.objects.get_or_create(
        codename='edit_commission',
        defaults={
            'name': 'Peut modifier les commissions',
            'content_type': content_type,
        }
    )
    create_commission_perm, _ = Permission.objects.get_or_create(
        codename='create_commission',
        defaults={
            'name': 'Peut créer des commissions',
            'content_type': content_type,
        }
    )
    delete_commission_perm, _ = Permission.objects.get_or_create(
        codename='delete_commission',
        defaults={
            'name': 'Peut supprimer des commissions',
            'content_type': content_type,
        }
    )
    manage_system_fees_perm, _ = Permission.objects.get_or_create(
        codename='manage_system_fees',
        defaults={
            'name': 'Peut gérer les frais système',
            'content_type': content_type,
        }
    )
    beauty_studio_perm, _ = Permission.objects.get_or_create(
        codename='manage_beauty_studio_requests',
        defaults={
            'name': 'Peut gérer les demandes Studio de Beauté',
            'content_type': content_type,
        }
    )
    
    # Préparer la liste des admins avec leurs permissions
    admin_list = []
    for admin in admins:
        admin_list.append({
            'user': admin,
            'has_withdrawal': admin.has_perm('marketplace.manage_withdrawal_commissions'),
            'has_deposit': admin.has_perm('marketplace.manage_deposit_commissions'),
            'has_admin': admin.has_perm('marketplace.manage_admin_permissions'),
            'has_beauty_studio': admin.has_perm('marketplace.manage_beauty_studio_requests'),
            'has_principal': admin.has_perm('marketplace.principal_admin_power'),
            'is_super': is_super_admin(admin),
        })
    
    context = {
        'admins': admin_list,
        'withdrawal_perm': withdrawal_perm,
        'deposit_perm': deposit_perm,
        'admin_perm': admin_perm,
        'beauty_studio_perm': beauty_studio_perm,
    }
    
    return render(request, 'marketplace/manage_admin_permissions.html', context)


@login_required
@require_http_methods(["POST"])
def toggle_admin_permission(request, user_id, permission_codename):
    """Activer/désactiver une permission pour un admin"""
    
    # Seul le super admin peut modifier les permissions
    if not is_super_admin(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    target_user = get_object_or_404(User, id=user_id, is_staff=True)
    
    try:
        permission = Permission.objects.get(codename=permission_codename)
        
        if target_user.has_perm(f'marketplace.{permission_codename}'):
            # Retirer la permission
            target_user.user_permissions.remove(permission)
            messages.success(request, f"Permission retirée à {target_user.username}.")
        else:
            # Ajouter la permission
            target_user.user_permissions.add(permission)
            messages.success(request, f"Permission accordée à {target_user.username}.")
    except Permission.DoesNotExist:
        messages.error(request, "Permission non trouvée.")
    
    return redirect('manage_admin_permissions')


@login_required
@require_http_methods(["POST"])
def grant_withdrawal_access(request, user_id):
    """Donner l'accès à la page Commission Retrait à un admin"""
    
    if not is_super_admin(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    target_user = get_object_or_404(User, id=user_id, is_staff=True)
    
    try:
        content_type = ContentType.objects.get_for_model(User)
        permission, _ = Permission.objects.get_or_create(
            codename='manage_withdrawal_commissions',
            defaults={
                'name': 'Peut gérer les commissions de retrait',
                'content_type': content_type,
            }
        )
        target_user.user_permissions.add(permission)
        messages.success(request, f"Accès Commission Retrait accordé à {target_user.username}.")
    except Exception as e:
        messages.error(request, f"Erreur: {str(e)}")
    
    return redirect('manage_admin_permissions')


@login_required
@require_http_methods(["POST"])
def revoke_withdrawal_access(request, user_id):
    """Retirer l'accès à la page Commission Retrait"""
    
    if not is_super_admin(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    target_user = get_object_or_404(User, id=user_id, is_staff=True)
    
    try:
        permission = Permission.objects.get(codename='manage_withdrawal_commissions')
        target_user.user_permissions.remove(permission)
        messages.success(request, f"Accès Commission Retrait retiré à {target_user.username}.")
    except Permission.DoesNotExist:
        pass
    
    return redirect('manage_admin_permissions')


@login_required
@require_http_methods(["POST"])
def toggle_principal_power(request, user_id):
    """Accorder ou retirer le "pouvoir admin principale" à un admin.

    Le pouvoir principal donne un ensemble de permissions (retrait, dépôt,
    gestion admin, frais système, etc.). Seul le super admin peut effectuer
    cette action.
    """
    if not is_super_admin(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')

    target_user = get_object_or_404(User, id=user_id, is_staff=True)
    try:
        content_type = ContentType.objects.get_for_model(User)
        principal_perm, _ = Permission.objects.get_or_create(
            codename='principal_admin_power',
            defaults={
                'name': 'Pouvoir admin principal',
                'content_type': content_type,
            }
        )

        # Permissions to grant when giving principal power
        perm_codenames = [
            'manage_withdrawal_commissions',
            'manage_deposit_commissions',
            'manage_admin_permissions',
            'manage_system_fees',
            'create_commission',
            'edit_commission',
            'delete_commission',
            'view_commission',
        ]

        if target_user.has_perm('marketplace.principal_admin_power'):
            # revoke principal and related perms
            target_user.user_permissions.remove(principal_perm)
            for code in perm_codenames:
                try:
                    p = Permission.objects.get(codename=code)
                    target_user.user_permissions.remove(p)
                except Permission.DoesNotExist:
                    continue
            messages.success(request, f"Pouvoir admin principal retiré à {target_user.username}.")
        else:
            # grant principal and related perms
            target_user.user_permissions.add(principal_perm)
            for code in perm_codenames:
                p, _ = Permission.objects.get_or_create(
                    codename=code,
                    defaults={
                        'name': code.replace('_', ' ').capitalize(),
                        'content_type': content_type,
                    }
                )
                target_user.user_permissions.add(p)
            messages.success(request, f"Pouvoir admin principal accordé à {target_user.username}.")
    except Exception as e:
        messages.error(request, f"Erreur: {str(e)}")

    return redirect('manage_admin_permissions')
