# ==========================================
# URLs MODULE IMMOBILIER
# ==========================================

from django.urls import path
from .real_estate_views import (
    real_estate_home, property_listing, property_detail,
    create_property, edit_property, delete_property,
    toggle_favorite, my_favorites,
    contact_owner, message_conversation, my_messages,
    become_member, admin_membership_requests, approve_membership_request, reject_membership_request,
    real_estate_admin_dashboard, admin_property_list,
    admin_conversations, admin_reviews, admin_user_management,
    approve_property, reject_property, approve_review, reject_review,
    toggle_agent_status, toggle_delivery_status,
    my_properties,
)

app_name = 'real_estate'

urlpatterns = [
    # Accueil et listing
    path('', real_estate_home, name='home'),
    path('listing/', property_listing, name='listing'),
    
    # Détail et gestion des propriétés
    path('property/<int:property_id>/', property_detail, name='detail'),
    path('property/create/', create_property, name='create'),
    path('property/<int:property_id>/edit/', edit_property, name='edit'),
    path('property/<int:property_id>/delete/', delete_property, name='delete'),
    path('my-properties/', my_properties, name='my_properties'),
    
    # Favoris
    path('favorite/<int:property_id>/toggle/', toggle_favorite, name='toggle_favorite'),
    path('favorites/', my_favorites, name='favorites'),
    
    # Messagerie
    path('property/<int:property_id>/contact/', contact_owner, name='contact_owner'),
    path('message/<int:message_id>/', message_conversation, name='conversation'),
    path('messages/', my_messages, name='messages'),
    
    # Admin
    path('admin/dashboard/', real_estate_admin_dashboard, name='admin_dashboard'),
    path('admin/properties/', admin_property_list, name='admin_property_list'),
    path('admin/conversations/', admin_conversations, name='admin_conversations'),
    path('admin/reviews/', admin_reviews, name='admin_reviews'),
    path('admin/users/', admin_user_management, name='admin_user_management'),
    path('admin/user/<int:user_id>/toggle-agent/', toggle_agent_status, name='toggle_agent_status'),
    path('admin/user/<int:user_id>/toggle-delivery/', toggle_delivery_status, name='toggle_delivery_status'),
    path('admin/property/<int:property_id>/approve/', approve_property, name='approve_property'),
    path('admin/property/<int:property_id>/reject/', reject_property, name='reject_property'),
    path('admin/review/<int:review_id>/approve/', approve_review, name='approve_review'),
    path('admin/review/<int:review_id>/reject/', reject_review, name='reject_review'),
    # Adhésion membres immobilier
    path('become-member/', become_member, name='become_member'),
    path('admin/membership-requests/', admin_membership_requests, name='admin_membership_requests'),
    path('admin/membership-request/<int:request_id>/approve/', approve_membership_request, name='approve_membership_request'),
    path('admin/membership-request/<int:request_id>/reject/', reject_membership_request, name='reject_membership_request'),
]
