# -*- coding: utf-8 -*-
"""
Template tags for admin announcements
"""
from django import template
from django.template.exceptions import TemplateSyntaxError
from marketplace.models import AdminAnnouncementPermission

register = template.Library()


@register.filter
def check_announcement_permission(user, required_level='view'):
    """
    Template filter to check if user has announcement permission
    Usage: {% if user|check_announcement_permission %}
    """
    if not user or not user.is_authenticated:
        return False
    
    # Super admin et AI admin ont toujours accès
    if hasattr(user, 'role') and user.role in ['super_admin', 'ai_admin']:
        return True
    
    # Check specific permissions for admin_secondary
    if hasattr(user, 'role') and user.role == 'admin_secondary':
        try:
            perm = AdminAnnouncementPermission.objects.get(admin=user)
            return perm.has_permission(required_level)
        except AdminAnnouncementPermission.DoesNotExist:
            return False
    
    return False


@register.simple_tag
def get_active_announcements_for_display():
    """
    Get active announcements for display in template
    Usage: {% get_active_announcements_for_display as announcements %}
    """
    from marketplace.models import AdminAnnouncement
    from django.utils import timezone
    
    announcements = AdminAnnouncement.objects.filter(
        is_active=True,
        status='active'
    ).order_by('-is_priority', '-created_at')
    
    # Filter by date if start/end dates are set
    now = timezone.now()
    active_announcements = []
    for announcement in announcements:
        if announcement.start_date and announcement.start_date > now:
            continue
        if announcement.end_date and announcement.end_date < now:
            continue
        active_announcements.append(announcement)
    
    return active_announcements[:1] if active_announcements else None
