# ==========================================
# VUES MODULE IMMOBILIER - MAISON À LOUER SDI
# ==========================================

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import transaction as db_transaction
from django.db.models import Q, Count, Avg
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
import json
import logging

from .models import (
    User, Profile, Wallet, AuditLog, Property, PropertyImage, PropertyFavorite,
    RealEstateMessage, PropertyReview, RealEstateNotification, RealEstateMembershipRequest,
    MarketplaceSettings
)

logger = logging.getLogger(__name__)


# ==========================================
# VUE - ACCUEIL IMMOBILIER
# ==========================================
def real_estate_home(request):
    """Page d'accueil du module immobilier"""
    
    # Récupérer les propriétés approuvées et disponibles
    properties = Property.objects.filter(
        approval_status='approuvee',
        status='disponible'
    ).order_by('-published_at')
    
    # Récupérer les catégories avec comptage
    categories = {
        'maisons': properties.filter(property_type='maison').count(),
        'appartements': properties.filter(property_type='appartement').count(),
        'terrains': properties.filter(property_type='terrain').count(),
        'commerciaux': properties.filter(property_type='local_commercial').count(),
    }
    
    # Pagination
    paginator = Paginator(properties, 12)  # 12 par page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Favoris de l'utilisateur (seulement pour les utilisateurs authentifiés)
    favorite_ids = []
    is_real_estate_member = False
    has_pending_request = False
    if request.user.is_authenticated:
        favorite_ids = PropertyFavorite.objects.filter(user=request.user).values_list('property_id', flat=True)
        profile = getattr(request.user, 'profile', None)
        is_real_estate_member = bool(profile and profile.is_real_estate_member)
        has_pending_request = RealEstateMembershipRequest.objects.filter(user=request.user, status='pending').exists()
    
    context = {
        'page_obj': page_obj,
        'categories': categories,
        'favorite_ids': list(favorite_ids),
        'total_properties': properties.count(),
        'filters': {
            'city': '',
            'neighborhood': '',
            'country': '',
            'property_type': '',
            'listing_type': '',
            'price_min': '',
            'price_max': '',
            'bedrooms': '',
        },
        'is_real_estate_member': is_real_estate_member,
        'has_pending_request': has_pending_request,
    }
    
    return render(request, 'real_estate/home.html', context)


# ==========================================
# VUE - LISTING DES PROPRIÉTÉS (Avec Recherche et Filtrage)
# ==========================================
def property_listing(request):
    """Listing des propriétés avec recherche avancée et filtrage"""
    
    properties = Property.objects.filter(
        approval_status='approuvee',
        status='disponible'
    )
    
    # Filtres
    city = request.GET.get('city', '')
    neighborhood = request.GET.get('neighborhood', '')
    country = request.GET.get('country', '')
    property_type = request.GET.get('property_type', '')
    listing_type = request.GET.get('listing_type', '')
    price_min = request.GET.get('price_min', '')
    price_max = request.GET.get('price_max', '')
    bedrooms = request.GET.get('bedrooms', '')
    
    if city:
        properties = properties.filter(city__icontains=city)
    if neighborhood:
        properties = properties.filter(neighborhood__icontains=neighborhood)
    if country:
        properties = properties.filter(country__icontains=country)
    if property_type:
        properties = properties.filter(property_type=property_type)
    if listing_type:
        properties = properties.filter(listing_type=listing_type)
    if price_min:
        try:
            properties = properties.filter(price__gte=float(price_min))
        except ValueError:
            pass
    if price_max:
        try:
            properties = properties.filter(price__lte=float(price_max))
        except ValueError:
            pass
    if bedrooms:
        try:
            properties = properties.filter(bedrooms__gte=int(bedrooms))
        except ValueError:
            pass
    
    # Tri
    sort_by = request.GET.get('sort_by', '-published_at')
    properties = properties.order_by(sort_by)
    
    # Pagination
    paginator = Paginator(properties, 12)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Favoris (seulement pour utilisateurs authentifiés)
    favorite_ids = []
    if request.user.is_authenticated:
        favorite_ids = PropertyFavorite.objects.filter(user=request.user).values_list('property_id', flat=True)
    
    # Villes uniques pour le filtre
    cities = Property.objects.filter(approval_status='approuvee').values_list('city', flat=True).distinct()
    
    context = {
        'page_obj': page_obj,
        'favorite_ids': list(favorite_ids),
        'cities': sorted(set(cities)),
        'filters': {
            'city': city,
            'neighborhood': neighborhood,
            'country': country,
            'property_type': property_type,
            'listing_type': listing_type,
            'price_min': price_min,
            'price_max': price_max,
            'bedrooms': bedrooms,
        },
        'property_types': [
            ('maison', 'Maisons'),
            ('appartement', 'Appartements'),
            ('terrain', 'Terrains'),
            ('local_commercial', 'Locaux commerciaux'),
        ],
        'listing_types': [
            ('vente', 'À vendre'),
            ('location', 'À louer'),
        ],
    }
    
    return render(request, 'real_estate/listing.html', context)


# ==========================================
# VUE - DÉTAIL D'UNE PROPRIÉTÉ
# ==========================================
@login_required
def property_detail(request, property_id):
    """Affiche les détails d'une propriété"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    # Vérifier l'approbation
    if property_obj.approval_status != 'approuvee':
        if request.user != property_obj.owner and not request.user.is_staff:
            return HttpResponseForbidden("Cette propriété n'est pas disponible.")
    
    # Incrémenter le compteur de vues
    property_obj.view_count += 1
    property_obj.save(update_fields=['view_count'])
    
    # Récupérer les images
    images = property_obj.images.all()
    main_image = images.filter(image_type='facade').first() or images.first()
    exterior_images = images.filter(image_type__in=['facade', 'avant', 'entree', 'fenetres', 'jardin', 'balcon', 'parking', 'cloture']).order_by('order', 'uploaded_at')
    interior_images = images.filter(image_type__in=['salon', 'cuisine', 'chambre', 'salle_bain', 'toilettes']).order_by('order', 'uploaded_at')
    bedroom_images = images.filter(image_type='chambre').order_by('order', 'uploaded_at')
    bathroom_images = images.filter(image_type='salle_bain').order_by('order', 'uploaded_at')
    toilet_images = images.filter(image_type='toilettes').order_by('order', 'uploaded_at')
    kitchen_images = images.filter(image_type='cuisine').order_by('order', 'uploaded_at')
    other_images = images.exclude(image_type__in=['facade', 'avant', 'entree', 'fenetres', 'jardin', 'balcon', 'parking', 'cloture', 'salon', 'cuisine', 'chambre', 'salle_bain', 'toilettes']).order_by('order', 'uploaded_at')
    
    # Vérifier si elle est en favoris
    is_favorite = PropertyFavorite.objects.filter(
        user=request.user,
        property=property_obj
    ).exists()
    
    # Récupérer les avis approuvés
    reviews = PropertyReview.objects.filter(
        property=property_obj,
        is_approved=True
    )
    
    # Récupérer les messages (si propriétaire ou admin)
    messages = []
    if request.user == property_obj.owner or request.user.is_staff:
        messages = RealEstateMessage.objects.filter(
            property=property_obj
        ).order_by('-created_at')
    
    # Propriétés similaires
    similar_properties = Property.objects.filter(
        property_type=property_obj.property_type,
        city=property_obj.city,
        approval_status='approuvee',
        status='disponible'
    ).exclude(id=property_obj.id)[:4]
    
    context = {
        'property': property_obj,
        'images': images,
        'is_favorite': is_favorite,
        'reviews': reviews,
        'messages': messages,
        'similar_properties': similar_properties,
        'review_count': reviews.count(),
        'avg_rating': reviews.aggregate(Avg('rating'))['rating__avg'] or 0,
    }
    
    return render(request, 'real_estate/detail.html', context)


# ==========================================
# VUE - CRÉER UNE PROPRIÉTÉ
# ==========================================
@login_required
def create_property(request):
    """Formulaire de création de propriété"""
    # Seuls les membres immobiliers approuvés (ou le staff) peuvent créer une propriété
    try:
        is_member = request.user.profile.is_real_estate_member
    except Exception:
        is_member = False

    if not request.user.is_staff and not is_member:
        messages.error(request, "Vous devez être membre immobilier approuvé pour créer une annonce. Envoyez une demande d'adhésion au préalable.")
        return redirect('real_estate:become_member')
    
    # Vérifier que l'utilisateur a permission
    can_create = (
        request.user.is_staff or 
        request.user.is_seller or
        request.user.role in ['agent', 'delivery_employee']
    )
    
    if not can_create:
        return HttpResponseForbidden("Vous n'avez pas la permission de créer une propriété.")
    
    if request.method == 'POST':
        # Créer la propriété
        def checked(field_name):
            return request.POST.get(field_name) in ['on', 'true', 'True', '1']

        agent = None
        if request.user.is_staff:
            agent_id = request.POST.get('agent_id')
            if agent_id:
                agent = User.objects.filter(id=agent_id).first()

        property_obj = Property(
            title=request.POST.get('title'),
            description=request.POST.get('description'),
            property_type=request.POST.get('property_type'),
            listing_type=request.POST.get('listing_type'),
            address=request.POST.get('address'),
            city=request.POST.get('city'),
            neighborhood=request.POST.get('neighborhood', ''),
            country=request.POST.get('country', 'Haiti'),
            price=request.POST.get('price'),
            currency=request.POST.get('currency', 'HTG'),
            total_area=request.POST.get('total_area'),
            bedrooms=request.POST.get('bedrooms', 0),
            bathrooms=request.POST.get('bathrooms', 0),
            has_parking=checked('has_parking'),
            has_garden=checked('has_garden'),
            has_balcony=checked('has_balcony'),
            has_gate=checked('has_gate'),
            owner=request.user,
            agent=agent,
        )
        
        # Si admin, approuver automatiquement
        if request.user.is_staff:
            property_obj.approval_status = 'approuvee'
            property_obj.approved_by = request.user
            property_obj.published_at = timezone.now()
        
        property_obj.save()
        
        # Ajouter les images
        files = request.FILES.getlist('images')
        upload_groups = [
            ('images_facade', 'facade'),
            ('images_interior', 'salon'),
            ('images_cuisine', 'cuisine'),
            ('images_bedroom', 'chambre'),
            ('images_bathroom', 'salle_bain'),
            ('images_toilette', 'toilettes'),
            ('images_other', 'autre'),
        ]
        image_order = 0
        for field_name, image_type in upload_groups:
            for file in request.FILES.getlist(field_name):
                PropertyImage.objects.create(
                    property=property_obj,
                    image=file,
                    image_type=image_type,
                    order=image_order
                )
                image_order += 1

        # Support legacy image upload field
        for file in request.FILES.getlist('images'):
            PropertyImage.objects.create(
                property=property_obj,
                image=file,
                image_type='autre',
                order=image_order
            )
            image_order += 1
        
        # Créer notification
        if not request.user.is_staff:
            RealEstateNotification.objects.create(
                user=request.user,
                notification_type='propriete_approuvee' if property_obj.approval_status == 'approuvee' else 'propriete_approuvee',
                property=property_obj,
                title='Propriété en attente d\'approbation',
                message='Votre propriété a été soumise et est en attente d\'approbation par l\'administrateur.'
            )
        
        return redirect('real_estate:detail', property_id=property_obj.id)
    
    available_agents = User.objects.filter(
        Q(is_agent=True) | Q(is_delivery_employee=True)
    ).order_by('username') if request.user.is_staff else None

    context = {
        'property_types': [
            ('maison', 'Maison'),
            ('appartement', 'Appartement'),
            ('terrain', 'Terrain'),
            ('local_commercial', 'Local commercial'),
        ],
        'listing_types': [
            ('vente', 'À vendre'),
            ('location', 'À louer'),
        ],
        'available_agents': available_agents,
    }
    
    return render(request, 'real_estate/create.html', context)


# ==========================================
# VUE - MODIFIER UNE PROPRIÉTÉ
# ==========================================
@login_required
def edit_property(request, property_id):
    """Formulaire de modification de propriété"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    # Vérifier les permissions
    if request.user != property_obj.owner and not request.user.is_staff:
        return HttpResponseForbidden("Vous n'avez pas la permission de modifier cette propriété.")
    
    def checked(field_name):
        return request.POST.get(field_name) in ['on', 'true', 'True', '1']

    if request.method == 'POST':
        # Mettre à jour les champs
        property_obj.title = request.POST.get('title', property_obj.title)
        property_obj.description = request.POST.get('description', property_obj.description)
        property_obj.price = request.POST.get('price', property_obj.price)
        property_obj.bedrooms = request.POST.get('bedrooms', property_obj.bedrooms)
        property_obj.bathrooms = request.POST.get('bathrooms', property_obj.bathrooms)
        property_obj.total_area = request.POST.get('total_area', property_obj.total_area)
        property_obj.has_parking = checked('has_parking')
        property_obj.has_garden = checked('has_garden')
        property_obj.has_balcony = checked('has_balcony')
        property_obj.has_gate = checked('has_gate')

        if request.user.is_staff:
            owner_first_name = request.POST.get('owner_first_name', '').strip()
            owner_last_name = request.POST.get('owner_last_name', '').strip()
            owner_phone = request.POST.get('owner_phone', '').strip()
            agent_id = request.POST.get('agent_id')

            if owner_first_name:
                property_obj.owner.first_name = owner_first_name
            if owner_last_name:
                property_obj.owner.last_name = owner_last_name
            if owner_first_name or owner_last_name:
                property_obj.owner.save(update_fields=['first_name', 'last_name'])
            if owner_phone:
                profile, _ = Profile.objects.get_or_create(user=property_obj.owner)
                profile.phone = owner_phone
                profile.save(update_fields=['phone'])
            if agent_id:
                assigned_agent = User.objects.filter(id=agent_id).first()
                property_obj.agent = assigned_agent

        property_obj.save()

        upload_groups = [
            ('images_facade', 'facade'),
            ('images_interior', 'salon'),
            ('images_cuisine', 'cuisine'),
            ('images_bedroom', 'chambre'),
            ('images_bathroom', 'salle_bain'),
            ('images_toilette', 'toilettes'),
            ('images_other', 'autre'),
        ]
        image_order = property_obj.images.count()
        for field_name, image_type in upload_groups:
            for file in request.FILES.getlist(field_name):
                PropertyImage.objects.create(
                    property=property_obj,
                    image=file,
                    image_type=image_type,
                    order=image_order
                )
                image_order += 1

        # Support legacy image upload field
        for file in request.FILES.getlist('images'):
            PropertyImage.objects.create(
                property=property_obj,
                image=file,
                image_type='autre',
                order=image_order
            )
            image_order += 1

        return redirect('real_estate:detail', property_id=property_obj.id)
    
    available_agents = User.objects.filter(
        Q(is_agent=True) | Q(is_delivery_employee=True)
    ).order_by('username') if request.user.is_staff else None

    owner_phone = ''
    if hasattr(property_obj.owner, 'profile'):
        owner_phone = property_obj.owner.profile.phone

    context = {
        'property': property_obj,
        'property_types': [
            ('maison', 'Maison'),
            ('appartement', 'Appartement'),
            ('terrain', 'Terrain'),
            ('local_commercial', 'Local commercial'),
        ],
        'available_agents': available_agents,
        'owner_phone': owner_phone,
    }
    
    return render(request, 'real_estate/edit.html', context)


# ==========================================
# VUE - SUPPRIMER UNE PROPRIÉTÉ
# ==========================================
@login_required
def delete_property(request, property_id):
    """Supprimer une propriété"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    # Vérifier les permissions
    if request.user != property_obj.owner and not request.user.is_staff:
        return HttpResponseForbidden("Vous n'avez pas la permission de supprimer cette propriété.")
    
    if request.method == 'POST':
        property_obj.delete()
        return redirect('real_estate:home')
    
    return render(request, 'real_estate/delete_confirm.html', {'property': property_obj})


# ==========================================
# VUE - FAVORIS
# ==========================================
@login_required
def toggle_favorite(request, property_id):
    """Ajouter/supprimer des favoris (AJAX)"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    favorite, created = PropertyFavorite.objects.get_or_create(
        user=request.user,
        property=property_obj
    )
    
    if not created:
        # Si existe déjà, supprimer
        favorite.delete()
        is_favorite = False
    else:
        is_favorite = True
        # Créer notification
        RealEstateNotification.objects.create(
            user=property_obj.owner,
            notification_type='favori_ajoute',
            property=property_obj,
            title='Votre propriété a été ajoutée aux favoris',
            message=f'{request.user.first_name} a ajouté votre propriété aux favoris.'
        )
    
    return JsonResponse({
        'success': True,
        'is_favorite': is_favorite,
        'favorite_count': PropertyFavorite.objects.filter(property=property_obj).count(),
    })


@login_required
def my_favorites(request):
    """Affiche les propriétés favorites de l'utilisateur"""
    
    favorites = PropertyFavorite.objects.filter(user=request.user).select_related('property')
    
    paginator = Paginator(favorites, 12)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'favorite_count': favorites.count(),
    }
    
    return render(request, 'real_estate/favorites.html', context)


# ==========================================
# VUE - MESSAGERIE
# ==========================================
@login_required
def contact_owner(request, property_id):
    """Envoyer un message au propriétaire"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    if request.method == 'POST':
        message_text = request.POST.get('message', '')
        
        if message_text.strip():
            message = RealEstateMessage.objects.create(
                property=property_obj,
                sender=request.user,
                recipient=property_obj.owner,
                message=message_text,
            )
            
            # Incrémenter le compteur de contacts
            property_obj.contact_count += 1
            property_obj.save(update_fields=['contact_count'])
            
            # Créer notification pour le propriétaire
            RealEstateNotification.objects.create(
                user=property_obj.owner,
                notification_type='nouveau_message',
                property=property_obj,
                title='Nouveau message',
                message=f'{request.user.first_name} vous a envoyé un message.'
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Message envoyé avec succès.'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Le message ne peut pas être vide.'
            })
    
    return JsonResponse({'success': False, 'message': 'Méthode non autorisée.'}, status=405)


@login_required
def message_conversation(request, message_id):
    """Affiche une conversation de messages"""
    
    message_obj = get_object_or_404(RealEstateMessage, id=message_id)
    
    # Vérifier les permissions
    if request.user not in [message_obj.sender, message_obj.recipient] and not request.user.is_staff:
        return HttpResponseForbidden("Vous n'avez pas la permission d'accéder à cette conversation.")
    
    # Récupérer tous les messages de la conversation
    conversation = RealEstateMessage.objects.filter(
        Q(sender=message_obj.sender, recipient=message_obj.recipient) |
        Q(sender=message_obj.recipient, recipient=message_obj.sender),
        property=message_obj.property
    ).order_by('created_at')
    
    # Marquer les messages comme lus
    for msg in conversation:
        if msg.recipient == request.user:
            msg.mark_as_read()
    
    context = {
        'conversation': conversation,
        'property': message_obj.property,
        'other_user': message_obj.sender if message_obj.recipient == request.user else message_obj.recipient,
    }
    
    return render(request, 'real_estate/conversation.html', context)


@login_required
def my_messages(request):
    """Affiche les messages de l'utilisateur"""
    
    # Récupérer toutes les conversations de l'utilisateur
    messages = RealEstateMessage.objects.filter(
        Q(sender=request.user) | Q(recipient=request.user)
    ).select_related('property', 'sender', 'recipient').order_by('-created_at')

    # Grouper par propriété et par interlocuteur pour afficher une liste de conversations
    conversation_map = {}
    for msg in messages:
        other_user = msg.recipient if msg.sender == request.user else msg.sender
        key = (msg.property_id, other_user.id)

        if key not in conversation_map:
            conversation_map[key] = {
                'other_user': other_user,
                'property': msg.property,
                'last_message': msg.message,
                'date': msg.created_at,
                'unread_count': 0,
                'is_read': msg.is_read,
            }

        if msg.recipient == request.user and not msg.is_read:
            conversation_map[key]['unread_count'] += 1

    messages_list = list(conversation_map.values())

    context = {
        'messages_list': messages_list,
    }
    
    return render(request, 'real_estate/messages.html', context)


@login_required
def become_member(request):
    """Permet à un utilisateur d'envoyer une demande pour devenir membre immobilier."""
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.is_real_estate_member:
            messages.info(request, "Vous êtes déjà membre immobilier. Vous pouvez publier une annonce.")
            return redirect('real_estate:create')

        if RealEstateMembershipRequest.objects.filter(user=request.user, status='pending').exists():
            messages.info(request, "Votre demande d'adhésion est déjà en cours de traitement.")
            return redirect('real_estate:home')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        sample_title = request.POST.get('sample_property_title', '').strip()
        message_text = request.POST.get('message', '').strip()

        req = RealEstateMembershipRequest.objects.create(
            user=request.user,
            full_name=full_name,
            phone=phone,
            sample_property_title=sample_title,
            message=message_text,
            status='pending'
        )

        # Notifier les admins
        RealEstateNotification.objects.create(
            user=request.user,
            notification_type='nouveau_message',
            title='Nouvelle demande d\'adhésion immobilier',
            message=f"{request.user.username} a envoyé une demande d'adhésion."
        )

        messages.success(request, "Votre demande a été envoyée. Un administrateur la traitera prochainement.")
        return redirect('real_estate:home')

    # GET
    profile = getattr(request.user, 'profile', None)
    initial = {
        'full_name': f"{request.user.first_name} {request.user.last_name}".strip() if request.user.first_name else request.user.username,
        'phone': profile.phone if profile else ''
    }
    return render(request, 'real_estate/become_member.html', {'initial': initial})


@staff_member_required
def admin_membership_requests(request):
    """Affiche la liste des demandes d'adhésion pour que les admins puissent approuver/rejeter."""
    requests_qs = RealEstateMembershipRequest.objects.order_by('-created_at')
    return render(request, 'real_estate/admin_membership_requests.html', {'requests': requests_qs})


@staff_member_required
def approve_membership_request(request, request_id):
    req = get_object_or_404(RealEstateMembershipRequest, id=request_id)
    settings = MarketplaceSettings.get_solo()
    membership_fee = settings.real_estate_membership_fee_htg
    wallet, _ = Wallet.objects.get_or_create(user=req.user)
    initial_balance = wallet.balance_htg

    if wallet.balance_htg >= membership_fee:
        loan_amount = Decimal('0.00')
        wallet.balance_htg -= membership_fee
        note = 'Frais d’adhésion immobilier payés.'
    else:
        if not settings.enable_real_estate_auto_loan:
            messages.error(request, 'La demande ne peut pas être approuvée car le solde HTG est insuffisant et le prêt automatique est désactivé.')
            return redirect('real_estate:admin_membership_requests')

        loan_amount = membership_fee - wallet.balance_htg
        wallet.real_estate_loan_balance_htg += loan_amount
        wallet.balance_htg = Decimal('0.00')
        note = f'Prêt immobilier accordé pour couvrir le solde manquant ({loan_amount} HTG) des frais d’adhésion.'

    with db_transaction.atomic():
        wallet.save(update_fields=['balance_htg', 'real_estate_loan_balance_htg'])
        req.status = 'approved'
        req.save()
        profile = getattr(req.user, 'profile', None)
        if not profile:
            profile = Profile.objects.create(user=req.user)
        profile.is_real_estate_member = True
        profile.save(update_fields=['is_real_estate_member'])

        RealEstateNotification.objects.create(
            user=req.user,
            notification_type='propriete_approuvee',
            title='Demande d\'adhésion approuvée',
            message=f'Votre demande pour devenir membre immobilier a été approuvée. {note}'
        )

        AuditLog.objects.create(
            user=request.user,
            action='real_estate_membership_approval',
            details=(
                f"Approbation demande immobilier pour {req.user.username}. "
                f"Frais={membership_fee} HTG, solde_initial={initial_balance} HTG, "
                f"pret_accorder={loan_amount} HTG"
            ),
            ip_address=request.META.get('REMOTE_ADDR')
        )

    messages.success(request, 'La demande a été approuvée et l\'utilisateur est maintenant membre immobilier.')
    return redirect('real_estate:admin_membership_requests')


@staff_member_required
def reject_membership_request(request, request_id):
    req = get_object_or_404(RealEstateMembershipRequest, id=request_id)
    req.status = 'rejected'
    req.admin_note = request.POST.get('admin_note', '') if request.method == 'POST' else ''
    req.save()
    RealEstateNotification.objects.create(
        user=req.user,
        notification_type='propriete_rejetee',
        title='Demande d\'adhésion rejetée',
        message='Votre demande pour devenir membre immobilier a été rejetée.'
    )
    messages.success(request, 'La demande a été rejetée.')
    return redirect('real_estate:admin_membership_requests')


# ==========================================
# VUE - ADMIN DASHBOARD
# ==========================================
@staff_member_required
def real_estate_admin_dashboard(request):
    """Tableau de bord administrateur pour le module immobilier"""
    
    # Statistiques
    total_properties = Property.objects.count()
    pending_approval = Property.objects.filter(approval_status='en_attente').count()
    approved_properties = Property.objects.filter(approval_status='approuvee').count()
    rejected_properties = Property.objects.filter(approval_status='rejetee').count()
    
    # Propriétés en attente
    pending_list = Property.objects.filter(approval_status='en_attente').order_by('-created_at')[:10]
    
    # Messages non lus
    unread_messages = RealEstateMessage.objects.filter(is_read=False).count()
    recent_messages = RealEstateMessage.objects.filter(is_read=False).order_by('-created_at')[:10]
    
    # Avis en attente de modération
    pending_reviews = PropertyReview.objects.filter(is_approved=False).count()
    
    stats = {
        'total_properties': total_properties,
        'pending_properties': pending_approval,
        'approved_properties': approved_properties,
        'rejected_properties': rejected_properties,
    }

    context = {
        'stats': stats,
        'pending_properties': pending_list,
        'unread_messages': unread_messages,
        'recent_messages': recent_messages,
        'pending_reviews': pending_reviews,
    }
    
    return render(request, 'real_estate/admin_dashboard.html', context)


@staff_member_required
def approve_property(request, property_id):
    """Approuver une propriété"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    if request.method == 'POST':
        property_obj.approve(request.user)
        
        # Notification au propriétaire
        RealEstateNotification.objects.create(
            user=property_obj.owner,
            notification_type='propriete_approuvee',
            property=property_obj,
            title='Propriété approuvée',
            message='Votre propriété a été approuvée et est maintenant visible.'
        )
        
        return JsonResponse({'success': True, 'message': 'Propriété approuvée.'})
    
    return JsonResponse({'success': False}, status=405)


@staff_member_required
def reject_property(request, property_id):
    """Rejeter une propriété"""
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        property_obj.reject(request.user, reason)
        
        # Notification au propriétaire
        RealEstateNotification.objects.create(
            user=property_obj.owner,
            notification_type='propriete_rejetee',
            property=property_obj,
            title='Propriété rejetée',
            message=f'Votre propriété a été rejetée. Raison: {reason}'
        )
        
        return JsonResponse({'success': True, 'message': 'Propriété rejetée.'})
    
    return JsonResponse({'success': False}, status=405)


@staff_member_required
def admin_property_list(request):
    """Voir toutes les propriétés pour l'administrateur"""
    properties = Property.objects.select_related('owner', 'agent').order_by('-created_at')
    paginator = Paginator(properties, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
    }
    return render(request, 'real_estate/admin_property_list.html', context)


@staff_member_required
def admin_conversations(request):
    """Voir toutes les conversations du module immobilier"""
    messages_qs = RealEstateMessage.objects.select_related('property', 'sender', 'recipient').order_by('-created_at')
    conversation_map = {}

    for msg in messages_qs:
        participants_key = tuple(sorted([msg.sender_id, msg.recipient_id]))
        key = (msg.property_id, participants_key)

        if key not in conversation_map:
            conversation_map[key] = {
                'property': msg.property,
                'participants': [msg.sender, msg.recipient],
                'last_message': msg.message,
                'date': msg.created_at,
                'message_id': msg.id,
                'unread_count': 0,
            }

        if not msg.is_read:
            conversation_map[key]['unread_count'] += 1

    context = {
        'conversations': list(conversation_map.values()),
    }
    return render(request, 'real_estate/admin_conversations.html', context)


@staff_member_required
def admin_reviews(request):
    """Gérer les signalements et avis non approuvés"""
    reviews = PropertyReview.objects.filter(is_approved=False).select_related('property', 'user').order_by('-created_at')

    context = {
        'reviews': reviews,
    }
    return render(request, 'real_estate/admin_reviews.html', context)


@staff_member_required
def approve_review(request, review_id):
    review = get_object_or_404(PropertyReview, id=review_id)
    if request.method == 'POST':
        review.is_approved = True
        review.is_verified = True
        review.moderated_by = request.user
        review.save(update_fields=['is_approved', 'is_verified', 'moderated_by'])
        messages.success(request, 'Avis approuvé avec succès.')
        return redirect('real_estate:admin_reviews')
    return HttpResponseForbidden('Méthode non autorisée.')


@staff_member_required
def reject_review(request, review_id):
    review = get_object_or_404(PropertyReview, id=review_id)
    if request.method == 'POST':
        review.is_verified = True
        review.moderated_by = request.user
        review.save(update_fields=['is_verified', 'moderated_by'])
        messages.success(request, 'Avis rejeté.')
        return redirect('real_estate:admin_reviews')
    return HttpResponseForbidden('Méthode non autorisée.')


@staff_member_required
def admin_user_management(request):
    """Gérer les agents et livreurs"""
    users = User.objects.filter(
        Q(role__in=['agent', 'delivery_employee']) |
        Q(is_agent=True) |
        Q(is_delivery_employee=True)
    ).order_by('username')

    context = {
        'users': users,
    }
    return render(request, 'real_estate/admin_users.html', context)


@staff_member_required
def toggle_agent_status(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        user.is_agent = not user.is_agent
        if user.is_agent:
            user.role = 'agent'
        user.save(update_fields=['is_agent', 'role'])
        messages.success(request, f"Statut agent mis à jour pour {user.username}.")
        return redirect('real_estate:admin_user_management')
    return HttpResponseForbidden('Méthode non autorisée.')


@staff_member_required
def toggle_delivery_status(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        user.is_delivery_employee = not user.is_delivery_employee
        if user.is_delivery_employee:
            user.role = 'delivery_employee'
        user.save(update_fields=['is_delivery_employee', 'role'])
        messages.success(request, f"Statut livreur mis à jour pour {user.username}.")
        return redirect('real_estate:admin_user_management')
    return HttpResponseForbidden('Méthode non autorisée.')


# ==========================================
# VUE - PROPRIÉTÉS DE L'UTILISATEUR
# ==========================================
@login_required
def my_properties(request):
    """Affiche les propriétés de l'utilisateur"""
    
    properties = Property.objects.filter(owner=request.user).order_by('-created_at')
    
    paginator = Paginator(properties, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
    }
    
    return render(request, 'real_estate/my_properties.html', context)
