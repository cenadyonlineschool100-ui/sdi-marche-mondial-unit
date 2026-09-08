# -*- coding: utf-8 -*-
"""
Vues pour la gestion des annonces administratives
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.utils import timezone
from .models import AdminAnnouncement, AdminAnnouncementPermission, User
from .forms import AdminAnnouncementForm
import json


def check_announcement_permission(user, required_level='view'):
    """
    Vérifie si l'utilisateur a la permission d'accéder aux annonces
    """
    if not user.is_authenticated:
        return False
    
    # Super admin et AI admin ont toujours accès
    if user.role in ['super_admin', 'ai_admin']:
        return True
    
    # Vérifier les permissions spécifiques
    if user.role == 'admin_secondary':
        try:
            perm = AdminAnnouncementPermission.objects.get(admin=user)
            return perm.has_permission(required_level)
        except AdminAnnouncementPermission.DoesNotExist:
            return False
    
    return False


@login_required
def announcements_list(request):
    """
    Affiche la liste des annonces administratives
    """
    if not check_announcement_permission(request.user, 'view'):
        return HttpResponseForbidden("Vous n'avez pas la permission d'accéder à cette page.")
    
    announcements = AdminAnnouncement.objects.all().order_by('-is_priority', '-created_at')
    
    context = {
        'announcements': announcements,
        'can_create': check_announcement_permission(request.user, 'create'),
        'can_edit': check_announcement_permission(request.user, 'edit'),
        'can_delete': check_announcement_permission(request.user, 'delete'),
    }
    
    return render(request, 'announcements/list.html', context)


@login_required
def announcement_create(request):
    """
    Crée une nouvelle annonce
    """
    if not check_announcement_permission(request.user, 'create'):
        return HttpResponseForbidden("Vous n'avez pas la permission de créer une annonce.")
    
    if request.method == 'POST':
        form = AdminAnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.updated_by = request.user
            announcement.save()
            messages.success(request, f"Annonce '{announcement.title}' créée avec succès.")
            return redirect('announcements_list')
    else:
        form = AdminAnnouncementForm()
    
    context = {'form': form, 'title': 'Créer une nouvelle annonce'}
    return render(request, 'announcements/form.html', context)


@login_required
def announcement_edit(request, pk):
    """
    Modifie une annonce existante
    """
    if not check_announcement_permission(request.user, 'edit'):
        return HttpResponseForbidden("Vous n'avez pas la permission de modifier une annonce.")
    
    announcement = get_object_or_404(AdminAnnouncement, pk=pk)
    
    if request.method == 'POST':
        form = AdminAnnouncementForm(request.POST, instance=announcement)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.updated_by = request.user
            announcement.save()
            messages.success(request, f"Annonce '{announcement.title}' modifiée avec succès.")
            return redirect('announcements_list')
    else:
        form = AdminAnnouncementForm(instance=announcement)
    
    context = {
        'form': form,
        'announcement': announcement,
        'title': f'Modifier: {announcement.title}',
        'is_edit': True
    }
    return render(request, 'announcements/form.html', context)


@login_required
def announcement_delete(request, pk):
    """
    Supprime une annonce
    """
    if not check_announcement_permission(request.user, 'delete'):
        return HttpResponseForbidden("Vous n'avez pas la permission de supprimer une annonce.")
    
    announcement = get_object_or_404(AdminAnnouncement, pk=pk)
    title = announcement.title
    announcement.delete()
    messages.success(request, f"Annonce '{title}' supprimée avec succès.")
    return redirect('announcements_list')


@login_required
@require_http_methods(["POST"])
def announcement_toggle_active(request, pk):
    """
    Bascule l'état actif/inactif d'une annonce (AJAX)
    """
    if not check_announcement_permission(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    announcement = get_object_or_404(AdminAnnouncement, pk=pk)
    announcement.is_active = not announcement.is_active
    announcement.status = 'active' if announcement.is_active else 'inactive'
    announcement.updated_by = request.user
    announcement.save()
    
    return JsonResponse({
        'success': True,
        'is_active': announcement.is_active,
        'status': announcement.status,
        'message': f"Annonce {'activée' if announcement.is_active else 'désactivée'}"
    })


@login_required
@require_http_methods(["POST"])
def announcement_toggle_priority(request, pk):
    """
    Bascule la priorité d'une annonce (AJAX)
    """
    if not check_announcement_permission(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    announcement = get_object_or_404(AdminAnnouncement, pk=pk)
    announcement.is_priority = not announcement.is_priority
    announcement.updated_by = request.user
    announcement.save()
    
    # Si cette annonce devient prioritaire, retirer la priorité des autres
    if announcement.is_priority:
        AdminAnnouncement.objects.exclude(pk=pk).update(is_priority=False)
    
    return JsonResponse({
        'success': True,
        'is_priority': announcement.is_priority,
        'message': f"Annonce {'marquée comme prioritaire' if announcement.is_priority else 'retirée de la priorité'}"
    })


@login_required
def get_active_announcements(request):
    """
    Récupère les annonces actives au format JSON (pour le bandeau)
    """
    announcements = AdminAnnouncement.get_active_announcements()
    
    data = {
        'announcements': [],
        'priority_announcement': None
    }
    
    # Ajouter l'annonce prioritaire si elle existe
    priority = AdminAnnouncement.get_priority_announcement()
    if priority:
        data['priority_announcement'] = {
            'id': priority.id,
            'title': priority.title,
            'message': priority.message,
            'icon': priority.icon,
            'background_color': priority.background_color,
            'text_color': priority.text_color,
            'accent_color': priority.accent_color,
            'scroll_speed': priority.scroll_speed,
            'enable_loop': priority.enable_loop,
            'animation_effect': priority.animation_effect,
        }
    
    # Ajouter les annonces non-prioritaires
    for announcement in announcements.filter(is_priority=False):
        data['announcements'].append({
            'id': announcement.id,
            'title': announcement.title,
            'message': announcement.message,
            'icon': announcement.icon,
            'background_color': announcement.background_color,
            'text_color': announcement.text_color,
            'accent_color': announcement.accent_color,
            'scroll_speed': announcement.scroll_speed,
            'enable_loop': announcement.enable_loop,
            'animation_effect': announcement.animation_effect,
        })
    
    return JsonResponse(data)


@login_required
@require_http_methods(["POST"])
def announcement_record_view(request, pk):
    """
    Enregistre une vue d'annonce (AJAX)
    """
    try:
        announcement = AdminAnnouncement.objects.get(pk=pk)
        announcement.increment_views()
        return JsonResponse({'success': True})
    except AdminAnnouncement.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Announcement not found'}, status=404)


@login_required
@require_http_methods(["POST"])
def announcement_record_click(request, pk):
    """
    Enregistre un clic sur une annonce (AJAX)
    """
    try:
        announcement = AdminAnnouncement.objects.get(pk=pk)
        announcement.increment_clicks()
        return JsonResponse({'success': True})
    except AdminAnnouncement.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Announcement not found'}, status=404)
