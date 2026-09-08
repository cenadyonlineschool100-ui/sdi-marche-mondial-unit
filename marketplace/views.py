import logging
import base64
import re
import os
import io

from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group
from django.views.decorators.http import require_POST
from django.db.models import Sum, Avg, Count, Q, Prefetch, Max
from django.db import transaction, connection
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings
from django.templatetags.static import static
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.mail import send_mail
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import secrets
import json
from random import sample
import gc
import traceback
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .forms import ProductForm, ProductReviewForm, SignUpForm, SystemSettingsForm, BannerExpandSettingsForm, ChatMessageForm, PrivateMessageForm, BeautyBookingForm, BeautyStudioServiceForm, BeautyStudioRequestForm, ShopCoverPhotoForm, ProfileForm, OrderForm, DeliveryLocationForm, TransferForm, TiKaneAccessRequestForm, TiKanePlanForm, AssignmentSubmissionForm, TechnicianProfileForm, SiteBannerForm, SiteBannerImageForm, PriorityGroupForm, BannerProductPriorityForm
from .security_enhanced import AnomalyDetector
from .models import (
    DeliveryAssignment, DeliveryEmployee, Order, OrderItem, Product, Shop,
    ProductImage, ProductReview, Transaction, Wallet, Agent, SystemSettings, SecurityIncident, SecurityEvent, IPBlocklist, Cart, CartItem,
    TiKaneAccessRequest, TiKanePlan, TiKaneAccount,
    BeautyAppointment, BeautyStudioRequest, BeautyStudioService, ShopCoverPhoto, Category, CategoryManager, DeliveryTracking, DeliveryNotification, ReturnRequest,
    Profile, TechnicianProfile, ChatGroup, ChatMessage, ChatMessageRead, PrivateConversation, PrivateMessage,
    PersistentNotification, AuditLog, ExchangeRate, Receipt, WithdrawalRequest, AdminWithdrawalPermission,
    Transfer, TransferReceipt, TransferLog, TransferNotification, TransferCommissionTier,
    SiteConfigurationPermission, Course, CourseAssignment, AssignmentSubmission, CourseCertificate,
    ProductAccessRequest, ResellerProduct, MarketplaceSettings, SDISolSettings, SDISolMember, SDISolPayment, SiteBanner, SiteBannerImage, SiteBannerPermission, SiteBannerAccess, SiteBannerPayment, SiteBannerEvent, PriorityGroup,
    # Security-related models used by the security dashboard API
    PortMonitoring, AIThreatAnalysis, HoneypotEvent, SecurityAlert, SecurityLog, SecurityMetrics
)
from .serializers import (
    DeliveryAssignmentSerializer, DeliveryEmployeeSerializer, OrderSerializer,
    ProductSerializer, ShopSerializer, TransactionSerializer, WalletSerializer,
    AgentSerializer, ReturnRequestSerializer
)
from .recommendations import (
    get_similar_products, get_personalized_recommendations, get_trending_products,
    refresh_recommendation_engine
)
from .utils import calcul_cashback
from .image_utils import generate_banner_variants
from .business_logic import (
    DeliveryAssignmentManager, DeliveryStatusManager,
    NotificationManager, PaymentManager, ReturnManager,
    OrderStatusManager, StatisticsManager, CommissionManager,
    get_system_admin_wallet, normalize_currency, fetch_exchange_rates_from_api,
    convert_currency
)

User = get_user_model()
logger = logging.getLogger(__name__)

# ------------------------------
# Utility functions
# ------------------------------

def is_order_in_history(order):
    """Retourne True si la commande doit être déplacée vers l'historique (30 min après confirmation)"""
    if order.date_reception_confirmee:
        return timezone.now() > order.date_reception_confirmee + timedelta(minutes=30)
    return False


def send_transfer_notification(transfer, recipient, title, message):
    TransferNotification.objects.create(
        transfer=transfer,
        recipient=recipient,
        title=title,
        message=message,
        status='sent',
        sent_at=timezone.now()
    )


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def get_banner_eligible_products(limit=None):
    """
    Retourne les produits éligibles pour affichage dans la bannière/carrousel.
    
    RÈGLES D'AFFICHAGE:
    - Image valide (custom_image ou image)
    - banner_display_allowed = True
    - banner_blocked_by_admin IS NULL (pas bloqué par admin)
    - Stock > 0
    
    Args:
        limit (int|None): Limite facultative pour les appels historiques.
    
    Returns:
        QuerySet: Les produits éligibles avec les relations préchargées
    """
    products = Product.objects.filter(
        quantity__gt=0,  # Stock disponible
        banner_display_allowed=True,  # Autorisé par défaut
        banner_blocked_by_admin__isnull=True  # NOT bloqué par admin
    ).select_related(
        'shop',
        'category'
    ).annotate(
        average_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
        reviews_count=Count('reviews', filter=Q(reviews__is_approved=True))
    ).order_by(
        '-average_rating',  # Trier par note d'abord
        '-reviews_count'    # Puis par nombre d'avis
    )
    if limit is not None:
        products = products[:limit]
    
    # Filtrer les produits qui ont une image valide
    # (custom_image ou image générée)
    eligible = [p for p in products if p.has_valid_image()]
    
    return eligible


@login_required
@require_POST
def optimize_performance(request):
    if not request.user.is_staff or request.user.role != 'super_admin':
        return JsonResponse({'success': False, 'error': 'Accès refusé'}, status=403)

    start_time = timezone.now()
    report = []

    try:
        cache.clear()
        report.append('Cache de l\'application effacé')

        collected = gc.collect()
        report.append(f'Garbage collection déclenchée ({collected} objets récupérés)')

        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        report.append('Connexion à la base de données vérifiée')

        if settings.DEBUG and hasattr(connection, 'queries'):
            slow_queries = [q for q in connection.queries if float(q.get('time', 0)) > 0.05]
            report.append(f'Queries lentes détectées dans DEBUG: {len(slow_queries)}')
            if slow_queries:
                report.append('Extraits des requêtes lentes: ' + ' | '.join(q.get('sql', '')[:120] for q in slow_queries[:3]))
        else:
            report.append('Journalisation des requêtes lentes indisponible (DEBUG désactivé)')

        settings_obj = SystemSettings.objects.first()
        if settings_obj:
            report.append('Paramètres système préchargés')

        active_shops = list(Shop.objects.filter(is_active=True).only('id', 'name')[:10])
        report.append(f'{len(active_shops)} boutiques actives préchargées')

        active_users_count = User.objects.filter(is_active=True).count()
        report.append(f'Utilisateur actifs comptés: {active_users_count}')

        duration_ms = int((timezone.now() - start_time).total_seconds() * 1000)
        details = json.dumps({'report': report, 'duration_ms': duration_ms})
        AuditLog.objects.create(
            user=request.user,
            action='optimize_performance',
            details=details,
            ip_address=get_client_ip(request)
        )

        return JsonResponse({
            'success': True,
            'duration_ms': duration_ms,
            'report': report,
        })
    except Exception as exc:
        duration_ms = int((timezone.now() - start_time).total_seconds() * 1000)
        error_details = traceback.format_exc()
        logger.exception('Erreur lors de l\'optimisation des performances')
        AuditLog.objects.create(
            user=request.user,
            action='optimize_performance_failed',
            details=json.dumps({
                'error': str(exc),
                'trace': error_details,
                'duration_ms': duration_ms,
            }),
            ip_address=get_client_ip(request)
        )
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors de l\'optimisation',
            'details': str(exc),
            'duration_ms': duration_ms,
        }, status=500)


def attach_reviews_stats(products):
    """Attache les statistiques d'avis aux produits"""
    if not products:
        return
    product_ids = [p.id for p in products]
    reviews_stats = ProductReview.objects.filter(
        product_id__in=product_ids,
        is_approved=True
    ).values('product_id').annotate(
        average_rating=Avg('rating'),
        reviews_count=Count('id')
    )
    
    reviews_dict = {stat['product_id']: stat for stat in reviews_stats}
    
    # Attacher les stats aux produits
    for product in products:
        stats = reviews_dict.get(product.id, {})
        product.average_rating = stats.get('average_rating', 0)
        product.reviews_count = stats.get('reviews_count', 0)


def get_wallet_balance_field(currency, account_type='micro_device'):
    currency = currency.upper()
    if currency == 'USD':
        return 'balance' if account_type == 'principal' else 'commission_balance_usd'
    if currency == 'HTG':
        return 'commission_balance_htg'
    if currency == 'EUR':
        return 'commission_balance_eur'
    if currency == 'DOP':
        return 'commission_balance_peso'
    return 'balance'


def get_commission_balance_field(currency):
    currency = currency.upper()
    if currency == 'USD':
        return 'commission_balance_usd'
    if currency == 'HTG':
        return 'commission_balance_htg'
    if currency == 'EUR':
        return 'commission_balance_eur'
    if currency == 'DOP':
        return 'commission_balance_peso'
    return 'commission_balance_usd'


def demo_page(request):
    """Page de démonstration pour la formation: présente comptes démo, boutiques et produits."""
    demo_users = User.objects.filter(email__in=['demo@buyer.local', 'seller@demo.local'])
    sample_products = Product.objects.all().select_related('shop')[:6]
    sample_shops = Shop.objects.all()[:6]
    placeholder = static('img/placeholder.png')
    return render(request, 'marketplace/demo.html', {
        'demo_users': demo_users,
        'sample_products': sample_products,
        'sample_shops': sample_shops,
        'placeholder': placeholder,
    })


def microordinateur(request):
    return render(request, 'marketplace/microordinateur.html')


def is_principal_admin(user):
    return user.is_superuser or user.has_perm('marketplace.principal_admin_power')


@login_required
def get_recipient_account_info(request):
    account_code = request.GET.get('account_code', '').strip().upper()
    if not account_code:
        return JsonResponse({'error': 'Numéro de compte requis.'}, status=400)
    recipient = User.objects.filter(account_code__iexact=account_code).first()
    if not recipient:
        return JsonResponse({'error': 'Compte introuvable.'}, status=404)
    profile = getattr(recipient, 'profile', None)
    return JsonResponse({
        'recipient_name': f"{recipient.first_name} {recipient.last_name}".strip() or recipient.username,
        'recipient_country': profile.address if profile and profile.address else 'Non défini',
        'recipient_currency': profile.preferred_currency if profile else 'USD',
        'recipient_account_code': recipient.account_code,
    })


@login_required
@require_POST
def transfer_funds(request):
    form = TransferForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)

    recipient_code = form.cleaned_data['recipient_account_code'].upper()
    source_account = form.cleaned_data['source_account']
    currency = form.cleaned_data['currency']
    amount = form.cleaned_data['amount']
    recipient = User.objects.filter(account_code__iexact=recipient_code).first()
    if not recipient:
        return JsonResponse({'error': 'Compte introuvable.'}, status=404)
    if recipient == request.user:
        return JsonResponse({'error': 'Vous ne pouvez pas transférer vers votre propre compte.'}, status=400)

    wallet = Wallet.objects.get_or_create(user=request.user)[0]
    recipient_wallet = Wallet.objects.get_or_create(user=recipient)[0]
    if wallet.is_blocked:
        return JsonResponse({'error': 'Votre compte est bloqué. Transfert impossible.'}, status=403)
    if not wallet.can_transfer and not is_principal_admin(request.user):
        return JsonResponse({'error': 'Transferts désactivés pour votre compte.'}, status=403)

    commission_breakdown = CommissionManager.get_transfer_commission_breakdown(amount, currency)
    fee_total = commission_breakdown['total_fee']
    system_fee = commission_breakdown['system_fee']
    agent_fee = commission_breakdown['agent_fee']

    sender_field = 'balance' if source_account == 'principal' else get_wallet_balance_field(currency, source_account)
    available_amount = getattr(wallet, sender_field, Decimal('0'))

    if source_account == 'principal' and currency != 'USD':
        total_deduction_usd = convert_currency(amount + fee_total, currency, 'USD')
    else:
        total_deduction_usd = amount + fee_total if currency == 'USD' else None

    if source_account == 'principal':
        if currency == 'USD':
            if available_amount < amount + fee_total:
                return JsonResponse({'error': 'Solde principal insuffisant.'}, status=400)
        else:
            if available_amount < total_deduction_usd:
                return JsonResponse({'error': 'Solde principal insuffisant pour ce montant et les frais.'}, status=400)
    else:
        if available_amount < amount + fee_total:
            return JsonResponse({'error': 'Solde Multi-appareils insuffisant.'}, status=400)

    with transaction.atomic():
        transfer = Transfer.objects.create(
            sender=request.user,
            receiver=recipient,
            sender_account_type=source_account,
            currency=currency,
            amount=amount,
            fee=fee_total,
            system_fee=system_fee,
            agent_fee=agent_fee,
            status='success',
        )

        Transaction.objects.create(
            sender=request.user,
            receiver=recipient,
            amount=amount,
            currency=currency,
            type='transfer',
            status='approved'
        )

        if source_account == 'principal':
            if currency == 'USD':
                wallet.balance -= (amount + fee_total)
                wallet.save(update_fields=['balance'])
                recipient_wallet.balance += amount
                recipient_wallet.save(update_fields=['balance'])
            else:
                wallet.balance -= total_deduction_usd
                wallet.save(update_fields=['balance'])
                recipient_field = get_wallet_balance_field(currency)
                current_value = getattr(recipient_wallet, recipient_field, Decimal('0'))
                setattr(recipient_wallet, recipient_field, current_value + amount)
                recipient_wallet.save(update_fields=[recipient_field])
        else:
            sender_balance = getattr(wallet, sender_field, Decimal('0'))
            setattr(wallet, sender_field, sender_balance - (amount + fee_total))
            wallet.save(update_fields=[sender_field])
            recipient_field = get_wallet_balance_field(currency)
            receiver_value = getattr(recipient_wallet, recipient_field, Decimal('0'))
            setattr(recipient_wallet, recipient_field, receiver_value + amount)
            recipient_wallet.save(update_fields=[recipient_field])

        system_wallet = get_system_admin_wallet()
        commission_field = get_commission_balance_field(currency)
        if system_wallet and system_fee > 0:
            current_system_commission = getattr(system_wallet, commission_field, Decimal('0'))
            setattr(system_wallet, commission_field, current_system_commission + system_fee)
            system_wallet.save(update_fields=[commission_field])

        if agent_fee > 0:
            if request.user.is_agent:
                current_agent_commission = getattr(wallet, get_commission_balance_field(currency), Decimal('0'))
                setattr(wallet, get_commission_balance_field(currency), current_agent_commission + agent_fee)
                wallet.save(update_fields=[get_commission_balance_field(currency)])
            elif system_wallet:
                current_system_commission = getattr(system_wallet, commission_field, Decimal('0'))
                setattr(system_wallet, commission_field, current_system_commission + agent_fee)
                system_wallet.save(update_fields=[commission_field])

        TransferLog.objects.create(
            transfer=transfer,
            action='Transfer completed',
            details=f"{request.user.username} sent {amount} {currency} from {source_account} to {recipient.username} (fee {fee_total}, system {system_fee}, agent {agent_fee})",
            actor=request.user,
        )

        admin_user = User.objects.filter(is_superuser=True).first()
        agent_user = request.user if request.user.is_agent else None
        receipt_base = f"RCPT-{transfer.transaction_id}"
        TransferReceipt.objects.create(
            transfer=transfer,
            user=request.user,
            role='sender',
            receipt_number=f"{receipt_base}-S",
            notes=f"Transfert vers {recipient.username} - Frais: {fee_total} {currency}"
        )
        TransferReceipt.objects.create(
            transfer=transfer,
            user=recipient,
            role='receiver',
            receipt_number=f"{receipt_base}-R",
            notes=f"Transfert reçu de {request.user.username}"
        )
        if admin_user:
            TransferReceipt.objects.create(
                transfer=transfer,
                user=admin_user,
                role='admin',
                receipt_number=f"{receipt_base}-A",
                notes=f"Admin receipt for transfer {transfer.transaction_id}"
            )
        if agent_user:
            TransferReceipt.objects.create(
                transfer=transfer,
                user=agent_user,
                role='agent',
                receipt_number=f"{receipt_base}-AG",
                notes=f"Agent involved in transfer {transfer.transaction_id}"
            )

        send_transfer_notification(
            transfer,
            request.user,
            'Transfert envoyé',
            f"Vous avez envoyé {amount} {currency} à {recipient.username}. Frais: {fee_total} {currency}"
        )
        send_transfer_notification(
            transfer,
            recipient,
            'Transfert reçu',
            f"Vous avez reçu {amount} {currency} de {request.user.username}."
        )
        if admin_user:
            send_transfer_notification(
                transfer,
                admin_user,
                'Nouveau transfert MicroSDICash',
                f"Transfert {transfer.transaction_id}: {request.user.username} → {recipient.username} ({amount} {currency}, frais {fee_total} {currency})."
            )
        if agent_user:
            send_transfer_notification(
                transfer,
                agent_user,
                'Transfert agent',
                f"Vous êtes l'agent concerné pour le transfert {transfer.transaction_id}. Commission agent: {agent_fee} {currency}."
            )

    return JsonResponse({
        'success': True,
        'transaction_id': transfer.transaction_id,
        'message': f'Transfert de {amount} {currency} envoyé avec succès.',
        'fee': str(fee_total),
        'system_fee': str(system_fee),
        'agent_fee': str(agent_fee),
    })


def sdi_sol_page(request):
    settings_obj = SDISolSettings.get_solo()
    members = list(SDISolMember.objects.filter(active=True, admin_approved=True).order_by('position', 'joined_at'))
    for member in members:
        member.update_status()
    SDISolMember.recalculate_rankings()
    members = list(SDISolMember.objects.filter(active=True, admin_approved=True).order_by('position', 'joined_at'))

    current_member = None
    pending_request = None
    if request.user.is_authenticated:
        current_member = SDISolMember.objects.filter(user=request.user, active=True, admin_approved=True).first()
        if not current_member:
            pending_request = SDISolMember.objects.filter(user=request.user, active=True, admin_approved=False).first()

    can_join = False
    join_message = ''
    if request.user.is_authenticated:
        if current_member:
            join_message = 'Vous faites déjà partie du Sol SDI.'
        elif pending_request:
            join_message = 'Votre demande de rejoindre le Sol SDI est en attente d’approbation admin. Merci de patienter.'
        elif len(members) >= settings_obj.max_members:
            join_message = 'Le Sol SDI est actuellement complet.'
        else:
            can_join = True
    else:
        join_message = 'Pour rejoindre le Sol SDI, vous devez être inscrit sur notre site SDI Marché Mondial.'

    return render(request, 'marketplace/sdi_sol.html', {
        'settings': settings_obj,
        'members': members,
        'current_member': current_member,
        'pending_request': pending_request,
        'can_join': can_join,
        'join_message': join_message,
    })


@login_required
@require_POST
def sdi_sol_join(request):
    settings_obj = SDISolSettings.get_solo()
    if SDISolMember.objects.filter(user=request.user, active=True).exists():
        pending_request = SDISolMember.objects.filter(user=request.user, active=True, admin_approved=False).exists()
        if pending_request:
            messages.info(request, 'Votre demande de rejoindre le Sol SDI est déjà en attente d’approbation admin.')
        else:
            messages.info(request, 'Vous êtes déjà membre du Sol SDI.')
        return redirect('sdi_sol')

    active_count = SDISolMember.objects.filter(active=True, admin_approved=True).count()
    if active_count >= settings_obj.max_members:
        messages.error(request, 'Le Sol SDI a atteint le nombre maximal de membres.')
        return redirect('sdi_sol')

    member = SDISolMember.objects.create(
        user=request.user,
        position=active_count + 1,
        status='pending',
        admin_approved=False,
    )
    member.schedule_next_due_date()
    member.save(update_fields=['position', 'next_due_date'])

    messages.success(request, 'Votre demande de rejoindre le Sol SDI a bien été enregistrée. Attendez l’approbation de l’admin.')
    return redirect('sdi_sol')


@login_required
def sdi_sol_payments(request):
    """Affiche l'historique des paiements de l'utilisateur pour le Sol SDI"""
    try:
        member = SDISolMember.objects.get(user=request.user, active=True)
    except SDISolMember.DoesNotExist:
        messages.error(request, 'Vous n\'êtes pas membre du Sol SDI.')
        return redirect('sdi_sol')

    if not member.admin_approved:
        messages.error(request, 'Votre adhésion doit être approuvée par un admin avant d\'accéder à vos paiements.')
        return redirect('sdi_sol')
    
    payments = member.payments.all().order_by('-created_at')
    
    return render(request, 'marketplace/sdi_sol_payments.html', {
        'member': member,
        'payments': payments,
        'settings': SDISolSettings.get_solo(),
    })


@login_required
@require_POST
def sdi_sol_make_payment(request):
    """Enregistre un paiement pour le membre du Sol SDI"""
    try:
        member = SDISolMember.objects.get(user=request.user, active=True)
    except SDISolMember.DoesNotExist:
        return JsonResponse({'error': 'Vous n\'êtes pas membre du Sol SDI.'}, status=400)

    if not member.admin_approved:
        return JsonResponse({'error': 'Votre adhésion doit être approuvée par un admin avant de payer.'}, status=403)
    
    settings_obj = SDISolSettings.get_solo()
    amount = request.POST.get('amount')
    currency = request.POST.get('currency', 'USD')
    
    if not amount or not currency:
        return JsonResponse({'error': 'Données manquantes.'}, status=400)
    
    try:
        amount = Decimal(amount)
    except (InvalidOperation, TypeError):
        return JsonResponse({'error': 'Montant invalide.'}, status=400)
    
    # Vérifier que le montant correspond à la cotisation
    if currency == 'USD':
        if amount < settings_obj.contribution_amount_usd:
            return JsonResponse({
                'error': f'Le montant minimum est ${settings_obj.contribution_amount_usd}'
            }, status=400)
    elif currency == 'HTG':
        if amount < settings_obj.contribution_amount_htg:
            return JsonResponse({
                'error': f'Le montant minimum est {settings_obj.contribution_amount_htg} HTG'
            }, status=400)
    
    # Créer le paiement
    with transaction.atomic():
        payment = SDISolPayment.objects.create(
            member=member,
            amount=amount,
            currency=currency,
            fee=Decimal('0.00'),
            due_date=member.next_due_date or timezone.now(),
        )
        
        # Marquer le paiement comme effectué
        payment.mark_paid()
        
        # Recalculer les classements
        SDISolMember.recalculate_rankings()
        
        # Créer une notification
        notification = PersistentNotification.objects.create(
            recipient=request.user,
            title='Paiement Sol SDI reçu ✅',
            message=f'Votre paiement de {amount} {currency} pour le Sol SDI a été enregistré. Reçu: {payment.receipt_number}',
            notification_type='sdi_sol_payment',
        )
    
    return JsonResponse({
        'success': True,
        'receipt_number': payment.receipt_number,
        'message': f'Paiement enregistré avec succès. Reçu: {payment.receipt_number}'
    })


@login_required
def sdi_sol_payment_receipt(request, receipt_id):
    """Affiche un reçu de paiement pour le Sol SDI"""
    payment = get_object_or_404(SDISolPayment, receipt_number=receipt_id)
    
    if payment.member.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden('Accès non autorisé.')
    
    return render(request, 'marketplace/sdi_sol_receipt.html', {
        'payment': payment,
    })


@user_passes_test(lambda u: u.is_staff)
def sdi_sol_admin(request):
    """Panel d'administration du Sol SDI"""
    settings_obj = SDISolSettings.get_solo()
    members = SDISolMember.objects.filter(active=True, admin_approved=True).order_by('position')
    pending_requests = SDISolMember.objects.filter(active=True, admin_approved=False).order_by('joined_at')
    payments = SDISolPayment.objects.all().order_by('-created_at')[:20]
    late_members = members.filter(status='late')
    
    if request.method == 'POST':
        # Mettre à jour les paramètres
        max_members = request.POST.get('max_members')
        contribution_usd = request.POST.get('contribution_usd')
        contribution_htg = request.POST.get('contribution_htg')
        frequency = request.POST.get('frequency')
        withdrawal_fee_usd = request.POST.get('withdrawal_fee_usd')
        withdrawal_fee_htg = request.POST.get('withdrawal_fee_htg')
        
        try:
            if max_members:
                settings_obj.max_members = int(max_members)
            if contribution_usd:
                settings_obj.contribution_amount_usd = Decimal(contribution_usd)
            if contribution_htg:
                settings_obj.contribution_amount_htg = Decimal(contribution_htg)
            if frequency:
                settings_obj.frequency = frequency
            if withdrawal_fee_usd:
                settings_obj.withdrawal_fee_usd = Decimal(withdrawal_fee_usd)
            if withdrawal_fee_htg:
                settings_obj.withdrawal_fee_htg = Decimal(withdrawal_fee_htg)
            
            settings_obj.save()
            messages.success(request, 'Paramètres du Sol SDI mis à jour.')
            return redirect('sdi_sol_admin')
        except (ValueError, InvalidOperation) as e:
            messages.error(request, f'Erreur: {str(e)}')
    
    return render(request, 'marketplace/sdi_sol_admin.html', {
        'settings': settings_obj,
        'members': members,
        'pending_requests': pending_requests,
        'payments': payments,
        'late_members': late_members,
        'total_members': members.count(),
        'pending_requests_count': pending_requests.count(),
        'total_payments': SDISolPayment.objects.count(),
    })


@user_passes_test(lambda u: u.is_staff)
@require_POST
def sdi_sol_admin_approve_member(request, member_id):
    """Approuver une demande de membre du Sol SDI"""
    member = get_object_or_404(SDISolMember, id=member_id, active=True, admin_approved=False)
    settings_obj = SDISolSettings.get_solo()
    approved_count = SDISolMember.objects.filter(active=True, admin_approved=True).count()
    if approved_count >= settings_obj.max_members:
        messages.error(request, 'Impossible d\'approuver ce membre : le Sol SDI est déjà plein.')
        return redirect('sdi_sol_admin')

    member.approve()
    SDISolMember.recalculate_rankings()
    messages.success(request, f'Membre {member.user.username} approuvé avec succès.')
    return redirect('sdi_sol_admin')


@user_passes_test(lambda u: u.is_staff)
@require_POST
def sdi_sol_admin_remove_member(request, member_id):
    """Retirer un membre du Sol SDI"""
    member = get_object_or_404(SDISolMember, id=member_id)
    member.active = False
    member.save()
    
    # Recalculer les classements
    SDISolMember.recalculate_rankings()
    
    messages.success(request, f'Membre {member.user.username} retiré du Sol SDI.')
    return redirect('sdi_sol_admin')


def get_private_contacts(user):
    """Retourne la liste des conversations privées avec métadonnées pour l'affichage."""
    conversations = PrivateConversation.objects.filter(
        Q(user1=user) | Q(user2=user)
    ).select_related('user1__profile', 'user2__profile')

    contacts = []
    for conv in conversations:
        other = conv.other_user(user)
        last_message = conv.latest_message()
        profile = getattr(other, 'profile', None)
        contacts.append({
            'user': other,
            'conversation': conv,
            'contact_id': other.id,
            'partner_name': other.get_full_name() or other.username,
            'partner_photo_url': profile.photo.url if profile and profile.photo else None,
            'unread_count': conv.unread_count_for(user),
            'last_message_text': last_message.content if last_message and last_message.content else 'Message partagé',
            'last_message_time': last_message.created_at if last_message else None,
            'last_message_sender': 'Vous' if last_message and last_message.sender == user else (other.get_full_name() or other.username),
        })

    return contacts


def has_purchased_product(user, product):
    """Vérifie si l'utilisateur a acheté ce produit et que la commande a été livrée."""
    return OrderItem.objects.filter(
        order__buyer=user,
        product=product,
    ).filter(
        order__status='delivered'
    ).exists() or OrderItem.objects.filter(
        order__buyer=user,
        product=product,
        order__date_reception_confirmee__isnull=False
    ).exists()


@require_POST
def set_currency(request):
    currency = request.POST.get('currency')
    if currency:
        currency = normalize_currency(currency)
        if currency in ['USD', 'HTG', 'DOP', 'EUR']:
            request.session['currency'] = currency
            if request.user.is_authenticated:
                profile = getattr(request.user, 'profile', None)
                if profile:
                    profile.preferred_currency = currency
                    profile.save(update_fields=['preferred_currency'])

    return redirect(request.META.get('HTTP_REFERER', '/'))


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calcule la distance en km entre deux points GPS (formule de Haversine)"""
    from math import radians, sin, cos, sqrt, atan2

    # Convertir en radians
    lat1, lon1 = radians(float(lat1)), radians(float(lon1))
    lat2, lon2 = radians(float(lat2)), radians(float(lon2))

    # Différences
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Formule de Haversine
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    # Distance en km (rayon terrestre = 6371 km)
    distance = 6371 * c
    return distance


def get_global_chat_group():
    group = ChatGroup.get_global_group()
    return group


def add_user_to_global_group(user):
    if user and user.is_active:
        group = get_global_chat_group()
        group.add_participant(user)
        return group
    return None


def get_agent_fund_managers_group():
    group, created = Group.objects.get_or_create(name='AgentFundManagers')
    return group


def user_has_agent_fund_access(user):
    group = get_agent_fund_managers_group()
    return group in user.groups.all()


def mark_group_messages_as_read(group, user):
    if not user or user.is_anonymous:
        return 0
    unread_messages = group.messages.exclude(read_receipts__user=user)
    read_records = [ChatMessageRead(message=msg, user=user) for msg in unread_messages]
    ChatMessageRead.objects.bulk_create(read_records, ignore_conflicts=True)
    return unread_messages.count()


def create_advertisement_messages(group, count=2):
    if not group:
        return
    recent_ads = group.messages.filter(is_advertisement=True, created_at__gte=timezone.now() - timedelta(hours=2)).count()
    if recent_ads >= count:
        return
    products = list(Product.objects.filter(quantity__gt=0).order_by('-created_at')[:12])
    if not products:
        return
    ads = sample(products, min(count, len(products)))
    for product in ads:
        if not group.messages.filter(product=product, is_advertisement=True).exists():
            ChatMessage.objects.create(
                group=group,
                sender=None,
                content=f"Découvre {product.name} à ${product.price_ht} !",
                product=product,
                is_system=True,
                is_advertisement=True,
            )


def auto_assign_delivery_employee(order):
    """Assigne automatiquement un employé de livraison disponible"""
    from .models import DeliveryEmployee, DeliveryAssignment, DeliveryTracking

    # Extraire les coordonnées de l'adresse de livraison (simulation)
    # En production, utiliser un service de géocodage
    delivery_lat = 48.8566  # Paris par défaut (à remplacer par géocodage réel)
    delivery_lng = 2.3522

    # Trouver les employés disponibles dans la zone
    available_employees = DeliveryEmployee.objects.filter(
        is_available=True,
        assigned_zone__icontains=order.delivery_address.split()[-1]  # Zone simple
    ).exclude(
        # Exclure les employés déjà assignés à trop de commandes
        deliveryassignment__status__in=['assigned', 'picked_up', 'in_transit']
    ).distinct()

    best_employee = None
    min_distance = float('inf')

    for employee in available_employees:
        if employee.current_latitude and employee.current_longitude:
            distance = calculate_distance(
                employee.current_latitude, employee.current_longitude,
                delivery_lat, delivery_lng
            )
            if distance <= employee.max_delivery_radius and distance < min_distance:
                min_distance = distance
                best_employee = employee

    if best_employee:
        # Créer l'assignation
        assignment = DeliveryAssignment.objects.create(
            employee=best_employee,
            order=order,
            status='assigned',
            estimated_delivery_time=timezone.now() + timedelta(hours=2)  # Estimation simple
        )

        # Créer le premier tracking
        DeliveryTracking.objects.create(
            assignment=assignment,
            status_update="Commande assignée au livreur",
            estimated_eta=assignment.estimated_delivery_time
        )

        # Créer une notification pour le client
        create_delivery_notification(
            assignment,
            order.buyer,
            'status_update',
            'Commande assignée',
            f'Votre commande a été assignée à {best_employee.user.get_full_name() or best_employee.identifier}'
        )

        return assignment

    return None

def create_delivery_notification(assignment, recipient, notification_type, title, message):
    """Crée une notification de livraison"""
    from .models import DeliveryNotification

    notification = DeliveryNotification.objects.create(
        assignment=assignment,
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message
    )
    return notification

def update_delivery_tracking(assignment, latitude=None, longitude=None, location_name=None, status_update=None):
    """Met à jour le suivi GPS et crée une entrée de tracking"""
    from .models import DeliveryTracking

    # Mettre à jour la position de l'employé
    if latitude and longitude:
        assignment.employee.update_location(latitude, longitude, location_name)

    # Créer une entrée de tracking
    tracking = DeliveryTracking.objects.create(
        assignment=assignment,
        latitude=latitude,
        longitude=longitude,
        location_name=location_name,
        status_update=status_update or f"Statut mis à jour: {assignment.get_status_display()}"
    )

    # Créer des notifications selon le statut
    if assignment.status == 'picked_up':
        create_delivery_notification(
            assignment, assignment.order.buyer, 'status_update',
            'Commande récupérée', 'Votre commande a été récupérée par le livreur'
        )
    elif assignment.status == 'in_transit':
        create_delivery_notification(
            assignment, assignment.order.buyer, 'status_update',
            'En cours de livraison', 'Votre commande est en route vers votre adresse'
        )
    elif assignment.status == 'arrived':
        create_delivery_notification(
            assignment, assignment.order.buyer, 'arrival',
            'Livreur arrivé', 'Le livreur est arrivé à votre adresse'
        )
    elif assignment.status == 'delivered':
        create_delivery_notification(
            assignment, assignment.order.buyer, 'delivered',
            'Commande livrée', 'Votre commande a été livrée avec succès'
        )

    return tracking

# ------------------------------
# Frontend views
# ------------------------------

def home(request):
    query = request.GET.get('q', '')
    category_slug = request.GET.get('category', '')
    
    # Filtrer les produits
    products = Product.objects.filter(quantity__gt=0).select_related('shop')
    
    if query:
        products = products.filter(name__icontains=query)
    
    if category_slug:
        try:
            category = Category.objects.get(slug=category_slug, is_active=True)
        except Category.DoesNotExist:
            products = products.none()
        else:
            category_ids = [category.id]
            category_ids.extend([child.id for child in category.children.filter(is_active=True)])
            products = products.filter(category_id__in=category_ids)
    
    shops = Shop.objects.all()
    
    # Recommandations personnalisées ou tendances
    if request.user.is_authenticated:
        recommendations = get_personalized_recommendations(request.user, limit=6)
    else:
        recommendations = get_trending_products(limit=6)
    
    # Récupérer les catégories principales pour le menu
    main_categories = CategoryManager.get_main_categories()
    # Filtrer les catégories avec slugs invalides et ajouter le nombre de produits
    main_categories = [cat for cat in main_categories if cat.get('slug') and cat['slug'].strip()]
    for category in main_categories:
        category['products_count'] = CategoryManager.get_category_products_count(category['id'])
    
    # Attacher les stats d'avis
    attach_reviews_stats(products)
    attach_reviews_stats(recommendations)
    return render(request, 'marketplace/home.html', {
        'products': products,
        'shops': shops,
        'query': query,
        'current_category': category_slug,
        'main_categories': main_categories,
        'recommendations': recommendations,
    })


def formations_en_ligne(request):
    return render(request, 'marketplace/formations_en_ligne.html')


def sdi_transport(request):
    if request.method == 'POST':
        honeypot = request.POST.get('website', '')
        if honeypot:
            messages.error(request, "La soumission a été rejetée pour des raisons de sécurité.")
            return redirect('sdi_transport')

        required_fields = {
            'first_name': 'Nom',
            'last_name': 'Prénom',
            'birth_date': 'Date de naissance',
            'address': 'Adresse complète',
            'phone': 'Téléphone',
            'email': 'Email',
            'experience_years': 'Années d’expérience',
            'vehicle_type': 'Type de véhicule conduit',
            'license_category': 'Permis (catégorie)',
            'experience_description': 'Description de l’expérience',
        }

        errors = []
        for field, label in required_fields.items():
            if not request.POST.get(field, '').strip():
                errors.append(f"Le champ {label} est requis.")

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            media_root = get_media_root()
            storage = FileSystemStorage(location=os.path.join(media_root, 'sdi_transport_applications'))

            for upload_field in ['identity_photo', 'driver_license', 'resume']:
                uploaded_file = request.FILES.get(upload_field)
                if uploaded_file:
                    sanitized_name = re.sub(r'[^0-9a-zA-Z_.-]', '_', uploaded_file.name)
                    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
                    storage.save(f"{timestamp}_{upload_field}_{sanitized_name}", uploaded_file)

            messages.success(request, "✔ Candidature envoyée avec succès. SDI Transport vous contactera bientôt.")
            return redirect('sdi_transport')

    return render(request, 'marketplace/sdi_transport.html', {
        'form_data': request.POST.dict() if request.method == 'POST' else {},
    })


def get_media_root():
    media_root = getattr(settings, 'MEDIA_ROOT', None)
    if media_root:
        return media_root
    base_dir = getattr(settings, 'BASE_DIR', None)
    if base_dir:
        return os.path.join(base_dir, 'media')
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'media')


def _escape_pdf_text(text):
    return text.replace('(', '\\(').replace(')', '\\)').replace('\\', '\\\\')


def generate_simple_pdf(course_title, student_name, certificate_title, issued_date):
    content_lines = [
        f'BT /F1 18 Tf 72 760 Td ({_escape_pdf_text(certificate_title)}) Tj ET',
        f'BT /F1 12 Tf 72 720 Td (Étudiant : {_escape_pdf_text(student_name)}) Tj ET',
        f'BT /F1 12 Tf 72 700 Td (Cours : {_escape_pdf_text(course_title)}) Tj ET',
        f'BT /F1 12 Tf 72 680 Td (Date : {_escape_pdf_text(issued_date)}) Tj ET',
        f'BT /F1 12 Tf 72 640 Td (Félicitations pour votre réussite !) Tj ET',
    ]
    content = '\n'.join(content_lines).encode('latin1')

    objects = []
    offsets = []

    def add_object(data: bytes):
        offsets.append(pdf.tell())
        pdf.write(data)

    pdf = io.BytesIO()
    pdf.write(b'%PDF-1.4\n')
    add_object(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    add_object(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')
    add_object(
        b'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]'
        b' /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n'
    )
    add_object(b'4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n')
    add_object(b'5 0 obj\n<< /Length ' + str(len(content)).encode('latin1') + b' >>\nstream\n' + content + b'\nendstream\nendobj\n')

    xref_start = pdf.tell()
    pdf.write(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets:
        pdf.write(f'{offset:010d} 00000 n \n'.encode('latin1'))
    pdf.write(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n')
    pdf.write(str(xref_start).encode('latin1'))
    pdf.write(b'\n%%EOF\n')
    return pdf.getvalue()


def ensure_demo_course(course_id, user=None):
    course, created = Course.objects.get_or_create(
        id=course_id,
        defaults={
            'title': f'Cours SDI #{course_id} - Exemple',
            'slug': f'cours-sdi-{course_id}',
            'description': 'Détail du cours, syllabus, sessions et ressources.',
            'instructor': 'Prof. SDI',
            'next_session': timezone.now() + timedelta(hours=2),
            'is_published': True,
        }
    )
    if not CourseAssignment.objects.filter(course=course).exists():
        CourseAssignment.objects.create(
            course=course,
            title='Projet module 1',
            description='Travail de synthèse sur le module 1.',
            due_date=timezone.now().date() + timedelta(days=5),
        )
        CourseAssignment.objects.create(
            course=course,
            title='Quiz semaine',
            description='Quiz de validation des acquis de la semaine.',
            due_date=timezone.now().date() + timedelta(days=2),
        )
    if user and user.is_authenticated:
        CourseCertificate.objects.get_or_create(
            course=course,
            user=user,
            title='Diplôme de réussite SDI',
            defaults={
                'issued_date': timezone.now().date(),
                'status': 'available',
            }
        )
        CourseCertificate.objects.get_or_create(
            course=course,
            user=user,
            title='Attestation de présence',
            defaults={
                'issued_date': timezone.now().date(),
                'status': 'available',
            }
        )
    return course


def get_course_data(request, course_id):
    course = ensure_demo_course(course_id, request.user)
    assignments = list(course.assignments.all())
    submissions = list(AssignmentSubmission.objects.filter(user=request.user, assignment__course=course).select_related('assignment').order_by('-submitted_at'))
    submitted_assignment_ids = {submission.assignment_id for submission in submissions}
    for assignment in assignments:
        assignment.display_status = 'Soumis' if assignment.id in submitted_assignment_ids else 'À rendre'
        assignment.submitted_at = next((submission.submitted_at for submission in submissions if submission.assignment_id == assignment.id), None)
    completed = len(submitted_assignment_ids)
    progress = int((completed / len(assignments)) * 100) if assignments else 0
    course.demo_assignments = assignments
    course.recordings = [
        {'title': 'Session 2026-06-01', 'url': '#', 'length': '45 min'},
        {'title': 'Session 2026-06-03', 'url': '#', 'length': '38 min'},
    ]
    course.progress = progress
    course.completed_assignments = completed
    course.total_assignments = len(assignments)
    course.certificates = list(CourseCertificate.objects.filter(course=course, user=request.user))
    return course


@login_required
def course_detail(request, course_id):
    course = get_course_data(request, course_id)
    return render(request, 'marketplace/course_detail.html', {'course': course})


@login_required
def live_room_webrtc(request, course_id):
    course = ensure_demo_course(course_id, request.user)
    return render(request, 'marketplace/live_room_webrtc.html', {'course': course})


@login_required
def live_room_jitsi(request, course_id):
    course = ensure_demo_course(course_id, request.user)
    jitsi_room = f'SDI-course-{course_id}'
    return render(request, 'marketplace/live_room_jitsi.html', {'course': course, 'jitsi_room': jitsi_room})


@login_required
def course_assignments(request, course_id):
    course = get_course_data(request, course_id)
    submissions = AssignmentSubmission.objects.filter(user=request.user, assignment__course=course).select_related('assignment').order_by('-submitted_at')
    if request.method == 'POST':
        form = AssignmentSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            assignment_title = form.cleaned_data['assignment_title']
            comments = form.cleaned_data['comments']
            uploaded_file = form.cleaned_data['submission_file']
            assignment, _ = CourseAssignment.objects.get_or_create(
                course=course,
                title__iexact=assignment_title,
                defaults={
                    'title': assignment_title,
                    'description': 'Soumission créée par l\'utilisateur.',
                    'due_date': timezone.now().date() + timedelta(days=7),
                }
            )
            AssignmentSubmission.objects.create(
                assignment=assignment,
                user=request.user,
                file=uploaded_file,
                comments=comments,
                status='submitted'
            )
            messages.success(request, 'Votre devoir a bien été soumis. Merci !')
            return redirect('course_assignments', course_id=course_id)
    else:
        form = AssignmentSubmissionForm()
    return render(request, 'marketplace/course_assignments.html', {
        'course': course,
        'form': form,
        'submissions': submissions,
    })


@login_required
def course_recordings(request, course_id):
    course = get_course_data(request, course_id)
    return render(request, 'marketplace/course_recordings.html', {'course': course})


@login_required
def course_certificates(request, course_id):
    course = get_course_data(request, course_id)
    return render(request, 'marketplace/course_certificates.html', {'course': course})


@login_required
def course_certificate_pdf(request, course_id, certificate_id):
    certificate = get_object_or_404(
        CourseCertificate,
        id=certificate_id,
        course_id=course_id,
        user=request.user,
        status='available'
    )
    student_name = 'Apprenant SDI'
    if hasattr(request.user, 'get_full_name'):
        student_name = request.user.get_full_name() or getattr(request.user, 'username', student_name)
    elif hasattr(request.user, 'username'):
        student_name = getattr(request.user, 'username', student_name)
    pdf_content = generate_simple_pdf(
        certificate.course.title,
        student_name,
        certificate.title,
        certificate.issued_date.strftime('%Y-%m-%d') if certificate.issued_date else timezone.now().date().strftime('%Y-%m-%d')
    )
    filename = slugify(certificate.title) or 'certificat'
    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    return response


def marche_mondial(request):
    """Page Marché Mondial en architecture modulaire"""
    return render(request, 'marketplace/marche_mondial.html')


def manage_projet(request):
    submitted = False
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        project_type = request.POST.get('project_type', '').strip()
        if full_name and email and phone:
            messages.success(request, 'Votre demande de gestion de projet a bien été reçue. Notre équipe vous contactera rapidement.')
            submitted = True
        else:
            messages.error(request, 'Merci de renseigner au minimum votre nom, votre email et votre téléphone.')

    return render(request, 'marketplace/manage_projet.html', {
        'submitted': submitted,
    })


def search(request):
    query = request.GET.get('q', '')
    category_slug = request.GET.get('category', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    seller = request.GET.get('seller', '')
    rating = request.GET.get('rating', '')
    stock = request.GET.get('stock', '')
    sort_by = request.GET.get('sort', '')

    products = Product.objects.select_related('shop', 'category').all()

    # Recherche multi-critères
    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query) |
            Q(shop__name__icontains=query) |
            Q(shop__owner__username__icontains=query)
        )

    if category_slug:
        products = products.filter(category__slug=category_slug)

    if min_price:
        try:
            products = products.filter(price_ht__gte=float(min_price))
        except ValueError:
            pass

    if max_price:
        try:
            products = products.filter(price_ht__lte=float(max_price))
        except ValueError:
            pass

    if seller:
        products = products.filter(
            Q(shop__name__icontains=seller) |
            Q(shop__owner__username__icontains=seller)
        )

    if stock == 'in_stock':
        products = products.filter(quantity__gt=0)
    elif stock == 'out_of_stock':
        products = products.filter(quantity__lte=0)

    products = products.annotate(
        average_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
        reviews_count=Count('reviews', filter=Q(reviews__is_approved=True))
    )

    if rating:
        try:
            minimum_rating = float(rating)
            products = products.filter(average_rating__gte=minimum_rating)
        except ValueError:
            pass

    if sort_by == 'price_asc':
        products = products.order_by('price_ht')
    elif sort_by == 'price_desc':
        products = products.order_by('-price_ht')
    elif sort_by == 'rating_desc':
        products = products.order_by('-average_rating')
    elif sort_by == 'popularity':
        products = products.order_by('-reviews_count')
    else:
        products = products.order_by('-average_rating', '-reviews_count')

    categories = Category.objects.filter(is_active=True)

    return render(request, 'marketplace/search.html', {
        'products': products,
        'query': query,
        'categories': categories,
        'selected_category': category_slug,
        'min_price': min_price,
        'max_price': max_price,
        'seller': seller,
        'selected_rating': rating,
        'selected_stock': stock,
        'selected_sort': sort_by,
    })


def autocomplete_products(request):
    query = request.GET.get('q', '')
    results = []
    if query:
        products = Product.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        ).order_by('name')[:10]
        results = [{'id': p.id, 'name': p.name} for p in products]
    return JsonResponse({'results': results})


@login_required
def chat(request):
    group = add_user_to_global_group(request.user)
    create_advertisement_messages(group)

    product_to_share = None
    product_id = request.GET.get('product_to_share')
    if product_id:
        product_to_share = Product.objects.filter(id=product_id, quantity__gt=0).first()

    if request.method == 'POST':
        form = ChatMessageForm(request.POST, request.FILES)
        if form.is_valid():
            message = form.save(commit=False)
            message.group = group
            message.sender = request.user
            message.is_system = False
            message.save()
            return redirect('chat')
    else:
        initial = {'product': product_to_share} if product_to_share else {}
        form = ChatMessageForm(initial=initial)

    chat_messages = group.messages.select_related('sender', 'product').prefetch_related(
        Prefetch('read_receipts', queryset=ChatMessageRead.objects.filter(user=request.user), to_attr='read_by_user')
    ).order_by('created_at')[:120]
    unread_count = group.messages.exclude(read_receipts__user=request.user).count()
    private_contacts = get_private_contacts(request.user)

    return render(request, 'marketplace/chat.html', {
        'group': group,
        'form': form,
        'chat_messages': chat_messages,
        'selected_product': product_to_share,
        'unread_message_count': unread_count,
        'private_contacts': private_contacts,
    })


@login_required
def chat_messages_api(request):
    group = get_global_chat_group()
    since = request.GET.get('since')
    messages_qs = group.messages.select_related('sender', 'product').prefetch_related(
        Prefetch('read_receipts', queryset=ChatMessageRead.objects.filter(user=request.user), to_attr='read_by_user')
    ).order_by('created_at')
    if since:
        try:
            since_date = timezone.datetime.fromisoformat(since)
            if timezone.is_naive(since_date):
                since_date = timezone.make_aware(since_date)
            messages_qs = messages_qs.filter(created_at__gt=since_date)
        except ValueError:
            pass

    messages_data = []
    unread_messages = []
    for msg in messages_qs.order_by('created_at'):
        is_read = bool(getattr(msg, 'read_by_user', []))
        messages_data.append({
            'id': msg.id,
            'sender': msg.sender.get_full_name() if msg.sender else 'Système',
            'content': msg.content,
            'image_url': msg.image.url if msg.image else None,
            'product': {
                'id': msg.product.id,
                'name': msg.product.name,
                'price': str(msg.product.price_ht),
                'image': str(msg.product.get_primary_image()) if msg.product else None,
            } if msg.product else None,
            'is_system': msg.is_system,
            'is_advertisement': msg.is_advertisement,
            'is_read': is_read,
            'created_at': msg.created_at.isoformat(),
        })
        if not is_read:
            unread_messages.append(msg)

    if unread_messages:
        ChatMessageRead.objects.bulk_create(
            [ChatMessageRead(message=msg, user=request.user) for msg in unread_messages],
            ignore_conflicts=True
        )

    return JsonResponse({'messages': messages_data})


@login_required
def private_chat_contacts(request):
    contacts = User.objects.filter(is_active=True).exclude(id=request.user.id).order_by('username')
    conversations = PrivateConversation.objects.filter(
        Q(user1=request.user) | Q(user2=request.user)
    ).prefetch_related('messages')

    conversation_map = {}
    for conversation in conversations:
        other = conversation.other_user(request.user)
        conversation_map[other.id] = conversation

    contacts_data = []
    for contact in contacts:
        conversation = conversation_map.get(contact.id)
        last_message = conversation.latest_message() if conversation else None
        contacts_data.append({
            'user': contact,
            'conversation': conversation,
            'unread_count': conversation.unread_count_for(request.user) if conversation else 0,
            'last_message': last_message,
        })

    return render(request, 'marketplace/private_chat_contacts.html', {
        'contacts': contacts_data,
    })


@login_required
def private_chat(request, user_id):
    if request.user.id == user_id:
        messages.error(request, 'Vous ne pouvez pas ouvrir une conversation privée avec vous-même.')
        return redirect('private_chat_contacts')

    other_user = get_object_or_404(User, id=user_id, is_active=True)
    conversation, _ = PrivateConversation.get_or_create(request.user, other_user)

    if request.method == 'POST':
        form = PrivateMessageForm(request.POST, request.FILES)
        if form.is_valid():
            private_message = form.save(commit=False)
            private_message.conversation = conversation
            private_message.sender = request.user
            private_message.receiver = other_user
            private_message.is_read = False
            private_message.save()
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            return redirect('private_chat', user_id=user_id)
    else:
        form = PrivateMessageForm()

    chat_messages = conversation.messages.select_related('sender', 'receiver', 'product').all()
    conversation.messages.filter(receiver=request.user, is_read=False).update(is_read=True)

    contacts = User.objects.filter(is_active=True).exclude(id=request.user.id).order_by('username')
    conversations = PrivateConversation.objects.filter(
        Q(user1=request.user) | Q(user2=request.user)
    )
    conversation_map = {conv.other_user(request.user).id: conv for conv in conversations}

    contacts_data = []
    for contact in contacts:
        conv = conversation_map.get(contact.id)
        contacts_data.append({
            'user': contact,
            'conversation': conv,
            'unread_count': conv.unread_count_for(request.user) if conv else 0,
        })

    return render(request, 'marketplace/private_chat.html', {
        'conversation': conversation,
        'other_user': other_user,
        'chat_messages': chat_messages,
        'form': form,
        'contacts': contacts_data,
    })


@login_required
def private_chat_unread_count_api(request):
    unread_count = PrivateMessage.objects.filter(receiver=request.user, is_read=False).count()
    return JsonResponse({'unread_count': unread_count})


@login_required
def private_chat_messages_api(request, user_id):
    other_user = get_object_or_404(User, id=user_id, is_active=True)
    conversation, _ = PrivateConversation.get_or_create(request.user, other_user)
    messages_qs = conversation.messages.select_related('sender', 'receiver', 'product').order_by('created_at')

    messages_data = []
    for msg in messages_qs:
        messages_data.append({
            'id': msg.id,
            'sender': msg.sender.get_full_name() if msg.sender else 'Système',
            'content': msg.content,
            'image_url': msg.image.url if msg.image else None,
            'product': {
                'id': msg.product.id,
                'name': msg.product.name,
                'price': str(msg.product.price_ht),
                'image': str(msg.product.get_primary_image()) if msg.product else None,
            } if msg.product else None,
            'is_read': msg.is_read,
            'receiver': msg.receiver.username,
            'created_at': msg.created_at.isoformat(),
        })
    return JsonResponse({'messages': messages_data})


def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            address = form.cleaned_data.get('address', '')
            phone = form.cleaned_data.get('phone', '')
            photo = form.cleaned_data.get('photo')
            identity_document = form.cleaned_data.get('identity_document')
            receipt_proof = form.cleaned_data.get('receipt_proof')
            profile, created = Profile.objects.get_or_create(user=user)
            profile.address = address
            profile.phone = phone
            if photo:
                profile.photo = photo
            if identity_document:
                profile.identity_document = identity_document
            if receipt_proof:
                profile.receipt_proof = receipt_proof
            profile.save()
            login(request, user)
            add_user_to_global_group(user)
            messages.success(request, 'Inscription réussie. Bienvenue !')
            return redirect('home')
    else:
        form = SignUpForm()
    return render(request, 'marketplace/signup.html', {'form': form})


@login_required
def request_delivery_access(request):
    profile = getattr(request.user, 'profile', None)
    if not profile:
        profile = Profile.objects.create(user=request.user)

    if request.user.is_delivery_agent or profile.delivery_access_granted:
        messages.info(request, 'Votre accès livreur est déjà activé.')
    elif not request.user.can_request_delivery:
        messages.warning(request, 'Vous ne pouvez pas faire cette demande pour le moment.')
    else:
        profile.delivery_access_requested = True
        profile.save()
        messages.success(request, 'Demande d’accès livreur envoyée. Un administrateur doit l’activer.')

    return redirect('profile')


def login_view(request):
    username = ''
    remember = False
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        remember = request.POST.get('remember') == 'on'
        ip = get_client_ip(request)

        if not AnomalyDetector.check_brute_force(ip, '/login/'):
            messages.error(request, 'Trop de tentatives. Réessayez plus tard.')
        elif username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if remember:
                    request.session.set_expiry(1209600)  # 14 jours
                else:
                    request.session.set_expiry(0)  # expire à la fermeture du navigateur
                add_user_to_global_group(user)
                messages.success(request, 'Connexion réussie.')
                return redirect('search')
            AnomalyDetector.record_failed_login(ip, username)
            messages.error(request, 'Identifiants invalides.')
        else:
            messages.error(request, 'Veuillez renseigner le nom d’utilisateur et le mot de passe.')

    return render(request, 'marketplace/login.html', {'username': username, 'remember': remember})


def password_reset_request(request):
    return render(request, 'marketplace/password_reset_request.html')


@login_required
def logout_view(request):
    logout(request)
    return redirect('search')


def category_products(request, category_slug):
    """Vue pour afficher les produits d'une catégorie"""
    try:
        category = Category.objects.get(slug=category_slug, is_active=True)
    except Category.DoesNotExist:
        messages.error(request, 'Catégorie non trouvée.')
        return redirect('home')
    
    # Récupérer tous les IDs de catégories (catégorie actuelle + sous-catégories)
    category_ids = [category.id]
    children = category.children.filter(is_active=True)
    category_ids.extend([child.id for child in children])
    
    products = Product.objects.filter(
        quantity__gt=0,
        category_id__in=category_ids
    ).select_related('shop')
    
    # Recherche dans la catégorie
    query = request.GET.get('q', '')
    if query:
        products = products.filter(name__icontains=query)
    
    # Statistiques de la catégorie
    total_products = products.count()
    
    # Attacher les stats d'avis
    attach_reviews_stats(products)
    
    return render(request, 'marketplace/category_products.html', {
        'category': category,
        'products': products,
        'query': query,
        'total_products': total_products,
    })


@login_required
def cart_view(request):
    """Vue pour afficher le panier de l'utilisateur"""
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = cart.items.select_related('product__shop').all()

    # Calculer la quantité totale et le cashback
    total_quantity = sum(item.quantity for item in cart_items)
    cashback = calcul_cashback(total_quantity)

    return render(request, 'marketplace/cart.html', {
        'cart': cart,
        'cart_items': cart_items,
        'total_quantity': total_quantity,
        'cashback': cashback,
    })


@login_required
def add_to_cart(request, product_id):
    """Ajouter un produit au panier"""
    product = get_object_or_404(Product, id=product_id)

    if product.quantity <= 0:
        messages.error(request, 'Ce produit n\'est plus disponible.')
        return redirect('product_detail', product_id=product_id)

    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_item, item_created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': 1}
    )

    if not item_created:
        # Si l'item existe déjà, augmenter la quantité
        if cart_item.quantity >= product.quantity:
            messages.warning(request, f'Stock limité : seulement {product.quantity} unités disponibles.')
            cart_item.quantity = product.quantity
        else:
            cart_item.quantity += 1
        cart_item.save()

    messages.success(request, f'{product.name} ajouté au panier.')
    return redirect('cart')


@login_required
def remove_from_cart(request, item_id):
    """Supprimer un item du panier"""
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    product_name = cart_item.product.name
    cart_item.delete()

    messages.success(request, f'{product_name} retiré du panier.')
    return redirect('cart')


@login_required
def update_cart_item(request, item_id):
    """Mettre à jour la quantité d'un item dans le panier"""
    if request.method == 'POST':
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        quantity = int(request.POST.get('quantity', 1))

        if quantity <= 0:
            cart_item.delete()
            messages.success(request, f'{cart_item.product.name} retiré du panier.')
        elif quantity > cart_item.product.quantity:
            messages.warning(request, f'Stock limité : seulement {cart_item.product.quantity} unités disponibles.')
            cart_item.quantity = cart_item.product.quantity
            cart_item.save()
        else:
            cart_item.quantity = quantity
            cart_item.save()
            messages.success(request, f'Quantité mise à jour pour {cart_item.product.name}.')

    return redirect('cart')


@login_required
def clear_cart(request):
    """Vider complètement le panier"""
    cart = Cart.objects.filter(user=request.user).first()
    if cart:
        cart.items.all().delete()
        messages.success(request, 'Panier vidé.')
    return redirect('cart')


@login_required
def checkout(request):
    """Procéder au paiement du panier"""
    cart = Cart.objects.filter(user=request.user).first()
    if not cart or not cart.items.exists():
        messages.warning(request, 'Votre panier est vide.')
        return redirect('cart')

    # Vérifier le stock disponible
    for item in cart.items.all():
        if item.quantity > item.product.quantity:
            messages.error(request, f'Stock insuffisant pour {item.product.name}. Quantité disponible : {item.product.quantity}')
            return redirect('cart')

    # Calculer le total et les métriques de volume/poids
    total = cart.get_total_price()
    total_weight = sum((item.product.poids or Decimal('0')) * item.quantity for item in cart.items.select_related('product'))
    total_volume_liters = sum(
        ((item.product.largeur or Decimal('0')) * (item.product.hauteur or Decimal('0')) * (item.product.longueur or Decimal('0')) / Decimal('1000')) * item.quantity
        for item in cart.items.select_related('product')
    )
    estimated_distance = Decimal('5')

    estimated_calc = CommissionManager.calcul_commande(
        total,
        distance_km=estimated_distance,
        poids_kg=total_weight,
        volume_liters=total_volume_liters,
        quantite=cart.get_total_items(),
        category=None
    )
    total_with_delivery = estimated_calc['total_commande']

    # Vérifier le solde du wallet
    wallet = Wallet.objects.filter(user=request.user).first()

    payment_method_groups = [
        {
            'label': 'Haïti',
            'methods': [
                ('htg_wallet', 'HTG - MicroSDICash / MonCash / NatCash'),
                ('htg_moncash', 'HTG - MonCash'),
                ('htg_natcash', 'HTG - NatCash'),
                ('htg_cod', 'HTG - Cash à la livraison'),
                ('htg_transfer', 'HTG - Virement local HTG'),
            ]
        },
        {
            'label': 'République Dominicaine',
            'methods': [
                ('dop_tpag', 'DOP - tPago'),
                ('dop_local_transfer', 'DOP - Virement local DOP'),
            ]
        },
        {
            'label': 'Europe / EUR',
            'methods': [
                ('eur_card', 'EUR - Carte Visa/Mastercard'),
                ('eur_paypal', 'EUR - PayPal'),
            ]
        },
        {
            'label': 'International',
            'methods': [
                ('int_card', 'International - Carte Visa/Mastercard'),
                ('int_paypal', 'International - PayPal'),
            ]
        }
    ]

    if request.method == 'POST':
        delivery_address = request.POST.get('delivery_address')
        payment_method = request.POST.get('payment_method', 'htg_wallet')
        if not delivery_address:
            messages.error(request, 'Veuillez saisir une adresse de livraison.')
            return redirect('checkout')

        valid_methods = [method for group in payment_method_groups for method, label in group['methods']]
        if payment_method not in valid_methods:
            messages.error(request, 'Méthode de paiement non valide.')
            return redirect('checkout')

        use_wallet = payment_method == 'htg_wallet'
        if use_wallet and (not wallet or wallet.balance < total_with_delivery):
            messages.error(request, 'Solde insuffisant dans votre compte MicroSDICash USD pour payer avec MicroSDICash.')
            return redirect('checkout')

        payment_status = 'approved' if use_wallet else 'pending'
        order_status = 'awaiting_delivery' if payment_method in ['htg_wallet', 'htg_cod'] else 'pending'

        # Créer la commande
        order = Order.objects.create(
            buyer=request.user,
            total_amount=total_with_delivery,
            delivery_address=delivery_address,
            status=order_status,
            payment_method=payment_method,
            payment_status=payment_status,
            distance_km=estimated_distance,
            date_achat=timezone.now(),
            product_name=f'Panier ({cart.get_total_items()} article(s))'
        )

        # Créer les items de commande et mettre à jour le stock
        for cart_item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=cart_item.product,
                quantity=cart_item.quantity,
                price_ht=cart_item.product.price_ht
            )

            # Réduire le stock
            cart_item.product.quantity -= cart_item.quantity
            cart_item.product.save()

        if use_wallet:
            wallet.balance -= total_with_delivery
            wallet.save()
            tx_status = 'approved'
        else:
            tx_status = 'pending'

        # Créer la transaction
        Transaction.objects.create(
            sender=request.user,
            receiver=None,  # Paiement au système
            amount=total_with_delivery,
            type=f'payment_{payment_method}',
            status=tx_status
        )

        # Vider le panier
        cart.items.all().delete()

        # Assigner automatiquement un livreur (business logic)
        try:
            assignment = DeliveryAssignmentManager.assign_delivery_agent_to_order(order)
            if assignment:
                messages.success(request, f'✅ Commande #{order.id} créée et assignée au livreur {assignment.employee.user.get_full_name() or assignment.employee.identifier}!')
            else:
                messages.warning(request, f'⏳ Commande #{order.id} créée mais aucun livreur disponible pour le moment.')
        except Exception:
            messages.warning(request, f'Commande #{order.id} créée. Assignation livreur en cours.')

        # Créer une notification persistante pour l'acheteur
        PersistentNotification.objects.create(
            recipient=request.user,
            title=f"✅ Commande #{order.id} enregistrée",
            message=f"Votre commande #{order.id} a été enregistrée avec succès et est en cours de traitement. Montant total : {total_with_delivery} USD.",
            notification_type='order_created',
            sound_interval_minutes=1
        )

        # Créer un message privé du système/admin vers l'acheteur
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            conversation, _ = PrivateConversation.get_or_create(request.user, admin_user)
            PrivateMessage.objects.create(
                conversation=conversation,
                sender=admin_user,
                receiver=request.user,
                content=f"Votre commande #{order.id} a bien été enregistrée. Nous allons procéder à l'assignation d'un livreur et au suivi de la livraison.",
            )

        return redirect('order_confirm', order_id=order.id)

    return render(request, 'marketplace/checkout.html', {
        'cart': cart,
        'cart_items': cart.items.select_related('product__shop').all(),
        'product_total': total,
        'wallet': wallet,
        'estimated_calc': estimated_calc,
        'total_with_delivery': total_with_delivery,
        'estimated_distance': estimated_distance,
        'payment_method_groups': payment_method_groups,
    })


@login_required
def order_product(request, product_id):
    """Commander un produit directement (sans passer par le panier)"""
    product = get_object_or_404(Product, id=product_id)

    # Vérifier le stock
    if product.quantity <= 0:
        messages.error(request, f'Le produit "{product.name}" n\'est plus en stock.')
        return redirect('product_detail', product_id=product.id)

    # Calculer le total (prix HT)
    total = product.price_ht
    wallet = Wallet.objects.filter(user=request.user).first()

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            # Calculer la distance et les frais de livraison
            buyer_lat = form.cleaned_data.get('buyer_lat')
            buyer_lng = form.cleaned_data.get('buyer_lng')
            distance_km = Decimal('0')

            # Si GPS disponible, calculer distance réelle
            if buyer_lat and buyer_lng:
                distance_km = Decimal('5')  # km par défaut pour l'instant

            # Calculer les frais totaux avec commissions
            volume_liters = CommissionManager.calculate_volume_liters(product)
            commission_calc = CommissionManager.calcul_commande(
                product.price_ht,
                distance_km=distance_km,
                poids_kg=product.poids,
                volume_liters=volume_liters,
                category=product.category
            )
            total_with_delivery = commission_calc['total_commande']
            payment_method = form.cleaned_data.get('payment_method', 'htg_wallet')
            use_wallet = payment_method == 'htg_wallet'
            payment_status = 'approved' if use_wallet else 'pending'
            order_status = 'awaiting_delivery' if payment_method in ['htg_wallet', 'htg_cod'] else 'pending'

            if use_wallet and (not wallet or wallet.balance < total_with_delivery):
                messages.error(request, 'Solde insuffisant dans votre compte MicroSDICash USD pour payer avec MicroSDICash.')
                return redirect('product_detail', product_id=product.id)

            # Créer la commande avec GPS
            order = Order.objects.create(
                buyer=request.user,
                total_amount=total_with_delivery,
                delivery_address=form.cleaned_data.get('delivery_address'),
                buyer_lat=buyer_lat,
                buyer_lng=buyer_lng,
                buyer_address_details=form.cleaned_data.get('buyer_address_details'),
                status=order_status,
                payment_method=payment_method,
                payment_status=payment_status,
                date_achat=timezone.now(),
                distance_km=distance_km,
                product_name=product.name
            )

            # Créer l'item de commande
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=1,
                price_ht=product.price_ht
            )

            # Réduire le stock
            product.quantity -= 1
            product.save()

            if use_wallet:
                wallet.balance -= total_with_delivery
                wallet.save()
                tx_status = 'approved'
            else:
                tx_status = 'pending'

            # Créer la transaction
            Transaction.objects.create(
                sender=request.user,
                receiver=None,  # Paiement au système
                amount=total_with_delivery,
                type=f'payment_{payment_method}',
                status=tx_status
            )

            # Assigner automatiquement un livreur en round-robin
            try:
                assignment = DeliveryAssignmentManager.assign_delivery_roundrobin(order)
                if assignment:
                    messages.success(request, f'✅ Commande #{order.id} créée et assignée au livreur {assignment.employee.user.get_full_name() or assignment.employee.identifier}!')
                else:
                    messages.warning(request, f'⏳ Commande #{order.id} créée mais aucun livreur disponible pour le moment.')
            except Exception as e:
                messages.warning(request, f'Commande #{order.id} créée. Assignation livreur en cours.')

            return redirect('order_confirm', order_id=order.id)
        else:
            messages.error(request, 'Veuillez corriger les erreurs dans le formulaire.')
    else:
        form = OrderForm()

    # Calculer le total estimé pour l'affichage
    estimated_distance = Decimal('5')  # km par défaut pour estimation
    estimated_calc = CommissionManager.calcul_commande(
        product.price_ht,
        distance_km=estimated_distance,
        poids_kg=product.poids,
        volume_liters=CommissionManager.calculate_volume_liters(product),
        quantite=1,
        category=product.category
    )
    estimated_total = estimated_calc['total_commande']

    return render(request, 'marketplace/order_confirm.html', {
        'product': product,
        'form': form,
        'total': estimated_total,
        'estimated_calc': estimated_calc,
        'wallet': wallet,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    })


@login_required
def studio_beaute(request):
    beauty_products = Product.objects.filter(
        Q(category__slug__iexact='beaute') |
        Q(category__slug__iexact='studio-beaute') |
        Q(category__name__iexact='Studio de Beauté') |
        Q(category__name__iexact='Beauté')
    ).select_related('shop').prefetch_related('images')

    selected_service_id = request.GET.get('service_id')
    selected_service = beauty_products.filter(id=selected_service_id).first() if selected_service_id else None
    selected_service_name = None

    if not selected_service:
        selected_service_key = request.GET.get('service')
        if selected_service_key:
            selected_service = beauty_products.filter(name__icontains=selected_service_key).first()
            selected_service_name = selected_service_key.replace('-', ' ').title()

    booking_form = BeautyBookingForm(initial={
        'product': selected_service.id if selected_service else None,
        'booking_type': 'home',
    })
    message_form = PrivateMessageForm()
    user_appointments = BeautyAppointment.objects.filter(user=request.user).order_by('-scheduled_date', '-scheduled_time')[:10]
    admin_product_url = reverse('admin:marketplace_product_changelist') + '?category__slug__exact=beaute'

    approved_shop = Shop.objects.filter(owner=request.user).first()
    studio_owner_name = None
    if approved_shop:
        studio_owner_name = approved_shop.owner.get_full_name() or approved_shop.owner.username

    profile_phone = ''
    if hasattr(request.user, 'profile'):
        profile_phone = request.user.profile.phone

    approved_beauty_studios = BeautyStudioRequest.objects.filter(status='approved').select_related('approved_shop', 'user')

    studio_wallet = None
    recent_studio_transactions = []
    recent_studio_transfers = []
    recent_studio_withdrawals = []
    commission_summary = None
    service_form = None
    cover_photo_form = None
    studio_services = []
    cover_photos = []

    if approved_shop:
        studio_wallet, _ = Wallet.objects.get_or_create(
            user=request.user,
            defaults={
                'balance': Decimal('0.00'),
                'can_transfer': False,
                'is_blocked': False,
            }
        )
        commission_summary = {
            'USD': getattr(studio_wallet, 'commission_balance_usd', Decimal('0.00')),
            'HTG': getattr(studio_wallet, 'commission_balance_htg', Decimal('0.00')),
            'PESO': getattr(studio_wallet, 'commission_balance_peso', Decimal('0.00')),
            'EUR': getattr(studio_wallet, 'commission_balance_eur', Decimal('0.00')),
        }
        recent_studio_transactions = Transaction.objects.filter(
            receiver=request.user,
            type__in=['deposit', 'recharge', 'admin_add', 'payment']
        ).order_by('-created_at')[:10]
        recent_studio_transfers = Transfer.objects.filter(receiver=request.user).order_by('-created_at')[:10]
        recent_studio_withdrawals = Transaction.objects.filter(
            sender=request.user,
            type__startswith='withdrawal_'
        ).order_by('-created_at')[:10]

        cover_photos = list(approved_shop.get_cover_photos())

        if request.user == approved_shop.owner:
            studio_services = BeautyStudioService.objects.filter(shop=approved_shop).order_by('service_type', 'title')
            if request.method == 'POST' and 'cover_upload_submit' in request.POST:
                cover_photo_form = ShopCoverPhotoForm(request.POST, request.FILES)
                if cover_photo_form.is_valid():
                    images = request.FILES.getlist('images')
                    start_order = approved_shop.cover_photos.aggregate(Max('sort_order'))['sort_order__max'] or 0
                    for index, image in enumerate(images, start=1):
                        ShopCoverPhoto.objects.create(
                            shop=approved_shop,
                            image=image,
                            sort_order=start_order + index
                        )
                    messages.success(request, '✅ Photos de couverture ajoutées avec succès.')
                    return redirect('studio_beaute')
            elif request.method == 'POST' and 'service_submit' in request.POST:
                service_form = BeautyStudioServiceForm(request.POST, request.FILES)
                if service_form.is_valid():
                    service = service_form.save(commit=False)
                    service.shop = approved_shop
                    service.save()
                    messages.success(request, '✅ Service ajouté avec succès.')
                    return redirect('studio_beaute')
            else:
                service_form = BeautyStudioServiceForm()
                cover_photo_form = ShopCoverPhotoForm()

    if request.method == 'POST':
        if 'booking_submit' in request.POST:
            booking_form = BeautyBookingForm(request.POST)
            if booking_form.is_valid():
                appointment = booking_form.save(commit=False)
                appointment.user = request.user
                appointment.status = 'pending'
                appointment.save()
                messages.success(request, '✅ Votre réservation a été enregistrée. Un technicien vous contactera bientôt.')
                return redirect('studio_beaute')
        elif 'message_submit' in request.POST:
            message_form = PrivateMessageForm(request.POST, request.FILES)
            if message_form.is_valid():
                admin_user = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_staff=True).exclude(pk=request.user.pk).first()
                if admin_user:
                    conversation, _ = PrivateConversation.get_or_create(request.user, admin_user)
                    private_message = message_form.save(commit=False)
                    private_message.conversation = conversation
                    private_message.sender = request.user
                    private_message.receiver = admin_user
                    private_message.save()
                    messages.success(request, '✅ Votre message a été envoyé au support Beauté.')
                    return redirect('studio_beaute')
                messages.error(request, 'Aucun destinataire disponible pour votre message.')
            
    if not service_form:
        service_form = BeautyStudioServiceForm() if approved_shop and request.user == approved_shop.owner else None

    return render(request, 'marketplace/studio_beaute.html', {
        'beauty_products': beauty_products,
        'selected_service': selected_service,
        'selected_service_name': selected_service_name,
        'booking_form': booking_form,
        'message_form': message_form,
        'user_appointments': user_appointments,
        'admin_product_url': admin_product_url,
        'approved_shop': approved_shop,
        'studio_owner_name': studio_owner_name,
        'profile_phone': profile_phone,
        'studio_wallet': studio_wallet,
        'commission_summary': commission_summary,
        'recent_studio_transactions': recent_studio_transactions,
        'recent_studio_transfers': recent_studio_transfers,
        'recent_studio_withdrawals': recent_studio_withdrawals,
        'service_form': service_form,
        'cover_photo_form': cover_photo_form,
        'studio_services': studio_services,
        'cover_photos': cover_photos,
        'approved_beauty_studios': approved_beauty_studios,
    })


@login_required
def studio_beaute_request(request):
    """Formulaire pour demander la création d'un studio de beauté"""
    # Vérifier si l'utilisateur a déjà une demande ou un studio approuvé
    existing_request = BeautyStudioRequest.objects.filter(user=request.user).first()
    existing_shop = Shop.objects.filter(owner=request.user).first()
    
    if request.method == 'POST':
        form = BeautyStudioRequestForm(request.POST)
        if form.is_valid():
            if existing_request and existing_request.status == 'pending':
                messages.error(request, '❌ Vous avez déjà une demande en attente de validation.')
                return redirect('studio_beaute_request')
            
            # Créer ou mettre à jour la demande
            studio_request = form.save(commit=False)
            studio_request.user = request.user
            studio_request.status = 'pending'
            studio_request.save()
            
            messages.success(request, '✅ Votre demande de création de studio a été enregistrée. L\'administration examinera votre demande bientôt.')
            return redirect('studio_beaute')
    else:
        # Pré-remplir le formulaire s'il existe déjà une demande
        if existing_request:
            form = BeautyStudioRequestForm(instance=existing_request)
        else:
            form = BeautyStudioRequestForm()
    
    return render(request, 'marketplace/studio_beaute_request.html', {
        'form': form,
        'existing_request': existing_request,
        'has_approved_studio': existing_request and existing_request.status == 'approved' if existing_request else False,
        'approved_shop': existing_request.approved_shop if existing_request and existing_request.status == 'approved' else None,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser or u.has_perm('marketplace.manage_beauty_studio_requests'))
def studio_beaute_requests_admin(request):
    """Interface admin pour valider les demandes de studio"""
    requests_list = BeautyStudioRequest.objects.all().order_by('-created_at')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        request_id = request.POST.get('request_id')
        studio_request = get_object_or_404(BeautyStudioRequest, pk=request_id)
        
        if action == 'approve':
            if studio_request.approve(request.user):
                messages.success(request, f'✅ Studio de beauté pour {studio_request.user.username} a été approuvé.')
            else:
                messages.error(request, '❌ Impossible d\'approuver cette demande.')
        elif action == 'reject':
            studio_request.status = 'rejected'
            studio_request.save()
            messages.success(request, f'❌ Demande pour {studio_request.user.username} a été rejetée.')
        
        return redirect('studio_beaute_requests_admin')
    
    return render(request, 'marketplace/studio_beaute_requests_admin.html', {
        'requests': requests_list,
    })


def technician_profiles(request):
    query = request.GET.get('q', '').strip()
    profiles = TechnicianProfile.objects.filter(is_published=True).order_by('-created_at')

    if query:
        profiles = profiles.filter(
            Q(company_name__icontains=query) |
            Q(contact_name__icontains=query) |
            Q(description__icontains=query) |
            Q(services__icontains=query) |
            Q(city_region__icontains=query)
        )

    return render(request, 'marketplace/technician_profiles.html', {
        'profiles': profiles,
        'query': query,
    })


@login_required
def technician_profile_create(request):
    instance = getattr(request.user, 'technician_profile', None)
    form = TechnicianProfileForm(request.POST or None, request.FILES or None, instance=instance)

    if request.method == 'POST':
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.save()
            messages.success(request, '✅ Votre profil technicien a bien été enregistré. Il est maintenant visible sur la plateforme.')
            return redirect('technician_profile_detail', profile_slug=profile.slug)
        messages.error(request, 'Veuillez corriger les erreurs du formulaire.')

    return render(request, 'marketplace/technician_profile_create.html', {
        'form': form,
        'instance': instance,
    })


def technician_profile_detail(request, profile_slug):
    profile = get_object_or_404(TechnicianProfile, slug=profile_slug, is_published=True)
    return render(request, 'marketplace/technician_profile_detail.html', {
        'profile': profile,
    })


@login_required
def profile(request):
    # S'assurer que l'utilisateur a un wallet
    wallet, created = Wallet.objects.get_or_create(
        user=request.user,
        defaults={
            'balance': Decimal('100.00'),
            'can_transfer': True,
            'is_blocked': False
        }
    )
    
    # Pour les administrateurs et vendeurs, créer une boutique automatiquement si elle n'existe pas
    if request.user.is_staff or request.user.is_seller:
        shop, created = Shop.objects.get_or_create(
            owner=request.user,
            defaults={'name': f'Boutique {request.user.username}'}
        )
    else:
        shop = Shop.objects.filter(owner=request.user).first()
    
    transactions = (Transaction.objects.filter(sender=request.user) | Transaction.objects.filter(receiver=request.user)).order_by('-created_at')[:10]
    
    # Exclure les commandes dans l'historique (plus de 30 min après confirmation)
    all_orders = Order.objects.filter(buyer=request.user).order_by('-created_at')
    orders = [order for order in all_orders if not is_order_in_history(order)][:10]
    
    # Données pour l'acheteur
    buyer_purchases = []
    buyer_commissions = Transaction.objects.filter(receiver=request.user, type='cashback').order_by('-created_at')[:10]
    total_buyer_commissions = Transaction.objects.filter(receiver=request.user, type='cashback').aggregate(total=Sum('amount'))['total'] or 0
    
    # Récupérer les achats de l'acheteur
    buyer_order_items = OrderItem.objects.filter(order__buyer=request.user).select_related('product', 'order').order_by('-order__created_at')[:20]
    for item in buyer_order_items:
        buyer_purchases.append({
            'order_id': item.order.id,
            'product_name': item.product.name,
            'quantity': item.quantity,
            'price_per_unit': item.price_ht,
            'total_price': item.price_ht * item.quantity,
            'order_date': item.order.date_achat,
            'status': item.order.status,
        })
    
    # Données pour le vendeur
    seller_sales = []
    total_seller_sales = 0
    
    if request.user.is_seller or request.user.is_staff:
        # Récupérer les ventes du vendeur/admin
        seller_order_items = OrderItem.objects.filter(product__shop__owner=request.user).select_related('product', 'order').order_by('-order__created_at')[:20]
        for item in seller_order_items:
            sale_amount = item.price_ht * item.quantity
            total_seller_sales += sale_amount
            seller_sales.append({
                'product_name': item.product.name,
                'quantity': item.quantity,
                'price_per_unit': item.price_ht,
                'total_sale': sale_amount,
                'order_date': item.order.date_achat,
                'buyer': item.order.buyer.username,
                'status': item.order.status,
            })
    
    seller_orders = Order.objects.filter(items__product__shop__owner=request.user).distinct().order_by('-created_at')[:10] if request.user.is_seller or request.user.is_staff else None
    admin_orders = Order.objects.all().order_by('-created_at')[:10] if request.user.is_staff else None
    
    # Données pour l'administration des accès livreur
    admin_delivery_users = None
    if request.user.is_staff:
        admin_delivery_users = []
        all_users = User.objects.all().select_related('profile').order_by('username')
        for user in all_users:
            profile = Profile.objects.get_or_create(user=user)[0]
            admin_delivery_users.append({
                'user': user,
                'profile': profile,
                'can_become_delivery': user.can_request_delivery,
            })

    # Données pour la gestion des commissions (admin seulement)
    commission_configs = None
    category_commission_configs = None
    categories = None
    if request.user.is_staff:
        from .models import CommissionConfig
        CommissionManager.ensure_default_configs()
        commission_configs = CommissionConfig.objects.exclude(nom__startswith='taux_commission_categorie_').order_by('nom')
        category_commission_configs = CommissionConfig.objects.filter(nom__startswith='taux_commission_categorie_').order_by('nom')
        categories = Category.objects.filter(is_active=True).order_by('name')

    system_settings = SystemSettings.objects.get_or_create(pk=1)[0]
    CommissionManager.ensure_default_transfer_tiers()
    transfer_commission_tiers = TransferCommissionTier.objects.filter(active=True).order_by('currency', 'min_amount')

    profile = Profile.objects.get_or_create(user=request.user)[0]
    # Force refresh from database to ensure latest data
    profile.refresh_from_db()
    
    # Determine admin/agent financial access
    is_principal_admin = request.user.is_superuser or request.user.has_perm('marketplace.principal_admin_power')
    can_use_agent_financial_tools = request.user.is_agent or is_principal_admin or user_has_agent_fund_access(request.user)
    can_use_full_admin_actions = request.user.is_staff or is_principal_admin
    can_access_agent_codes = request.user.is_staff or is_principal_admin
    can_manage_withdrawal_commissions = request.user.is_superuser or request.user.has_perm('marketplace.manage_withdrawal_commissions')

    agent_fund_managers = []
    if is_principal_admin:
        group = get_agent_fund_managers_group()
        staff_users = User.objects.filter(is_staff=True).exclude(id=request.user.id).order_by('username')
        for staff_user in staff_users:
            agent_fund_managers.append({
                'user': staff_user,
                'has_access': staff_user.groups.filter(name='AgentFundManagers').exists()
            })

    # Get withdrawal codes from profile object
    withdrawal_pin = profile.withdrawal_pin
    withdrawal_code = profile.withdrawal_code

    # Initialiser les variables avant les conditions POST
    show_edit_form = False
    form = ProfileForm(instance=profile)  # Initialiser par défaut

    if request.method == 'POST':
        # Gestion des codes de retrait pour admin
        if 'update_withdrawal_codes' in request.POST and request.user.is_staff and (request.user.is_superuser or request.user.role in ['super_admin', 'admin_secondary']):
            new_pin = request.POST.get('new_withdrawal_pin', '').strip()
            new_code = request.POST.get('new_withdrawal_code', '').strip()
            
            if new_pin and (len(new_pin) != 8 or not new_pin.isdigit()):
                messages.error(request, 'Le PIN doit être exactement 8 chiffres.')
            elif new_code and (len(new_code) != 4 or not new_code.isdigit()):
                messages.error(request, 'Le code final doit être exactement 4 chiffres.')
            else:
                if new_pin:
                    profile.withdrawal_pin = new_pin
                if new_code:
                    profile.withdrawal_code = new_code
                profile.save()
                withdrawal_pin = profile.withdrawal_pin
                withdrawal_code = profile.withdrawal_code
                messages.success(request, 'Vos codes de retrait ont été mis à jour avec succès.')
            return redirect('profile')

        if 'save_commission_button_color' in request.POST:
            button_gradient = request.POST.get('commission_button_gradient', '').strip()
            settings_data = profile.theme_settings or {}
            if button_gradient:
                settings_data['commission_button_gradient'] = button_gradient
                messages.success(request, 'Couleur du bouton enregistrée avec succès.')
            else:
                settings_data.pop('commission_button_gradient', None)
                messages.success(request, 'La couleur du bouton a été réinitialisée.')
            profile.theme_settings = settings_data
            profile.save(update_fields=['theme_settings'])
            return redirect('profile')
        
        # Gestion des commissions
        if request.user.is_staff and 'update_commission' in request.POST:
            commission_id = request.POST.get('commission_id')
            new_value = request.POST.get('commission_value', '').strip()
            try:
                if not new_value:
                    messages.error(request, 'La valeur de commission ne peut pas être vide.')
                    return redirect('profile')
                commission = CommissionConfig.objects.get(id=commission_id)
                commission.valeur = Decimal(new_value)
                commission.save()
                messages.success(request, f'Commission "{commission.nom}" mise à jour avec succès.')
            except CommissionConfig.DoesNotExist:
                messages.error(request, 'Configuration de commission non trouvée.')
            except (ValueError, InvalidOperation):
                messages.error(request, 'Valeur de commission invalide. Veuillez entrer un nombre décimal valide.')
            return redirect('profile')

        if request.user.is_staff and 'update_category_commission' in request.POST:
            category_id = request.POST.get('category_id')
            new_value = request.POST.get('category_commission_value', '').strip()
            try:
                if not category_id or not new_value:
                    messages.error(request, 'Veuillez sélectionner une catégorie et entrer une valeur.')
                    return redirect('profile')
                category = Category.objects.filter(id=category_id, is_active=True).first()
                if not category:
                    messages.error(request, 'Catégorie invalide ou inactive.')
                    return redirect('profile')
                key = f'taux_commission_categorie_{category.slug}'
                commission, created = CommissionConfig.objects.get_or_create(
                    nom=key,
                    defaults={
                        'valeur': Decimal(new_value),
                        'type': 'pourcentage',
                        'description': f'Taux de commission pour la catégorie {category.name}',
                        'actif': True
                    }
                )
                if not created:
                    commission.valeur = Decimal(new_value)
                    commission.actif = True
                    commission.save()
                messages.success(request, f'Commission catégorie "{category.name}" mise à jour avec succès.')
            except (ValueError, InvalidOperation):
                messages.error(request, 'Valeur de commission invalide. Veuillez entrer un nombre décimal valide.')
            return redirect('profile')

        if request.user.is_staff and 'update_transfer_tiers' in request.POST:
            tier_ids = request.POST.getlist('tier_id')
            for tier_id in tier_ids:
                try:
                    tier = TransferCommissionTier.objects.get(id=int(tier_id))
                except (TransferCommissionTier.DoesNotExist, ValueError):
                    continue
                try:
                    currency = request.POST.get(f'currency_{tier_id}', tier.currency).strip().upper()
                    if currency not in ['USD', 'HTG', 'EUR', 'DOP']:
                        currency = tier.currency
                    tier.currency = currency
                    tier.description = request.POST.get(f'description_{tier_id}', '').strip() or tier.description
                    tier.min_amount = Decimal(request.POST.get(f'min_amount_{tier_id}', tier.min_amount))
                    tier.max_amount = Decimal(request.POST.get(f'max_amount_{tier_id}', tier.max_amount))
                    tier.total_fee = Decimal(request.POST.get(f'total_fee_{tier_id}', tier.total_fee))
                    tier.system_fee = Decimal(request.POST.get(f'system_fee_{tier_id}', tier.system_fee))
                    tier.agent_fee = Decimal(request.POST.get(f'agent_fee_{tier_id}', tier.agent_fee))
                    tier.active = request.POST.get(f'active_{tier_id}') == 'on'
                    tier.save()
                except (InvalidOperation, ValueError):
                    continue
            messages.success(request, 'Tranches de commission de transfert mises à jour avec succès.')
            return redirect('profile')

        if request.user.is_staff and 'create_transfer_tier' in request.POST:
            description = request.POST.get('new_description', '').strip()
            currency = request.POST.get('new_currency', 'HTG').strip().upper()
            if currency not in ['USD', 'HTG', 'EUR', 'DOP']:
                currency = 'HTG'
            min_amount = request.POST.get('new_min_amount', '').strip()
            max_amount = request.POST.get('new_max_amount', '').strip()
            total_fee = request.POST.get('new_total_fee', '').strip()
            system_fee = request.POST.get('new_system_fee', '').strip()
            agent_fee = request.POST.get('new_agent_fee', '').strip()
            active = request.POST.get('new_active') == 'on'
            try:
                TransferCommissionTier.objects.create(
                    currency=currency,
                    min_amount=Decimal(min_amount),
                    max_amount=Decimal(max_amount),
                    total_fee=Decimal(total_fee),
                    system_fee=Decimal(system_fee),
                    agent_fee=Decimal(agent_fee),
                    description=description,
                    active=active,
                )
                messages.success(request, 'Nouvelle tranche de commission de transfert ajoutée avec succès.')
            except (InvalidOperation, ValueError):
                messages.error(request, 'Données invalides pour la nouvelle tranche de commission.')
            return redirect('profile')

        if request.user.is_staff and 'security_action' in request.POST:
            security_action = request.POST.get('security_action')
            if security_action == 'toggle_lockdown':
                system_settings.emergency_lockdown = not system_settings.emergency_lockdown
                system_settings.enable_cybersecurity = True
                system_settings.save()
                state = 'activé' if system_settings.emergency_lockdown else 'désactivé'
                messages.success(request, f'Verrouillage d\'urgence {state} avec succès.')
                return redirect('profile')

            if security_action == 'toggle_cybersecurity':
                system_settings.enable_cybersecurity = not system_settings.enable_cybersecurity
                system_settings.save()
                state = 'activée' if system_settings.enable_cybersecurity else 'désactivée'
                messages.success(request, f'Surveillance cybersécurité {state} avec succès.')
                return redirect('profile')

            if security_action == 'create_security_alert':
                incident_type = request.POST.get('incident_type', 'other')
                severity = request.POST.get('severity', 'warning')
                description = request.POST.get('security_description', '').strip()
                source_ip = request.META.get('REMOTE_ADDR', '')
                SecurityIncident.objects.create(
                    incident_type=incident_type,
                    severity=severity,
                    description=description,
                    source_ip=source_ip
                )
                messages.success(request, 'Alerte de cybersécurité enregistrée. Le système peut envoyer une notification si activé.')
                return redirect('profile')

            if security_action == 'block_ip':
                ip_to_block = request.POST.get('ip_address', '').strip()
                if ip_to_block:
                    IPBlocklist.objects.update_or_create(
                        ip_address=ip_to_block,
                        defaults={'reason': 'Blocked from security dashboard'}
                    )
                    messages.success(request, f'IP {ip_to_block} bloquée avec succès.')
                else:
                    messages.error(request, 'Adresse IP invalide.')
                return redirect('profile')

            if security_action == 'unblock_ip':
                ip_to_unblock = request.POST.get('ip_address', '').strip()
                if ip_to_unblock:
                    blocked_record = IPBlocklist.objects.filter(ip_address=ip_to_unblock).first()
                    if blocked_record:
                        blocked_record.delete()
                        messages.success(request, f'IP {ip_to_unblock} débloquée avec succès.')
                    else:
                        messages.warning(request, f'Aucune IP bloquée trouvée pour {ip_to_unblock}.')
                else:
                    messages.error(request, 'Adresse IP invalide.')
                return redirect('profile')

            if security_action == 'resolve_incident':
                incident_id = request.POST.get('incident_id')
                if incident_id:
                    incident = SecurityIncident.objects.filter(id=incident_id, resolved=False).first()
                    if incident:
                        incident.resolved = True
                        incident.save(update_fields=['resolved'])
                        messages.success(request, 'Incident marqué comme résolu.')
                    else:
                        messages.warning(request, 'Cet incident est déjà résolu ou introuvable.')
                else:
                    messages.error(request, 'Incident invalide.')
                return redirect('profile')

        if request.user.is_staff and request.user.role in ['super_admin', 'admin_secondary'] and 'withdrawal_decision' in request.POST:
            withdrawal_id = request.POST.get('withdrawal_id')
            action = request.POST.get('action')
            
            # Vérifier si l'admin secondaire a la permission
            if request.user.role == 'admin_secondary':
                profile = Profile.objects.filter(user=request.user).first()
                if not (profile and profile.global_withdrawal_access_granted):
                    messages.error(request, "Vous n'avez pas la permission de confirmer les retraits.")
                    return redirect('profile')
            
            withdrawal = WithdrawalRequest.objects.filter(id=withdrawal_id, status='pending').first()
            if withdrawal:
                if action == 'approve':
                    # Approuver le retrait
                    withdrawal.status = 'approved'
                    withdrawal.confirmed_at = timezone.now()
                    withdrawal.confirmed_by = request.user
                    withdrawal.receipt_generated = True
                    withdrawal.save(update_fields=['status', 'confirmed_at', 'confirmed_by', 'receipt_generated'])
                    
                    # Générer le numéro de reçu
                    receipt_number = f"WR-{withdrawal.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                    
                    # Envoyer email avec reçu
                    try:
                        subject = f'Confirmation de retrait - {receipt_number}'
                        from_email = settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@sdistore.com'
                        recipient_list = [withdrawal.user.email] if withdrawal.user.email else []
                        
                        if recipient_list:
                            html_message = f'''
                            <html>
                                <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                                    <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px;">
                                        <h2 style="color: #28a745;">✅ Votre retrait a été confirmé</h2>
                                        <hr>
                                        <p>Bonjour {withdrawal.user.first_name or withdrawal.user.username},</p>
                                        <p>Votre demande de retrait a été approuvée par l\\'administration.</p>
                                        <h3 style="color: #333;">Détails du retrait</h3>
                                        <table style="width: 100%; border-collapse: collapse;">
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Numéro de reçu :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{receipt_number}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Montant :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{withdrawal.amount} {withdrawal.currency}</td>
                                            </tr>
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Type de compte :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{'Principal' if withdrawal.account_type == 'principal' else 'Multi-appareils'}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Date de confirmation :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{withdrawal.confirmed_at.strftime('%d/%m/%Y %H:%M')}</td>
                                            </tr>
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Confirmé par :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{request.user.username}</td>
                                            </tr>
                                        </table>
                                        <p style="margin-top: 20px; color: #666;">Vous pouvez télécharger ce reçu depuis votre profil.</p>
                                        <p style="color: #999; font-size: 12px; margin-top: 30px;">Cet email a été généré automatiquement. Merci d\\'utiliser nos services.</p>
                                    </div>
                                </body>
                            </html>
                            '''
                            send_mail(
                                subject,
                                f'Votre retrait de {withdrawal.amount} {withdrawal.currency} a été confirmé.',
                                from_email,
                                recipient_list,
                                html_message=html_message,
                                fail_silently=True
                            )
                            withdrawal.receipt_sent_to_email = True
                            withdrawal.save(update_fields=['receipt_sent_to_email'])
                    except Exception as e:
                        logger.error(f"Erreur lors de l\\'envoi du reçu: {str(e)}")
                    
                    messages.success(request, f'Retrait de {withdrawal.amount} {withdrawal.currency} approuvé. Reçu envoyé à {withdrawal.user.email}.')
                    logger.info(f"Retrait approuvé: {withdrawal.id} par {request.user.username}")
                    
                elif action == 'reject':
                    # Rejeter le retrait et rembourser
                    refund_wallet, _ = Wallet.objects.get_or_create(user=withdrawal.user)
                    if withdrawal.account_type == 'principal':
                        refund_wallet.balance += withdrawal.amount
                    else:
                        field_map = {
                            'USD': 'commission_balance_usd',
                            'HTG': 'commission_balance_htg',
                            'DOP': 'commission_balance_peso',
                            'EUR': 'commission_balance_eur',
                        }
                        field_name = field_map.get(withdrawal.currency.upper())
                        if field_name:
                            current_value = getattr(refund_wallet, field_name, Decimal('0'))
                            setattr(refund_wallet, field_name, current_value + withdrawal.amount)
                    refund_wallet.save()
                    
                    withdrawal.status = 'rejected'
                    withdrawal.rejection_reason = request.POST.get('rejection_reason', "Rejeté par l'administration")
                    withdrawal.confirmed_at = timezone.now()
                    withdrawal.confirmed_by = request.user
                    withdrawal.save(update_fields=['status', 'rejection_reason', 'confirmed_at', 'confirmed_by'])
                    
                    messages.error(request, f'Retrait de {withdrawal.amount} {withdrawal.currency} rejeté et remboursé.')
                    logger.info(f"Retrait rejeté: {withdrawal.id} par {request.user.username}")
                else:
                    messages.error(request, 'Action de retrait invalide.')
            else:
                messages.error(request, 'Retrait introuvable ou déjà traité.')
            return redirect('profile')

        if request.user.is_staff and 'access_request_decision' in request.POST:
            request_id = request.POST.get('request_id')
            action = request.POST.get('action')
            commission_value = request.POST.get('commission_value', '').strip()
            commission_type = request.POST.get('commission_type', 'percent')
            req = ProductAccessRequest.objects.filter(id=request_id, status='pending').first()
            if not req:
                messages.error(request, 'Demande introuvable ou déjà traitée.')
                return redirect('profile')

            settings = MarketplaceSettings.get_solo()
            if action == 'approve':
                active_product_copies = ResellerProduct.objects.filter(original_product=req.product, status='active').count()
                active_seller_copies = ResellerProduct.objects.filter(seller=req.seller, status='active').count()
                if active_product_copies >= settings.get_copy_limit() or active_seller_copies >= settings.get_max_active_copies_for_seller():
                    req.status = 'rejected'
                    req.save()
                    messages.error(request, 'Limite de copies atteinte pour ce produit. Demande rejetée.')
                    return redirect('profile')

                req.status = 'approved'
                req.commission_type = commission_type
                if commission_value:
                    try:
                        req.commission_value = Decimal(commission_value)
                    except Exception:
                        req.commission_value = None
                elif not req.commission_value:
                    seller_commission_type, seller_commission_value = settings.get_seller_commission(req.seller)
                    req.commission_type = seller_commission_type
                    req.commission_value = seller_commission_value
                req.save()

                rp, created = ResellerProduct.objects.get_or_create(
                    seller=req.seller,
                    original_product=req.product,
                    defaults={
                        'commission_type': req.commission_type,
                        'commission_value': req.commission_value,
                        'status': 'active'
                    }
                )
                if not rp.copied_product:
                    new_prod = req.product.create_copy_for_reseller(req.seller)
                    rp.copied_product = new_prod
                    rp.save()
                messages.success(request, 'Demande de produit approuvée et copie créée dans la boutique du vendeur.')
            elif action == 'reject':
                req.status = 'rejected'
                req.save()
                messages.success(request, 'Demande de produit rejetée.')
            else:
                messages.error(request, 'Action invalide pour la demande.')
            return redirect('profile')

        if request.user.is_superuser and 'grant_withdrawal_permission' in request.POST:
            target_user_id = request.POST.get('user_id')
            action = request.POST.get('action')
            target_user = User.objects.filter(id=target_user_id, role='admin_secondary').first()
            if target_user:
                perm, created = AdminWithdrawalPermission.objects.get_or_create(admin=target_user)
                if action == 'grant':
                    perm.can_confirm_withdrawals = True
                    perm.granted_by = request.user
                    perm.save(update_fields=['can_confirm_withdrawals', 'granted_by'])
                    messages.success(request, f'{target_user.username} peut maintenant confirmer les retraits.')
                elif action == 'revoke':
                    perm.can_confirm_withdrawals = False
                    perm.save(update_fields=['can_confirm_withdrawals'])
                    messages.success(request, f"{target_user.username} n'a plus la permission de confirmer les retraits.")
            else:
                messages.error(request, 'Utilisateur admin secondaire introuvable.')
            return redirect('profile')

        if request.user.is_superuser and 'grant_secondary_admin' in request.POST:
            target_user_id = request.POST.get('user_id')
            target_user = User.objects.filter(id=target_user_id).first()
            if target_user:
                if not target_user.is_staff:
                    target_user.is_staff = True
                    target_user.role = 'admin_secondary'
                    target_user.save(update_fields=['is_staff', 'role'])
                    messages.success(request, f'{target_user.username} est maintenant admin secondaire.')
                else:
                    messages.warning(request, f'{target_user.username} est déjà administrateur.')
            else:
                messages.error(request, 'Utilisateur introuvable.')
            return redirect('profile')

        if request.user.is_superuser and 'toggle_global_withdrawal_access' in request.POST:
            target_user_id = request.POST.get('user_id')
            action = request.POST.get('action')
            target_user = User.objects.filter(role='admin_secondary', id=target_user_id).first()
            if target_user:
                profile, created = Profile.objects.get_or_create(user=target_user)
                old_status = profile.global_withdrawal_access_granted
                if action == 'grant':
                    profile.global_withdrawal_access_granted = True
                    profile.save(update_fields=['global_withdrawal_access_granted'])
                    messages.success(request, f'{target_user.username} peut maintenant faire des retraits pour tous les utilisateurs.')
                    # Log d'audit
                    AuditLog.objects.create(
                        user=request.user,
                        action='global_withdrawal_access_granted',
                        details=f'Accès aux retraits globaux accordé à {target_user.username} (ID: {target_user.id})',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    # Notification par email
                    if target_user.email:
                        try:
                            subject = 'Accès aux retraits globaux accordé'
                            from_email = settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@sdistore.com'
                            html_message = f'''
                            <html>
                                <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                                    <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px;">
                                        <h2 style="color: #28a745;">✅ Accès accordé</h2>
                                        <hr>
                                        <p>Bonjour {target_user.first_name or target_user.username},</p>
                                        <p>L'administrateur principal vous a accordé l'accès aux retraits globaux.</p>
                                        <p>Vous pouvez maintenant approuver et rejeter les demandes de retrait de tous les utilisateurs de la plateforme.</p>
                                        <h3 style="color: #333;">Détails</h3>
                                        <table style="width: 100%; border-collapse: collapse;">
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Accès :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">Retraits globaux</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Accordé par :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{request.user.username}</td>
                                            </tr>
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Date :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{timezone.now().strftime('%d/%m/%Y %H:%M')}</td>
                                            </tr>
                                        </table>
                                        <p style="margin-top: 20px; color: #666;">Vous pouvez gérer les retraits depuis votre profil administrateur.</p>
                                        <p style="color: #999; font-size: 12px; margin-top: 30px;">Cet email a été généré automatiquement. Merci d'utiliser nos services.</p>
                                    </div>
                                </body>
                            </html>
                            '''
                            send_mail(
                                subject,
                                f'Vous avez maintenant accès aux retraits globaux sur SDI STORE.',
                                from_email,
                                [target_user.email],
                                html_message=html_message,
                                fail_silently=True
                            )
                        except Exception as e:
                            logger.error(f"Erreur lors de l'envoi de l'email d'accord d'accès: {str(e)}")
                elif action == 'revoke':
                    profile.global_withdrawal_access_granted = False
                    profile.save(update_fields=['global_withdrawal_access_granted'])
                    messages.success(request, f"{target_user.username} n'a plus l'accès aux retraits globaux.")
                    # Log d'audit
                    AuditLog.objects.create(
                        user=request.user,
                        action='global_withdrawal_access_revoked',
                        details=f'Accès aux retraits globaux révoqué pour {target_user.username} (ID: {target_user.id})',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    # Notification par email
                    if target_user.email:
                        try:
                            subject = 'Accès aux retraits globaux révoqué'
                            from_email = settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@sdistore.com'
                            html_message = f'''
                            <html>
                                <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                                    <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px;">
                                        <h2 style="color: #dc3545;">❌ Accès révoqué</h2>
                                        <hr>
                                        <p>Bonjour {target_user.first_name or target_user.username},</p>
                                        <p>L'administrateur principal a révoqué votre accès aux retraits globaux.</p>
                                        <p>Vous ne pouvez plus approuver ou rejeter les demandes de retrait des autres utilisateurs.</p>
                                        <h3 style="color: #333;">Détails</h3>
                                        <table style="width: 100%; border-collapse: collapse;">
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Accès révoqué :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">Retraits globaux</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Révoqué par :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{request.user.username}</td>
                                            </tr>
                                            <tr style="background-color: #f9f9f9;">
                                                <td style="padding: 10px; border: 1px solid #ddd;"><strong>Date :</strong></td>
                                                <td style="padding: 10px; border: 1px solid #ddd;">{timezone.now().strftime('%d/%m/%Y %H:%M')}</td>
                                            </tr>
                                        </table>
                                        <p style="margin-top: 20px; color: #666;">Si vous pensez que c'est une erreur, contactez l'administrateur principal.</p>
                                        <p style="color: #999; font-size: 12px; margin-top: 30px;">Cet email a été généré automatiquement. Merci d'utiliser nos services.</p>
                                    </div>
                                </body>
                            </html>
                            '''
                            send_mail(
                                subject,
                                f"Votre accès aux retraits globaux sur SDI STORE a été révoqué.",
                                from_email,
                                [target_user.email],
                                html_message=html_message,
                                fail_silently=True
                            )
                        except Exception as e:
                            logger.error(f"Erreur lors de l'envoi de l'email de révocation d'accès: {str(e)}")
            else:
                messages.error(request, 'Admin secondaire introuvable.')
            return redirect('profile')

        if is_principal_admin and 'toggle_agent_fund_manager' in request.POST:
            target_user_id = request.POST.get('user_id')
            action = request.POST.get('action')
            target_user = User.objects.filter(is_staff=True, id=target_user_id).first()
            if target_user:
                group = get_agent_fund_managers_group()
                if action == 'grant':
                    group.user_set.add(target_user)
                    messages.success(request, f'{target_user.username} peut maintenant gérer les fonds agent.')
                    AuditLog.objects.create(
                        user=request.user,
                        action='agent_fund_access_granted',
                        details=f'Accès aux fonds agent accordé à {target_user.username} (ID: {target_user.id})',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                elif action == 'revoke':
                    group.user_set.remove(target_user)
                    messages.success(request, f"{target_user.username} n'a plus l'accès aux fonds agent.")
                    AuditLog.objects.create(
                        user=request.user,
                        action='agent_fund_access_revoked',
                        details=f'Accès aux fonds agent révoqué pour {target_user.username} (ID: {target_user.id})',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                else:
                    messages.error(request, 'Action invalide pour la gestion des fonds agent.')
            else:
                messages.error(request, 'Utilisateur admin introuvable.')
            return redirect('profile')

        # Gestion du profil - mise à jour du formulaire de profil
        if 'profile_form_submit' in request.POST or (request.method == 'POST' and 'update_withdrawal_codes' not in request.POST and 'update_commission' not in request.POST and 'update_category_commission' not in request.POST and 'security_action' not in request.POST and 'withdrawal_decision' not in request.POST and 'grant_withdrawal_permission' not in request.POST and 'grant_secondary_admin' not in request.POST and 'toggle_global_withdrawal_access' not in request.POST and 'save_theme' not in request.POST and 'transfer_submit' not in request.POST):
            form = ProfileForm(request.POST, request.FILES, instance=profile)
            show_edit_form = True
            if form.is_valid():
                form.save()
                messages.success(request, 'Votre profil a été mis à jour avec succès.')
                return redirect('profile')
        elif request.method == 'POST' and 'transfer_submit' in request.POST:
            transfer_form = TransferForm(request.POST)
            if transfer_form.is_valid():
                recipient_code = transfer_form.cleaned_data['recipient_account_code'].upper()
                source_account = transfer_form.cleaned_data['source_account']
                currency = transfer_form.cleaned_data['currency']
                amount = transfer_form.cleaned_data['amount']
                recipient = User.objects.filter(account_code__iexact=recipient_code).first()
                if recipient and recipient != request.user:
                    with transaction.atomic():
                        sender_wallet = Wallet.objects.get_or_create(user=request.user)[0]
                        receiver_wallet = Wallet.objects.get_or_create(user=recipient)[0]
                        sender_field = 'balance' if source_account == 'principal' else get_wallet_balance_field(currency, source_account)
                        available_amount = getattr(sender_wallet, sender_field, Decimal('0'))

                        commission_breakdown = CommissionManager.get_transfer_commission_breakdown(amount, currency)
                        fee_total = commission_breakdown['total_fee']
                        system_fee = commission_breakdown['system_fee']
                        agent_fee = commission_breakdown['agent_fee']

                        if source_account == 'principal' and currency != 'USD':
                            total_deduction_usd = convert_currency(amount + fee_total, currency, 'USD')
                        else:
                            total_deduction_usd = amount + fee_total if currency == 'USD' else None

                        if source_account == 'principal':
                            if currency == 'USD':
                                if available_amount < amount + fee_total:
                                    messages.error(request, 'Solde principal insuffisant pour le montant et les frais.')
                                    return redirect('profile')
                            else:
                                if available_amount < total_deduction_usd:
                                    messages.error(request, 'Solde principal insuffisant pour le montant et les frais.')
                                    return redirect('profile')
                        else:
                            if available_amount < amount + fee_total:
                                messages.error(request, 'Solde Multi-appareils insuffisant pour le montant et les frais.')
                                return redirect('profile')

                        transfer = Transfer.objects.create(
                            sender=request.user,
                            receiver=recipient,
                            sender_account_type=source_account,
                            currency=currency,
                            amount=amount,
                            fee=fee_total,
                            system_fee=system_fee,
                            agent_fee=agent_fee,
                            status='success',
                        )

                        if source_account == 'principal':
                            if currency == 'USD':
                                sender_wallet.balance -= (amount + fee_total)
                                sender_wallet.save(update_fields=['balance'])
                                receiver_wallet.balance += amount
                                receiver_wallet.save(update_fields=['balance'])
                            else:
                                sender_wallet.balance -= total_deduction_usd
                                sender_wallet.save(update_fields=['balance'])
                                receiver_field = get_wallet_balance_field(currency)
                                receiver_amount = getattr(receiver_wallet, receiver_field, Decimal('0')) + amount
                                setattr(receiver_wallet, receiver_field, receiver_amount)
                                receiver_wallet.save(update_fields=[receiver_field])
                        else:
                            sender_amount = getattr(sender_wallet, sender_field, Decimal('0')) - (amount + fee_total)
                            setattr(sender_wallet, sender_field, sender_amount)
                            sender_wallet.save(update_fields=[sender_field])
                            receiver_field = get_wallet_balance_field(currency)
                            receiver_amount = getattr(receiver_wallet, receiver_field, Decimal('0')) + amount
                            setattr(receiver_wallet, receiver_field, receiver_amount)
                            receiver_wallet.save(update_fields=[receiver_field])

                        system_wallet = get_system_admin_wallet()
                        commission_field = get_commission_balance_field(currency)
                        if system_wallet and system_fee > 0:
                            current_system_commission = getattr(system_wallet, commission_field, Decimal('0'))
                            setattr(system_wallet, commission_field, current_system_commission + system_fee)
                            system_wallet.save(update_fields=[commission_field])

                        if agent_fee > 0:
                            if request.user.is_agent:
                                current_agent_commission = getattr(sender_wallet, get_commission_balance_field(currency), Decimal('0'))
                                setattr(sender_wallet, get_commission_balance_field(currency), current_agent_commission + agent_fee)
                                sender_wallet.save(update_fields=[get_commission_balance_field(currency)])
                            elif system_wallet:
                                current_system_commission = getattr(system_wallet, commission_field, Decimal('0'))
                                setattr(system_wallet, commission_field, current_system_commission + agent_fee)
                                system_wallet.save(update_fields=[commission_field])

                        Transaction.objects.create(
                            sender=request.user,
                            receiver=recipient,
                            amount=amount,
                            currency=currency,
                            type='transfer',
                            status='approved'
                        )
                        TransferLog.objects.create(
                            transfer=transfer,
                            action='Transfert effectué',
                            details=f"{request.user.username} a envoyé {amount} {currency} à {recipient.username} (frais {fee_total}, système {system_fee}, agent {agent_fee})",
                            actor=request.user,
                        )
                        TransferReceipt.objects.create(
                            transfer=transfer,
                            user=request.user,
                            role='sender',
                            receipt_number=f"RCPT-{transfer.transaction_id}-S",
                            notes=f"Reçu expéditeur pour le transfert {transfer.transaction_id} - Frais {fee_total} {currency}"
                        )
                        TransferReceipt.objects.create(
                            transfer=transfer,
                            user=recipient,
                            role='receiver',
                            receipt_number=f"RCPT-{transfer.transaction_id}-R",
                            notes=f"Reçu destinataire pour le transfert {transfer.transaction_id}"
                        )
                        if system_wallet and system_wallet.user != request.user:
                            TransferReceipt.objects.create(
                                transfer=transfer,
                                user=system_wallet.user,
                                role='admin',
                                receipt_number=f"RCPT-{transfer.transaction_id}-A",
                                notes=f"Reçu admin pour le transfert {transfer.transaction_id}"
                            )
                        if request.user.is_agent:
                            TransferReceipt.objects.create(
                                transfer=transfer,
                                user=request.user,
                                role='agent',
                                receipt_number=f"RCPT-{transfer.transaction_id}-AG",
                                notes=f"Commission agent pour le transfert {transfer.transaction_id}"
                            )

                        send_transfer_notification(
                            transfer,
                            request.user,
                            'Transfert envoyé',
                            f"Vous avez envoyé {amount} {currency} à {recipient.username}. Frais: {fee_total} {currency}"
                        )
                        send_transfer_notification(
                            transfer,
                            recipient,
                            'Transfert reçu',
                            f"Vous avez reçu {amount} {currency} de {request.user.username}."
                        )
                        if system_wallet and system_wallet.user != request.user:
                            send_transfer_notification(
                                transfer,
                                system_wallet.user,
                                'Nouveau transfert MicroSDICash',
                                f"Transfert {transfer.transaction_id}: {request.user.username} → {recipient.username} ({amount} {currency}, frais {fee_total} {currency})."
                            )
                        if request.user.is_agent:
                            send_transfer_notification(
                                transfer,
                                request.user,
                                'Transfert agent',
                                f"Vous avez reçu une commission agent de {agent_fee} {currency} pour le transfert {transfer.transaction_id}."
                            )
                        messages.success(request, f'Transfert de {amount} {currency} effectué avec succès.')
                        return redirect('profile')
                else:
                    messages.error(request, 'Compte destinataire invalide ou identique au vôtre.')
            else:
                messages.error(request, 'Veuillez corriger les erreurs du formulaire de transfert.')
        else:
            form = ProfileForm(instance=profile)
            show_edit_form = False
    else:
        form = ProfileForm(instance=profile)
        show_edit_form = False

    transfer_form = locals().get('transfer_form', TransferForm())

    # Liste des boutiques vendeurs pour affichage en mode carte
    vendor_shops = []
    all_shops = Shop.objects.select_related('owner').annotate(product_count=Count('product')).order_by('-product_count', 'name')
    for shop in all_shops:
        profile_owner = getattr(shop.owner, 'profile', None)
        vendor_shops.append({
            'id': shop.id,
            'name': shop.name,
            'owner_username': shop.owner.username,
            'owner_full_name': f"{shop.owner.first_name} {shop.owner.last_name}".strip(),
            'created_at': shop.created_at,
            'product_count': shop.product_count,
            'photo_url': profile_owner.photo.url if profile_owner and profile_owner.photo else None,
            'is_delivery_agent': shop.owner.is_delivery_agent,
            'is_seller': shop.owner.is_seller,
            'is_buyer': shop.owner.is_buyer,
        })
    featured_vendor = vendor_shops[0] if vendor_shops else None

    # Commandes en attente de confirmation pour l'acheteur
    pending_orders = []
    if request.user.is_buyer:
        pending_orders = Order.objects.filter(
            buyer=request.user,
            status='ready_for_buyer_confirmation',
            buyer_confirmed_delivery=False
        ).order_by('-date_achat')

    # Historique des retraits (ancien système + nouveau système)
    withdrawal_transactions = Transaction.objects.filter(sender=request.user, type__startswith='withdrawal_').order_by('-created_at')[:10]
    withdrawal_requests = WithdrawalRequest.objects.filter(user=request.user).order_by('-created_at')[:10]
    withdrawal_history = []
    
    # Ajouter les nouvelles demandes de retrait
    for withdrawal in withdrawal_requests:
        withdrawal_history.append({
            'id': withdrawal.id,
            'account_type': 'Principal' if withdrawal.account_type == 'principal' else 'Multi-appareils',
            'currency': withdrawal.currency.upper(),
            'amount': withdrawal.amount,
            'status': withdrawal.status,
            'created_at': withdrawal.created_at,
            'is_new_system': True,
        })
    
    # Ajouter les anciennes transactions de retrait
    for withdrawal_tx in withdrawal_transactions:
        parts = withdrawal_tx.type.split('_')
        account_type = parts[1] if len(parts) > 1 else 'unknown'
        currency = parts[2] if len(parts) > 2 else withdrawal_tx.currency
        withdrawal_history.append({
            'account_type': 'Principal' if account_type == 'principal' else 'Multi-appareils',
            'currency': currency.upper(),
            'amount': withdrawal_tx.amount,
            'status': withdrawal_tx.status,
            'created_at': withdrawal_tx.created_at,
            'is_new_system': False,
        })
    
    # Trier par date et limiter à 20
    withdrawal_history = sorted(withdrawal_history, key=lambda x: x['created_at'], reverse=True)[:20]

    pending_withdrawals = []
    admin_secondary_candidates = []
    if request.user.is_staff and request.user.role in ['super_admin', 'admin_secondary']:
        pending_transactions = Transaction.objects.filter(type__startswith='withdrawal_', status='pending').order_by('-created_at')[:20]
        for pending_tx in pending_transactions:
            if not pending_tx.sender:
                continue
            parts = pending_tx.type.split('_')
            account_type = parts[1] if len(parts) > 1 else 'unknown'
            currency = parts[2] if len(parts) > 2 else pending_tx.currency
            pending_withdrawals.append({
                'id': pending_tx.id,
                'username': pending_tx.sender.username,
                'account_type': 'Principal' if account_type == 'principal' else 'Multi-appareils',
                'currency': currency.upper(),
                'amount': pending_tx.amount,
                'created_at': pending_tx.created_at,
                'status': pending_tx.status,
            })
    
    # Données pour les retraits en attente
    pending_withdrawals = []
    if request.user.is_staff and request.user.role in ['super_admin', 'admin_secondary']:
        pending_trans = WithdrawalRequest.objects.filter(status='pending').order_by('-created_at')[:20]
        for withdrawal in pending_trans:
            pending_withdrawals.append({
                'id': withdrawal.id,
                'username': withdrawal.user.username,
                'account_type': 'Principal' if withdrawal.account_type == 'principal' else 'Multi-appareils',
                'currency': withdrawal.currency.upper(),
                'amount': withdrawal.amount,
                'created_at': withdrawal.created_at,
            })

    pending_product_access_requests = []
    if request.user.is_staff:
        pending_product_access_requests = ProductAccessRequest.objects.filter(status='pending').order_by('-created_at')[:20]

    if request.user.is_superuser:
        admin_secondary_candidates = User.objects.filter(is_staff=False).exclude(role='super_admin').order_by('username')[:20]
        # Ajouter les permissions d'admin secondaire pour affichage
        admin_perms = AdminWithdrawalPermission.objects.all().select_related('admin')

    security_incidents = []
    blocked_ips = []
    if request.user.is_staff:
        security_incidents = SecurityIncident.objects.order_by('-created_at')[:10]
        blocked_ips = IPBlocklist.objects.order_by('-ip_address')

    can_manage_beauty_studio_requests = request.user.is_superuser or request.user.role == 'super_admin' or request.user.has_perm('marketplace.manage_beauty_studio_requests')

    return render(request, 'marketplace/profile.html', {
        'wallet': wallet,
        'shop': shop,
        'transactions': transactions,
        'orders': orders,
        'seller_orders': seller_orders,
        'admin_orders': admin_orders,
        'buyer_purchases': buyer_purchases,
        'buyer_commissions': buyer_commissions,
        'total_buyer_commissions': total_buyer_commissions,
        'seller_sales': seller_sales,
        'total_seller_sales': total_seller_sales,
        'profile': profile,
        'withdrawal_pin': withdrawal_pin,
        'withdrawal_code': withdrawal_code,
        'admin_delivery_users': admin_delivery_users,
        'commission_configs': commission_configs,
        'vendor_shops': vendor_shops,
        'featured_vendor': featured_vendor,
        'form': form,
        'show_edit_form': show_edit_form,
        'transfer_form': transfer_form,
        'commission_configs': commission_configs,
        'category_commission_configs': category_commission_configs,
        'categories': categories,
        'transfer_commission_tiers': transfer_commission_tiers,
        'transfer_commission_tiers_json': json.dumps([
            {
                'currency': tier.currency,
                'min_amount': str(tier.min_amount),
                'max_amount': str(tier.max_amount),
                'total_fee': str(tier.total_fee),
                'system_fee': str(tier.system_fee),
                'agent_fee': str(tier.agent_fee)
            }
            for tier in transfer_commission_tiers
        ]),
        'can_manage_beauty_studio_requests': can_manage_beauty_studio_requests,
        'pending_orders': pending_orders,
        'withdrawal_history': withdrawal_history,
        'pending_withdrawals': pending_withdrawals,
        'pending_product_access_requests': pending_product_access_requests,
        'admin_secondary_candidates': admin_secondary_candidates,
        'system_settings': system_settings,
        'security_incidents': security_incidents,
        'blocked_ips': blocked_ips,
        'is_principal_admin': is_principal_admin,
        'can_use_agent_financial_tools': can_use_agent_financial_tools,
        'can_use_full_admin_actions': can_use_full_admin_actions,
        'agent_fund_managers': agent_fund_managers,
    })


def is_tikane_admin(user):
    return user.is_staff and (user.is_superuser or user.role in ['super_admin', 'ai_admin', 'admin_secondary'])


@login_required
def tikane_access(request):
    tikane_request = TiKaneAccessRequest.objects.filter(user=request.user).order_by('-requested_at').first()
    tikane_account = getattr(request.user, 'tikane_account', None)
    tikane_withdrawal_available = False
    form = None
    can_submit_request = True

    if tikane_account and tikane_account.can_withdraw:
        tikane_withdrawal_available = True

    if tikane_request and tikane_request.status == 'approved':
        can_submit_request = False
    if tikane_account and tikane_account.status == 'active':
        can_submit_request = False

    if request.method == 'POST':
        if not can_submit_request:
            messages.warning(request, 'Votre compte Ti Kanè est déjà actif. Aucune nouvelle demande n’est nécessaire.')
            return redirect('tikane_access')

        if tikane_request and tikane_request.status in ['pending', 'refused', 'suspended']:
            form = TiKaneAccessRequestForm(request.POST, request.FILES, instance=tikane_request)
        else:
            form = TiKaneAccessRequestForm(request.POST, request.FILES)

        if form.is_valid():
            tikane_request = form.save(commit=False)
            tikane_request.user = request.user
            tikane_request.status = 'pending'
            tikane_request.requested_at = tikane_request.requested_at or timezone.now()
            tikane_request.save()
            messages.success(request, 'Votre demande Ti Kanè Digital a bien été enregistrée. Un administrateur la traitera sous peu.')
            return redirect('tikane_access')
    else:
        if tikane_request and tikane_request.status in ['pending', 'refused', 'suspended']:
            form = TiKaneAccessRequestForm(instance=tikane_request)
        elif can_submit_request:
            initial = {
                'full_name': f"{request.user.first_name} {request.user.last_name}".strip(),
                'email': request.user.email,
                'phone': getattr(getattr(request.user, 'profile', None), 'phone', ''),
            }
            form = TiKaneAccessRequestForm(initial=initial)
        else:
            form = None

    available_plans = TiKanePlan.objects.filter(active=True).order_by('duration_days')

    daily_payments = tikane_account.get_daily_payment_statuses() if tikane_account and tikane_account.plan else []
    return render(request, 'marketplace/tikane_access.html', {
        'form': form,
        'tikane_request': tikane_request,
        'tikane_account': tikane_account,
        'tikane_withdrawal_available': tikane_withdrawal_available,
        'available_plans': available_plans,
        'can_submit_request': can_submit_request,
        'daily_payments': daily_payments,
    })


@login_required
def admin_tikane_requests(request):
    if not is_tikane_admin(request.user):
        messages.error(request, 'Accès refusé.')
        return redirect('profile')

    if request.method == 'POST':
        action = request.POST.get('action')
        request_id = request.POST.get('request_id')
        tikane_request = get_object_or_404(TiKaneAccessRequest, id=request_id)

        if action == 'approve_immediate':
            tikane_request.status = 'approved'
            tikane_request.reviewed_by = request.user
            tikane_request.reviewed_at = timezone.now()
            tikane_request.admin_notes = ''
            tikane_request.save()
            plan = tikane_request.plan or TiKanePlan.objects.filter(active=True).order_by('duration_days').first()
            account, created = TiKaneAccount.objects.get_or_create(
                user=tikane_request.user,
                defaults={
                    'request': tikane_request,
                    'plan': plan,
                    'status': 'active',
                    'is_sdi_managed': True,
                }
            )
            if not created:
                account.request = tikane_request
                account.status = 'active'
                account.plan = plan
                account.save(update_fields=['request', 'status', 'plan'])
            messages.success(request, f'La demande de {tikane_request.user.username} a été approuvée immédiatement.')
        elif action == 'approve_delayed':
            schedule_at = timezone.now() + timedelta(minutes=30)
            tikane_request.status = 'pending'
            tikane_request.reviewed_by = request.user
            tikane_request.reviewed_at = timezone.now()
            tikane_request.admin_notes = f'Approbation différée programmée pour {schedule_at.strftime("%d/%m/%Y %H:%M")}. '
            tikane_request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'admin_notes'])
            messages.success(request, f'Approbation différée prévue pour {schedule_at.strftime("%d/%m/%Y %H:%M")}.')
        elif action == 'refuse':
            tikane_request.status = 'refused'
            tikane_request.reviewed_by = request.user
            tikane_request.reviewed_at = timezone.now()
            tikane_request.save()
            messages.success(request, f'La demande de {tikane_request.user.username} a été refusée.')
        elif action == 'suspend':
            tikane_request.status = 'suspended'
            tikane_request.reviewed_by = request.user
            tikane_request.reviewed_at = timezone.now()
            tikane_request.save()
            account = getattr(tikane_request.user, 'tikane_account', None)
            if account:
                account.status = 'suspended'
                account.save(update_fields=['status'])
            messages.success(request, f'La demande de {tikane_request.user.username} a été suspendue.')
        elif action == 'reactivate':
            tikane_request.status = 'approved'
            tikane_request.reviewed_by = request.user
            tikane_request.reviewed_at = timezone.now()
            tikane_request.admin_notes = ''
            tikane_request.save()
            account, created = TiKaneAccount.objects.get_or_create(
                user=tikane_request.user,
                defaults={
                    'request': tikane_request,
                    'plan': tikane_request.plan,
                    'status': 'active',
                    'is_sdi_managed': True,
                }
            )
            if not created:
                account.request = tikane_request
                account.status = 'active'
                account.plan = tikane_request.plan
                account.save(update_fields=['request', 'status', 'plan'])
            messages.success(request, f'La demande de {tikane_request.user.username} a été réactivée.')

        return redirect('admin_tikane_requests')

    requests_list = TiKaneAccessRequest.objects.select_related('user', 'plan', 'reviewed_by').order_by('-requested_at')
    return render(request, 'marketplace/admin_tikane_requests.html', {
        'requests_list': requests_list,
    })


@login_required
def admin_tikane_plans(request):
    if not is_tikane_admin(request.user):
        messages.error(request, 'Accès refusé.')
        return redirect('profile')

    plan_id = request.GET.get('plan_id') or request.POST.get('plan_id')
    plan_instance = TiKanePlan.objects.filter(id=plan_id).first() if plan_id else None
    plan_action = request.POST.get('action') if request.method == 'POST' else None

    if request.method == 'POST' and plan_action == 'delete' and plan_instance:
        plan_instance.delete()
        messages.success(request, 'Le plan Ti Kanè a été supprimé avec succès.')
        return redirect('admin_tikane_plans')

    form = TiKanePlanForm(request.POST or None, instance=plan_instance)

    if request.method == 'POST' and plan_action != 'delete' and form.is_valid():
        form.save()
        messages.success(request, 'Le plan Ti Kanè a été enregistré avec succès.')
        return redirect('admin_tikane_plans')

    plans = TiKanePlan.objects.order_by('duration_days')
    return render(request, 'marketplace/admin_tikane_plans.html', {
        'plans': plans,
        'form': form,
        'editing_plan': plan_instance,
    })


@login_required
def agent_codes(request):
    is_principal_admin = request.user.is_superuser or request.user.has_perm('marketplace.principal_admin_power')
    if not request.user.is_staff and not is_principal_admin:
        messages.error(request, 'Accès refusé.')
        return redirect('profile')

    agents = User.objects.filter(is_agent=True).order_by('username')
    agent_data = []
    generated_codes = []

    if request.method == 'POST' and 'generate_codes' in request.POST:
        for agent in agents:
            otp = ''.join(secrets.choice('0123456789') for _ in range(6))
            agent.set_otp_code(otp)
            agent.otp_expires_at = timezone.now() + timedelta(days=7)
            agent.save(update_fields=['otp_expires_at'])
            agent_data.append({'agent': agent, 'otp_code': otp, 'generated': True})
            generated_codes.append({'agent': agent, 'otp_code': otp})
        messages.success(request, 'Les codes agents ont été régénérés. Copiez-les et transmettez-les aux agents.')
    else:
        for agent in agents:
            if not agent.otp_code:
                otp = ''.join(secrets.choice('0123456789') for _ in range(6))
                agent.set_otp_code(otp)
                agent.otp_expires_at = timezone.now() + timedelta(days=7)
                agent.save(update_fields=['otp_expires_at'])
                agent_data.append({'agent': agent, 'otp_code': otp, 'generated': True})
            else:
                agent_data.append({'agent': agent, 'otp_code': None, 'generated': False})

    return render(request, 'marketplace/agent_codes.html', {
        'agent_data': agent_data,
        'generated_codes': generated_codes,
        'agents_count': agents.count(),
    })


@login_required
@require_POST
def upload_receipt(request):
    """Endpoint pour téléverser un reçu MonCash"""
    from django.shortcuts import redirect

    if 'receipt_proof' not in request.FILES:
        messages.error(request, 'Aucun fichier sélectionné.')
        return redirect('profile')

    receipt_image = request.FILES['receipt_proof']

    allowed_content_types = ['image/jpeg', 'image/png', 'image/gif']
    max_upload_size = 5 * 1024 * 1024  # 5 MB

    if not receipt_image.content_type.startswith('image/'):
        messages.error(request, 'Le fichier doit être une image (JPG, PNG, GIF).')
        return redirect('profile')

    if receipt_image.size > max_upload_size:
        messages.error(request, 'Le fichier est trop volumineux. Taille maximale : 5 MB.')
        return redirect('profile')

    Receipt.objects.create(
        user=request.user,
        receipt_image=receipt_image
    )

    messages.success(request, 'Reçu MonCash téléversé avec succès. Il sera vérifié par un administrateur.')
    return redirect('profile')


@login_required
@require_POST
def upload_identity(request):
    """Endpoint pour téléverser une carte d'identité ou carte SDI"""
    profile = getattr(request.user, 'profile', None)
    if not profile:
        profile = Profile.objects.create(user=request.user)

    if 'identity_document' not in request.FILES:
        messages.error(request, 'Aucun fichier sélectionné.')
        return redirect('profile')

    identity_image = request.FILES['identity_document']
    max_upload_size = 5 * 1024 * 1024  # 5 MB

    if not identity_image.content_type.startswith('image/'):
        messages.error(request, 'Le fichier doit être une image (JPG, PNG, GIF).')
        return redirect('profile')

    if identity_image.size > max_upload_size:
        messages.error(request, 'Le fichier est trop volumineux. Taille maximale : 5 MB.')
        return redirect('profile')

    profile.identity_document = identity_image
    profile.save(update_fields=['identity_document'])

    messages.success(request, 'Document d’identité téléversé avec succès. Il sera vérifié par un administrateur.')
    return redirect('profile')


@login_required
@require_POST
def save_recharge_message(request):
    message = request.POST.get('recharge_message', '').strip()
    if not message:
        messages.error(request, 'Le message ne peut pas être vide.')
        return redirect('profile')

    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.recharge_message = message
    profile.save(update_fields=['recharge_message'])

    messages.success(request, 'Message de recharge enregistré avec succès.')
    return redirect('profile')


@login_required
@require_POST
def upload_selfie(request):
    selfie_data = request.POST.get('selfie_data', '')
    if not selfie_data:
        messages.error(request, 'Aucune image selfie fournie.')
        return redirect('profile')

    match = re.match(r'data:(image/[^;]+);base64,(.*)', selfie_data)
    if not match:
        messages.error(request, 'Format de selfie invalide.')
        return redirect('profile')

    content_type, base64_data = match.groups()
    try:
        decoded_file = base64.b64decode(base64_data.replace(' ', '+'))
    except (TypeError, ValueError):
        messages.error(request, 'Impossible de décoder le selfie.')
        return redirect('profile')

    extension = content_type.split('/')[-1]
    filename = f'{request.user.username}_recharge_selfie.{extension}'
    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.recharge_selfie.save(filename, ContentFile(decoded_file), save=True)

    messages.success(request, 'Selfie recharge téléversé avec succès.')
    return redirect('profile')


@login_required
@user_passes_test(lambda u: u.role in ['super_admin', 'admin_secondary'])
def view_receipts(request):
    """Vue pour que les administrateurs voient tous les reçus MonCash"""
    receipts = Receipt.objects.select_related('user').order_by('-uploaded_at')
    
    # Filtrage par statut si demandé
    status_filter = request.GET.get('status')
    if status_filter:
        receipts = receipts.filter(status=status_filter)
    
    context = {
        'receipts': receipts,
        'status_choices': Receipt.status_choices,
        'current_filter': status_filter,
    }
    
    return render(request, 'marketplace/admin_receipts.html', context)


@login_required
def transfer_receipts(request):
    """Liste des reçus de transfert accessibles à l'utilisateur ou aux administrateurs."""
    if request.user.is_staff:
        receipts = TransferReceipt.objects.select_related('transfer', 'user').order_by('-created_at')
    else:
        receipts = TransferReceipt.objects.filter(user=request.user).select_related('transfer', 'user').order_by('-created_at')

    return render(request, 'marketplace/transfer_receipts.html', {
        'receipts': receipts,
        'is_admin': request.user.is_staff,
    })


@login_required
def view_transfer_receipt(request, receipt_id):
    receipt = get_object_or_404(TransferReceipt, id=receipt_id)
    if receipt.user != request.user and not request.user.is_staff:
        messages.error(request, 'Accès non autorisé au reçu de transfert.')
        return redirect('transfer_receipts')

    return render(request, 'marketplace/transfer_receipt.html', {
        'receipt': receipt,
    })


@login_required
@user_passes_test(lambda u: u.role in ['super_admin', 'admin_secondary'])
@require_POST
def process_receipt(request, receipt_id):
    """Endpoint pour approuver ou rejeter un reçu"""
    receipt = get_object_or_404(Receipt, id=receipt_id)
    
    action = request.POST.get('action')
    notes = request.POST.get('notes', '')
    
    if action == 'approve':
        receipt.approve(request.user, notes)
        messages.success(request, f'Reçu de {receipt.user.username} approuvé.')
    elif action == 'reject':
        receipt.reject(request.user, notes)
        messages.error(request, f'Reçu de {receipt.user.username} rejeté.')
    else:
        messages.error(request, 'Action invalide.')
    
    return redirect('view_receipts')


@login_required
@require_POST
def withdraw_funds(request):
    """Endpoint pour retirer des fonds du portefeuille"""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from .models import WithdrawalRequest, WithdrawalTransaction
    from .business_logic import get_system_admin_wallet
    
    data = request.POST
    account_type = data.get('account') or data.get('account_type')
    amount_str = data.get('amount')
    currency = data.get('currency')
    pin = data.get('pin')
    secure_code = data.get('secure_code')
    
    # Validation des données
    if not all([account_type, amount_str, currency, pin, secure_code]):
        return JsonResponse({'success': False, 'message': 'Tous les champs sont requis.'})
    
    if account_type not in ['principal', 'multidevice', 'tikane']:
        return JsonResponse({'success': False, 'message': 'Type de compte invalide.'})
    
    if currency not in ['USD', 'HTG', 'DOP', 'EUR']:
        return JsonResponse({'success': False, 'message': 'Devise invalide.'})
    
    try:
        amount = Decimal(amount_str)
        if amount < Decimal('5.00'):  # Minimum 5 USD
            return JsonResponse({'success': False, 'message': 'Le montant minimum de retrait est de 5 USD.'})
    except (InvalidOperation, ValueError):
        return JsonResponse({'success': False, 'message': 'Montant invalide.'})
    
    user = request.user
    
    # Récupérer le profil pour vérifier les codes
    profile, created = Profile.objects.get_or_create(user=user)
    
    # Vérifier si bloqué
    if user.is_withdrawal_blocked():
        return JsonResponse({'success': False, 'message': 'Retrait temporairement bloqué en raison de tentatives échouées.'})
    
    # Vérifier les codes du profil
    if pin != profile.withdrawal_pin:
        user.increment_failed_attempts()
        logger.warning(f"Tentative de retrait échouée pour {user.username}: PIN incorrect")
        return JsonResponse({'success': False, 'message': 'Code PIN incorrect.'})
    
    if secure_code != profile.withdrawal_code:
        user.increment_failed_attempts()
        logger.warning(f"Tentative de retrait échouée pour {user.username}: Code final incorrect")
        return JsonResponse({'success': False, 'message': 'Code final incorrect.'})
    
    # Récupérer le portefeuille
    wallet, created = Wallet.objects.get_or_create(user=user)
    breakdown = CommissionManager.get_withdrawal_commission_breakdown(amount, currency)
    fee_total = breakdown['total_fee']
    fee_system = breakdown['system_fee']
    fee_agent = breakdown['agent_fee']
    
    # Vérifier le solde selon le type de compte
    if account_type == 'principal':
        if currency != 'USD':
            return JsonResponse({'success': False, 'message': 'Le compte principal ne supporte que USD.'})
        if wallet.balance < amount + fee_total:
            return JsonResponse({'success': False, 'message': 'Solde insuffisant.'})
        wallet.balance -= amount + fee_total
    elif account_type == 'multidevice':
        field_map = {
            'USD': 'commission_balance_usd',
            'HTG': 'commission_balance_htg',
            'DOP': 'commission_balance_peso',
            'EUR': 'commission_balance_eur',
        }
        field_name = field_map.get(currency.upper())
        if not field_name:
            return JsonResponse({'success': False, 'message': 'Devise non supportée pour multi-device.'})
        
        current_balance = getattr(wallet, field_name)
        if current_balance < amount + fee_total:
            return JsonResponse({'success': False, 'message': 'Solde insuffisant pour couvrir le montant du retrait et les frais.'})
        setattr(wallet, field_name, current_balance - amount - fee_total)
    elif account_type == 'tikane':
        tikane_account = getattr(user, 'tikane_account', None)
        if not tikane_account or tikane_account.status != 'active':
            return JsonResponse({'success': False, 'message': 'Vous devez avoir un compte Ti Kanè actif pour ce type de retrait.'})
        if not tikane_account.can_withdraw:
            return JsonResponse({'success': False, 'message': 'Retrait Ti Kanè indisponible avant la date d\'échéance du plan.'})

        plan_fee = tikane_account.get_plan_withdrawal_commission(amount)
        if plan_fee is not None:
            fee_total = plan_fee
            fee_system = plan_fee
            fee_agent = Decimal('0')
        else:
            breakdown = CommissionManager.get_withdrawal_commission_breakdown(amount, currency)
            fee_total = breakdown['total_fee']
            fee_system = breakdown['system_fee']
            fee_agent = breakdown['agent_fee']

        if currency == 'USD':
            if wallet.balance < amount + fee_total:
                return JsonResponse({'success': False, 'message': 'Solde insuffisant.'})
            wallet.balance -= amount + fee_total
        else:
            field_map = {
                'HTG': 'balance_htg',
                'DOP': 'balance_dop',
                'EUR': 'balance_eur',
            }
            field_name = field_map.get(currency.upper())
            if not field_name:
                return JsonResponse({'success': False, 'message': 'Devise non supportée pour Ti Kanè.'})
            current_balance = getattr(wallet, field_name)
            if current_balance < amount + fee_total:
                return JsonResponse({'success': False, 'message': 'Solde insuffisant pour couvrir le montant du retrait et les frais.'})
            setattr(wallet, field_name, current_balance - amount - fee_total)
        if tikane_account.balance < amount:
            return JsonResponse({'success': False, 'message': 'Solde Ti Kanè insuffisant pour ce retrait.'})
        tikane_account.balance -= amount
        tikane_account.total_withdrawals += amount
        tikane_account.save(update_fields=['balance', 'total_withdrawals'])
    
    # Débiter l'argent IMMÉDIATEMENT
    wallet.save()
    
    # Créer une WithdrawalRequest en pending
    withdrawal = WithdrawalRequest.objects.create(
        user=user,
        amount=amount,
        currency=currency,
        account_type=account_type,
        status='pending',
        amount_debited=True,
        fee_total=fee_total,
        fee_system=fee_system,
        fee_agent=fee_agent
    )

    if fee_system > Decimal('0'):
        admin_wallet = get_system_admin_wallet()
        if admin_wallet:
            admin_field_map = {
                'USD': 'commission_balance_usd',
                'HTG': 'commission_balance_htg',
                'DOP': 'commission_balance_peso',
                'EUR': 'commission_balance_eur',
            }
            admin_field_name = admin_field_map.get(currency.upper())
            if admin_field_name:
                current_admin_balance = getattr(admin_wallet, admin_field_name)
                setattr(admin_wallet, admin_field_name, current_admin_balance + fee_system)
                admin_wallet.save(update_fields=[admin_field_name])
            try:
                from .models import Transaction
                Transaction.objects.create(
                    sender=user,
                    receiver=admin_wallet.user,
                    amount=fee_system,
                    currency=currency,
                    type='withdrawal_system_commission',
                    status='approved'
                )
            except Exception as exc:
                logger.warning(f"Impossible d'enregistrer la commission de retrait: {exc}")

    WithdrawalTransaction.objects.create(
        withdrawal_request=withdrawal,
        user=user,
        amount=amount,
        currency=currency,
        account_type=account_type,
        fee_total=fee_total,
        fee_system=fee_system,
        fee_agent=fee_agent,
        status='pending'
    )
    
    # Remettre à zéro les tentatives échouées
    user.reset_failed_attempts()
    
    # Loguer la transaction
    logger.info(f"Retrait créé: {user.username} - {amount} {currency} depuis {account_type} - Withdrawal ID: {withdrawal.id}")
    
    response_message = f"Retrait de {amount} {currency} effectué et débité de votre compte. Veuillez attendre la confirmation de l'administration."
    if account_type == 'multidevice' and currency == 'HTG' and fee_total > Decimal('0'):
        response_message = f"Retrait de {amount} {currency} effectué. Frais de retrait appliqués: {fee_total} HTG. Veuillez attendre la confirmation de l'administration."

    return JsonResponse({
        'success': True,
        'message': response_message,
        'withdrawal_id': withdrawal.id
    })


@login_required
@user_passes_test(lambda u: u.is_staff)
def manage_delivery_access(request, user_id, action):
    """Vue pour accorder ou révoquer l'accès livreur à un utilisateur"""
    target_user = get_object_or_404(User, id=user_id)
    profile = Profile.objects.get_or_create(user=target_user)[0]
    
    if action == 'grant':
        profile.delivery_access_granted = True
        profile.delivery_access_requested = False  # Reset request
        target_user.is_delivery_agent = True  # Activer le rôle livreur
        target_user.save()
        messages.success(request, f'Accès livreur accordé à {target_user.username}')
    elif action == 'revoke':
        profile.delivery_access_granted = False
        target_user.is_delivery_agent = False  # Désactiver le rôle livreur
        target_user.save()
        messages.success(request, f'Accès livreur révoqué pour {target_user.username}')
    else:
        messages.error(request, 'Action non valide')
        return redirect('profile')
    
    profile.save()
    return redirect('profile')


@login_required
def order_history(request):
    """Vue pour afficher l'historique des commandes terminées (plus de 30 min après confirmation)"""
    all_orders = Order.objects.filter(buyer=request.user).order_by('-created_at')
    history_orders = [order for order in all_orders if is_order_in_history(order)]
    
    assignments = DeliveryAssignment.objects.filter(order__in=history_orders).select_related('employee__user', 'order')
    assignment_map = {assignment.order_id: assignment for assignment in assignments}
    for order in history_orders:
        order.assignment = assignment_map.get(order.id)

    return render(request, 'marketplace/order_history.html', {
        'history_orders': history_orders,
    })


@login_required
def delivery_tracking(request, order_id=None):
    """Vue pour suivre les livraisons en cours"""
    from django.conf import settings
    from django.db.models import Q
    
    if order_id:
        # Suivi d'une commande spécifique
        # Récupérer la commande
        order = get_object_or_404(Order, id=order_id)
        
        # Vérifier les permissions : acheteur, livreur assigné, ou administrateur
        is_buyer = order.buyer == request.user
        is_admin = request.user.is_staff or request.user.role in ['super_admin', 'admin_secondary']
        
        # Vérifier si l'utilisateur est le livreur assigné
        is_assigned_driver = False
        try:
            # Prendre la plus récente assignation
            assignment = DeliveryAssignment.objects.filter(order=order).order_by('-assigned_at').first()
            if assignment:
                is_assigned_driver = assignment.employee.user == request.user
        except DeliveryAssignment.DoesNotExist:
            assignment = None
        
        # Autoriser l'accès si c'est l'acheteur, l'admin ou le livreur assigné
        if not (is_buyer or is_admin or is_assigned_driver):
            messages.error(request, 'Vous n\'avez pas accès à cette livraison.')
            return redirect('home')
        
        if not assignment:
            messages.warning(request, 'Aucune livraison assignée pour cette commande.')
            return redirect('order_history')
        
        try:
            tracking_data = DeliveryTracking.objects.filter(assignment=assignment).order_by('-timestamp')[:10]
            notifications = DeliveryNotification.objects.filter(
                assignment=assignment,
                recipient=request.user
            ).order_by('-created_at')[:5]
            
            latest_tracking = tracking_data.first() if tracking_data else None
            
            return render(request, 'marketplace/delivery_tracking.html', {
                'order': order,
                'assignment': assignment,
                'tracking_data': tracking_data,
                'notifications': notifications,
                'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
                'seller_lat': assignment.seller_lat,
                'seller_lng': assignment.seller_lng,
                'buyer_lat': assignment.buyer_lat,
                'buyer_lng': assignment.buyer_lng,
                'driver_lat': assignment.driver_lat,
                'driver_lng': assignment.driver_lng,
            })
        except DeliveryAssignment.DoesNotExist:
            messages.warning(request, 'Aucune livraison assignée pour cette commande.')
            return redirect('order_history')
    else:
        # Liste des livraisons en cours
        active_orders = Order.objects.filter(
            buyer=request.user
        ).exclude(
            status__in=['delivered']
        ).order_by('-created_at')
        
        deliveries = []
        for order in active_orders:
            try:
                assignment = DeliveryAssignment.objects.get(order=order)
                deliveries.append({
                    'order': order,
                    'assignment': assignment,
                    'latest_tracking': DeliveryTracking.objects.filter(
                        assignment=assignment
                    ).order_by('-timestamp').first()
                })
            except DeliveryAssignment.DoesNotExist:
                deliveries.append({
                    'order': order,
                    'assignment': None,
                    'latest_tracking': None
                })
        
        return render(request, 'marketplace/delivery_tracking.html', {
            'deliveries': deliveries,
            'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        })


@login_required
def driver_dashboard(request):
    """Tableau de bord du livreur avec carte GPS et contrôles de livraison"""
    if not request.user.is_delivery_employee:
        messages.error(request, 'Accès réservé aux livreurs.')
        return redirect('home')

    try:
        driver = DeliveryEmployee.objects.get(user=request.user)
    except DeliveryEmployee.DoesNotExist:
        messages.error(request, 'Profil livreur non trouvé.')
        return redirect('home')

    # Traiter le formulaire de localisation
    if request.method == 'POST':
        form = DeliveryLocationForm(request.POST)
        if form.is_valid():
            # Mettre à jour la position du livreur dans toutes ses livraisons actives
            active_deliveries = DeliveryAssignment.objects.filter(
                employee=driver,
                status__in=['assigned', 'picked_up', 'in_transit']
            )

            for delivery in active_deliveries:
                delivery.driver_lat = form.cleaned_data.get('driver_lat')
                delivery.driver_lng = form.cleaned_data.get('driver_lng')
                delivery.driver_address_details = form.cleaned_data.get('driver_address_details')
                delivery.save()

                # Créer une entrée de tracking
                DeliveryTracking.objects.create(
                    assignment=delivery,
                    latitude=delivery.driver_lat,
                    longitude=delivery.driver_lng,
                    location_name=delivery.driver_address_details or 'Position livreur',
                    status_update=f'Position mise à jour: {delivery.driver_address_details or "Position actuelle"}'
                )

            messages.success(request, 'Votre position a été mise à jour avec succès.')
            return redirect('driver_dashboard')
        else:
            messages.error(request, 'Erreur lors de la mise à jour de votre position.')
    else:
        form = DeliveryLocationForm()

    # Récupérer les livraisons actives
    active_deliveries = DeliveryAssignment.objects.filter(
        employee=driver,
        status__in=['assigned', 'picked_up', 'in_transit']
    ).select_related('order', 'order__buyer').order_by('assigned_at')

    # Récupérer l'historique récent
    recent_deliveries = DeliveryAssignment.objects.filter(
        employee=driver,
        status__in=['delivered', 'failed']
    ).select_related('order', 'order__buyer').order_by('-delivered_at')[:10]

    context = {
        'driver': driver,
        'active_deliveries': active_deliveries,
        'recent_deliveries': recent_deliveries,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        'form': form,
    }

    return render(request, 'marketplace/driver_dashboard.html', context)


@login_required
def delivery_dashboard(request):
    """Tableau de bord du système de livraison"""
    if not request.user.is_staff and not request.user.is_delivery_employee:
        messages.error(request, 'Accès non autorisé.')
        return redirect('home')

    # Statistiques générales
    from marketplace.business_logic import StatisticsManager
    stats = StatisticsManager.get_platform_stats()

    context = {
        'total_orders': stats.get('total_orders', 0),
        'active_deliveries': stats.get('active_deliveries', 0),
        'total_deliveries': stats.get('total_deliveries', 0),
        'success_rate': stats.get('success_rate', 0),
    }

    return render(request, 'marketplace/delivery_dashboard.html', context)


@login_required
def return_request(request, order_id):
    """Vue pour faire une demande de retour"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    
    # Vérifier que la commande est livrée et qu'aucune demande de retour n'existe
    if order.status != 'delivered':
        messages.error(request, 'Vous ne pouvez faire une demande de retour que pour une commande livrée.')
        return redirect('order_history')
    
    if ReturnRequest.objects.filter(order=order).exists():
        messages.warning(request, 'Une demande de retour existe déjà pour cette commande.')
        return redirect('order_history')
    
    if request.method == 'POST':
        reason = request.POST.get('reason')
        description = request.POST.get('description')
        
        if not reason or not description:
            messages.error(request, 'Veuillez remplir tous les champs.')
            return redirect('return_request', order_id=order_id)
        
        ReturnRequest.objects.create(
            order=order,
            customer=request.user,
            reason=reason,
            description=description
        )
        
        messages.success(request, 'Votre demande de retour a été soumise avec succès.')
        return redirect('order_history')
    
    return render(request, 'marketplace/return_request.html', {
        'order': order,
    })


def system_view(request):
    """Vue des paramètres système pour contrôler le site."""
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        messages.error(request, "Accès refusé. Seuls les superutilisateurs peuvent accéder à cette page.")
        return redirect('home')
    
    settings, created = SystemSettings.objects.get_or_create(pk=1)  # Singleton
    
    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Paramètres système mis à jour avec succès.')
            return redirect('system_view')
    else:
        form = SystemSettingsForm(instance=settings)
    
    return render(request, 'marketplace/system_view.html', {
        'form': form,
    })


@login_required
@require_POST
def site_banner_activation_toggle(request):
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        return HttpResponseForbidden('Accès réservé à l’administrateur principal')

    settings_obj, _ = SystemSettings.objects.get_or_create(pk=1)
    settings_obj.banner_enabled = not settings_obj.banner_enabled
    settings_obj.save(update_fields=['banner_enabled'])
    messages.success(
        request,
        'Bannière activée.' if settings_obj.banner_enabled else 'Bannière désactivée pour tout le site.',
    )
    return redirect('site_banner_activation')


@login_required
def site_banner_activation(request):
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        return HttpResponseForbidden('Accès réservé à l’administrateur principal')

    settings_obj, _ = SystemSettings.objects.get_or_create(pk=1)
    return render(request, 'marketplace/site_banner_activation.html', {
        'banner_enabled': settings_obj.banner_enabled,
    })


@login_required
def site_banner_expand_settings(request):
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        return HttpResponseForbidden('Accès réservé à l’administrateur principal')

    settings_obj, _ = SystemSettings.objects.get_or_create(pk=1)
    if request.method == 'POST':
        form = BannerExpandSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Configuration ⭐ AGR enregistrée.')
            return redirect('site_banner_expand_settings')
    else:
        form = BannerExpandSettingsForm(instance=settings_obj)
    return render(request, 'marketplace/site_banner_expand_settings.html', {'form': form})


@login_required
def _site_dashboard_common(request, redirect_name):
    is_principal = request.user.is_superuser or request.user.role == 'super_admin'
    is_gp_dashboard = redirect_name == 'site_gp_dashboard'
    if not (is_principal or SiteBannerPermission.objects.filter(user=request.user, can_manage=True).exists()):
        messages.error(request, 'Accès refusé. Vous devez être administrateur.')
        return redirect('dashboard')

    edit_id = request.GET.get('edit')
    instance = SiteBanner.objects.filter(id=edit_id).first() if edit_id else None
    if request.method == 'POST':
        if request.POST.get('group_action'):
            if not is_principal:
                return HttpResponseForbidden('Accès réservé à l’administrateur principal')
            group_id = request.POST.get('group_id')
            group = PriorityGroup.objects.filter(pk=group_id).first() if group_id else None
            if request.POST.get('group_action') == 'delete' and group:
                group.delete()
                messages.success(request, 'Groupe de priorité supprimé.')
            else:
                group_form = PriorityGroupForm(request.POST, instance=group)
                if group_form.is_valid():
                    group_form.save()
                    messages.success(request, 'Groupe de priorité enregistré.')
                else:
                    messages.error(request, 'Les paramètres du groupe sont invalides.')
            return redirect(redirect_name)
        if request.POST.get('product_priority_action'):
            if not is_principal:
                return HttpResponseForbidden('Accès réservé à l’administrateur principal')
            product = get_object_or_404(Product, pk=request.POST.get('product_id'))
            product_form = BannerProductPriorityForm(request.POST, instance=product)
            if product_form.is_valid():
                product_form.save()
                messages.success(request, 'Priorité de la carte enregistrée.')
            else:
                messages.error(request, 'Les paramètres de la carte sont invalides.')
            return redirect(redirect_name)
        if is_gp_dashboard:
            return redirect(redirect_name)
        instance = SiteBanner.objects.filter(id=request.POST.get('banner_id')).first() if request.POST.get('banner_id') else None
        previous_scope = instance.scope if instance else None
        form = SiteBannerForm(request.POST, request.FILES, instance=instance, is_principal=is_principal)
        if form.is_valid():
            previous_access_mode = instance.access_mode if instance else None
            banner = form.save()
            generate_banner_variants(banner.image)
            event_type = 'created' if not instance else ('image_replaced' if request.FILES.get('image') else 'updated')
            SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type=event_type)
            if instance and previous_scope != banner.scope:
                SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='scope_changed', details={'from': previous_scope, 'to': banner.scope})
            if instance and previous_access_mode != banner.access_mode:
                SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='access_mode_changed', details={'from': previous_access_mode, 'to': banner.access_mode})
            messages.success(request, 'Bannière enregistrée avec succès.')
            return redirect(redirect_name)
    else:
        form = SiteBannerForm(instance=instance, is_principal=is_principal)

    banners = SiteBanner.objects.select_related('product', 'product__shop').prefetch_related('images', 'shops', 'permissions', 'access_grants').order_by('display_order', '-created_at')
    users = User.objects.filter(is_active=True).order_by('username') if is_principal else []
    stats = {banner.id: {
        'impressions': banner.events.filter(event_type='impression').count(),
        'clicks': banner.events.filter(event_type='click').count(),
    } for banner in banners}
    for item in stats.values():
        item['ctr'] = round((item['clicks'] / item['impressions']) * 100, 2) if item['impressions'] else 0
    for banner in banners:
        banner.audit_stats = stats[banner.id]
    history = SiteBannerEvent.objects.select_related('user', 'banner').order_by('-created_at')[:50] if is_principal else []
    products = Product.objects.select_related('shop').order_by('-created_at')
    priority_groups = PriorityGroup.objects.all()
    autoplay_banner = SiteBanner.get_active_banners().first()
    template_name = 'marketplace/site_gp_dashboard.html' if is_gp_dashboard else 'marketplace/site_banner_dashboard.html'
    return render(request, template_name, {
        'banners': banners,
        'form': form,
        'editing_banner': instance,
        'banner_users': users,
        'is_principal_admin': is_principal,
        'banner_stats': stats,
        'banner_history': history,
        'banner_products': products,
        'autoplay_banner': autoplay_banner,
        'autoplay_enabled': bool(autoplay_banner and autoplay_banner.autoplay_enabled),
        'priority_groups': priority_groups,
        'priority_group_form': PriorityGroupForm(),
        'banner_only': not is_gp_dashboard,
    })


@login_required
def site_banner_dashboard(request):
    return _site_dashboard_common(request, redirect_name='site_banner_dashboard')


@login_required
def site_gp_dashboard(request):
    return _site_dashboard_common(request, redirect_name='site_gp_dashboard')


@login_required
def site_banner_autoplay_toggle(request, banner_id):
    if request.method != 'POST':
        return redirect('site_banner_dashboard')
    banner = get_object_or_404(SiteBanner, pk=banner_id)
    if not _can_manage_site_banner(request.user, banner):
        return HttpResponseForbidden('Accès refusé.')
    banner.autoplay_enabled = not banner.autoplay_enabled
    banner.save(update_fields=['autoplay_enabled', 'updated_at'])
    messages.success(request, 'Défilement automatique mis à jour.')
    return redirect('site_banner_dashboard')


@login_required
def site_banner_product_toggle(request, product_id):
    banner = SiteBanner.get_active_banners().first()
    if request.method != 'POST' or not banner or not _can_manage_site_banner(request.user, banner):
        return redirect('site_banner_dashboard')
    product = get_object_or_404(Product, pk=product_id)
    product.banner_display_allowed = not product.banner_display_allowed
    if product.banner_display_allowed:
        product.banner_blocked_by_admin = None
        product.banner_blocked_at = None
        product.banner_block_reason = ''
    else:
        product.banner_blocked_by_admin = request.user
        product.banner_blocked_at = timezone.now()
    product.save(update_fields=[
        'banner_display_allowed', 'banner_blocked_by_admin',
        'banner_blocked_at', 'banner_block_reason',
    ])
    messages.success(request, 'Produit mis à jour pour la bannière.')
    return redirect('site_gp_dashboard' if request.POST.get('return_to') == 'gp' else 'site_banner_dashboard')


def _can_manage_site_banner(user, banner=None):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.role == 'super_admin':
        return True
    return banner is not None and SiteBannerPermission.objects.filter(banner=banner, user=user, can_manage=True).exists()


@login_required
@require_POST
def site_banner_permission(request, banner_id):
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        return HttpResponseForbidden('Accès réservé à l’administrateur principal')
    banner = get_object_or_404(SiteBanner, id=banner_id)
    target = get_object_or_404(User, id=request.POST.get('user_id'))
    permission, created = SiteBannerPermission.objects.get_or_create(banner=banner, user=target, defaults={'granted_by': request.user})
    action = request.POST.get('action', 'grant')
    if action == 'remove':
        permission.delete()
    SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='permission_revoked' if action == 'remove' else 'permission_granted', details={'target_user_id': target.id})
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_access(request, banner_id):
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        return HttpResponseForbidden('Accès réservé à l’administrateur principal')
    banner = get_object_or_404(SiteBanner, id=banner_id)
    target = get_object_or_404(User, id=request.POST.get('user_id'))
    action = request.POST.get('action', 'grant')
    access, _ = SiteBannerAccess.objects.get_or_create(banner=banner, user=target, defaults={'granted_by': request.user})
    if action == 'remove':
        access.delete()
        event_type = 'access_revoked'
    else:
        event_type = 'access_granted'
    SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type=event_type, details={'target_user_id': target.id})
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_purchase(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if banner.access_mode != 'paid' or banner.access_price <= 0:
        return JsonResponse({'success': False, 'error': 'Paiement non requis.'}, status=400)
    with transaction.atomic():
        SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='payment_required', details={'amount': str(banner.access_price)})
        payment, _ = SiteBannerPayment.objects.select_for_update().get_or_create(
            banner=banner, user=request.user, defaults={'amount': banner.access_price}
        )
        if payment.status == 'confirmed':
            return JsonResponse({'success': True, 'already_paid': True})
        wallet = Wallet.objects.select_for_update().filter(user=request.user).first()
        if not wallet or wallet.balance < banner.access_price:
            payment.status = 'failed'
            payment.save(update_fields=['status'])
            SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='payment_failed', details={'reason': 'insufficient_balance', 'amount': str(banner.access_price)})
            return JsonResponse({'success': False, 'error': 'Solde MicroCash insuffisant.'}, status=400)
        wallet.balance -= banner.access_price
        wallet.save(update_fields=['balance'])
        tx = Transaction.objects.create(sender=request.user, receiver=get_system_admin_wallet().user if get_system_admin_wallet() else None, amount=banner.access_price, currency='USD', type='site_banner_payment', status='approved')
        payment.amount = banner.access_price
        payment.transaction = tx
        payment.status = 'confirmed'
        payment.confirmed_at = timezone.now()
        payment.save(update_fields=['amount', 'transaction', 'status', 'confirmed_at'])
        SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='payment_confirmed', details={'amount': str(banner.access_price), 'transaction_id': tx.id})
    return JsonResponse({'success': True})


@require_POST
def site_banner_impression(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if not request.session.session_key:
        request.session.save()
    key = f'site-banner-impression-{banner.id}'
    if not request.session.get(key):
        SiteBannerEvent.objects.create(banner=banner, user=request.user if request.user.is_authenticated else None, event_type='impression', session_key=request.session.session_key)
        request.session[key] = True
    return JsonResponse({'success': True})


def site_banner_click(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if not banner.can_access(request.user):
        return HttpResponseForbidden('Accès à la bannière refusé')
    SiteBannerEvent.objects.create(banner=banner, user=request.user if request.user.is_authenticated else None, event_type='click')
    return redirect('product_detail', banner.product_id)


@login_required
@require_POST
def site_banner_image_add(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if not _can_manage_site_banner(request.user, banner):
        return HttpResponseForbidden('Accès refusé')
    form = SiteBannerImageForm(request.POST, request.FILES)
    if form.is_valid():
        image = form.save(commit=False)
        image.banner = banner
        image.save()
        SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='image_added', details={'image_id': image.id})
        messages.success(request, 'Image ajoutée à la bannière.')
    else:
        messages.error(request, 'Image invalide.')
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_image_delete(request, image_id):
    image = get_object_or_404(SiteBannerImage, id=image_id)
    if not _can_manage_site_banner(request.user, image.banner):
        return HttpResponseForbidden('Accès refusé')
    banner = image.banner
    image.image.delete(save=False)
    image.delete()
    SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='image_deleted', details={'image_id': image_id})
    messages.success(request, 'Image supprimée.')
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_image_crop(request, image_id):
    image = get_object_or_404(SiteBannerImage, id=image_id)
    if not _can_manage_site_banner(request.user, image.banner):
        return HttpResponseForbidden('Accès refusé')
    try:
        from PIL import Image
        left = max(0, int(request.POST.get('left', 0)))
        top = max(0, int(request.POST.get('top', 0)))
        width = int(request.POST.get('width', 0))
        height = int(request.POST.get('height', 0))
        with Image.open(image.image.path) as source:
            right = min(source.width, left + width)
            bottom = min(source.height, top + height)
            if width <= 0 or height <= 0 or right <= left or bottom <= top:
                raise ValueError('Zone de recadrage invalide')
            cropped = source.crop((left, top, right, bottom)).convert('RGB')
            output = io.BytesIO()
            cropped.save(output, format='WEBP', quality=84, method=6)
        image.image.save(f'{os.path.basename(os.path.splitext(image.image.name)[0])}_cropped.webp', ContentFile(output.getvalue()), save=True)
        SiteBannerEvent.objects.create(banner=image.banner, user=request.user, event_type='cropped', details={'image_id': image.id})
        messages.success(request, 'Image recadrée et enregistrée.')
    except (OSError, ValueError, TypeError):
        messages.error(request, 'Zone de recadrage invalide.')
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_crop(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if not _can_manage_site_banner(request.user, banner):
        return HttpResponseForbidden('Accès refusé')
    try:
        from PIL import Image
        with Image.open(banner.image.path) as source:
            left, top = max(0, int(request.POST.get('left', 0))), max(0, int(request.POST.get('top', 0)))
            width, height = int(request.POST.get('width', 0)), int(request.POST.get('height', 0))
            right, bottom = min(source.width, left + width), min(source.height, top + height)
            if width <= 0 or height <= 0 or right <= left or bottom <= top:
                raise ValueError('Zone de recadrage invalide')
            cropped = source.crop((left, top, right, bottom)).convert('RGB')
            output = io.BytesIO(); cropped.save(output, format='WEBP', quality=84, method=6)
        banner.image.save(f'{os.path.basename(os.path.splitext(banner.image.name)[0])}_cropped.webp', ContentFile(output.getvalue()), save=True)
        generate_banner_variants(banner.image)
        SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='cropped', details={'target': 'primary'})
        messages.success(request, 'Image principale recadrée et enregistrée.')
    except (OSError, ValueError, TypeError, AttributeError):
        messages.error(request, 'Image principale indisponible ou zone invalide.')
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_toggle(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if not _can_manage_site_banner(request.user, banner):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Accès refusé'}, status=403)
        messages.error(request, 'Accès refusé.')
        return redirect('site_banner_dashboard')

    banner.is_active = not banner.is_active
    banner.save(update_fields=['is_active'])
    SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='activated' if banner.is_active else 'deactivated')
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'is_active': banner.is_active})
    messages.success(request, 'Statut de la bannière mis à jour.')
    return redirect('site_banner_dashboard')


@login_required
@require_POST
def site_banner_delete(request, banner_id):
    banner = get_object_or_404(SiteBanner, id=banner_id)
    if not _can_manage_site_banner(request.user, banner):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Accès refusé'}, status=403)
        messages.error(request, 'Accès refusé.')
        return redirect('site_banner_dashboard')

    SiteBannerEvent.objects.create(banner=banner, user=request.user, event_type='deleted')
    banner.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Bannière supprimée.'})
    messages.success(request, 'Bannière supprimée.')
    return redirect('site_banner_dashboard')


@login_required
def dashboard(request):
    wallet = Wallet.objects.filter(user=request.user).first()
    recent_orders = Order.objects.filter(buyer=request.user).order_by('-created_at')[:5]
    recent_sales = OrderItem.objects.filter(product__shop__owner=request.user).order_by('-order__created_at')[:5]
    commission_total = Transaction.objects.filter(receiver=request.user, type='commission').aggregate(total=Sum('amount'))['total'] or 0
    cashback_total = Transaction.objects.filter(receiver=request.user, type='cashback').aggregate(total=Sum('amount'))['total'] or 0

    tikane_request = TiKaneAccessRequest.objects.filter(user=request.user).order_by('-requested_at').first()
    tikane_account = None
    try:
        tikane_account = request.user.tikane_account
    except TiKaneAccount.DoesNotExist:
        tikane_account = None
    tikane_daily_payments = tikane_account.get_daily_payment_statuses() if tikane_account and tikane_account.plan else []
    tikane_paid_days = sum(1 for p in tikane_daily_payments if p.get('paid')) if tikane_daily_payments else 0
    recent_withdrawals = WithdrawalRequest.objects.filter(user=request.user).order_by('-created_at')[:5]
    recent_deposits = Transaction.objects.filter(receiver=request.user, type='deposit').order_by('-created_at')[:5]

    agent_commission_summary = None
    if request.user.is_agent and wallet:
        agent_commission_summary = {
            'USD': getattr(wallet, 'commission_balance_usd', 0),
            'HTG': getattr(wallet, 'commission_balance_htg', 0),
            'EUR': getattr(wallet, 'commission_balance_eur', 0),
            'DOP': getattr(wallet, 'commission_balance_peso', 0),
        }

    wallet_supervision = None
    if request.user.is_superuser or request.user.role == 'super_admin':
        wallet_supervision = {'wallet_count': Wallet.objects.count(), 'rows': [], 'totals': {}}
        withdrawal_totals = {}
        for withdrawal in WithdrawalRequest.objects.filter(status__in=['approved', 'completed']).values('user_id', 'currency').annotate(total=Sum('amount')):
            withdrawal_totals[(withdrawal['user_id'], withdrawal['currency'].upper())] = withdrawal['total']
        currency_fields = (
            ('USD', 'balance', 'Principal'), ('USD', 'balance_usd', 'Compte devise'),
            ('HTG', 'balance_htg', 'Compte devise'), ('PESO', 'balance_peso', 'Compte devise'),
            ('EUR', 'balance_eur', 'Compte devise'), ('USD', 'commission_balance_usd', 'Commission'),
            ('HTG', 'commission_balance_htg', 'Commission'), ('PESO', 'commission_balance_peso', 'Commission'),
            ('EUR', 'commission_balance_eur', 'Commission'),
        )
        for current_wallet in Wallet.objects.select_related('user').order_by('user__username'):
            for currency, field_name, account_type in currency_fields:
                balance = getattr(current_wallet, field_name) or Decimal('0')
                if balance == 0 and account_type != 'Principal':
                    continue
                withdrawal_total = withdrawal_totals.get((current_wallet.user_id, currency), Decimal('0'))
                wallet_supervision['rows'].append({
                    'username': current_wallet.user.username, 'account_type': account_type,
                    'currency': currency, 'balance': balance, 'withdrawals': withdrawal_total,
                    'available': balance, 'status': 'Bloqué' if current_wallet.is_blocked else 'Actif',
                })
                wallet_supervision['totals'][currency] = wallet_supervision['totals'].get(currency, Decimal('0')) + balance

    return render(request, 'marketplace/dashboard.html', {
        'wallet': wallet,
        'recent_orders': recent_orders,
        'recent_sales': recent_sales,
        'commission_total': commission_total,
        'cashback_total': cashback_total,
        'tikane_request': tikane_request,
        'tikane_account': tikane_account,
        'tikane_daily_payments': tikane_daily_payments,
        'tikane_paid_days': tikane_paid_days,
        'recent_withdrawals': recent_withdrawals,
        'recent_deposits': recent_deposits,
        'agent_commission_summary': agent_commission_summary,
        'wallet_supervision': wallet_supervision,
    })


@login_required
def shop_detail(request, shop_id):
    shop = get_object_or_404(Shop, id=shop_id)
    products = Product.objects.filter(shop=shop, quantity__gt=0)
    
    # Attacher les stats d'avis
    attach_reviews_stats(products)
    
    return render(request, 'marketplace/shop.html', {'shop': shop, 'products': products})


def product_detail(request, product_id):
    """Vue pour afficher le détail d'un produit et les recommandations"""
    product = get_object_or_404(Product, id=product_id)
    similar_products = get_similar_products(product_id, limit=5)
    approved_reviews = product.reviews.filter(is_approved=True).select_related('user')
    review_stats = product.reviews.filter(is_approved=True).aggregate(
        average=Avg('rating'),
        count=Count('id')
    )
    average_rating = review_stats['average'] or 0
    reviews_count = review_stats['count'] or 0

    if request.user.is_authenticated:
        existing_review = product.reviews.filter(user=request.user).first()
        can_review = has_purchased_product(request.user, product)
    else:
        existing_review = None
        can_review = False

    if request.method == 'POST':
        form = ProductReviewForm(request.POST)
        if not can_review:
            messages.error(request, 'Vous devez avoir acheté ce produit pour laisser un avis.')
        elif form.is_valid():
            rating = int(form.cleaned_data['rating'])
            comment = form.cleaned_data['comment']
            ProductReview.objects.update_or_create(
                product=product,
                user=request.user,
                defaults={
                    'rating': rating,
                    'comment': comment,
                    'is_approved': False,
                }
            )
            messages.success(request, 'Merci ! Votre avis a été soumis et est en attente de modération.')
            return redirect('product_detail', product_id=product.id)
    else:
        form = ProductReviewForm(instance=existing_review) if existing_review else ProductReviewForm()

    pending_review = existing_review and not existing_review.is_approved

    return render(request, 'marketplace/product_detail.html', {
        'product': product,
        'similar_products': similar_products,
        'approved_reviews': approved_reviews,
        'average_rating': average_rating,
        'reviews_count': reviews_count,
        'form': form,
        'can_review': can_review,
        'pending_review': pending_review,
        'existing_review': existing_review,
    })


@login_required
def request_product_access(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if not getattr(request.user, 'is_seller', False):
        messages.error(request, 'Seuls les vendeurs peuvent demander l’accès à un produit.')
        return redirect('product_detail', product_id=product.id)
    if product.shop.owner == request.user:
        messages.error(request, 'Vous possédez déjà ce produit.')
        return redirect('product_detail', product_id=product.id)

    settings = MarketplaceSettings.get_solo()

    existing_request = ProductAccessRequest.objects.filter(seller=request.user, product=product).exclude(status='rejected').first()
    if existing_request:
        messages.warning(request, 'Vous avez déjà une demande en cours ou approuvée pour ce produit.')
        return redirect('product_detail', product_id=product.id)

    existing_copy = ResellerProduct.objects.filter(seller=request.user, original_product=product, status__in=['active', 'suspended']).first()
    if existing_copy:
        messages.warning(request, 'Ce produit est déjà copié dans votre boutique.')
        return redirect('product_detail', product_id=product.id)

    product_copies_count = ResellerProduct.objects.filter(original_product=product, status='active').count()
    if product_copies_count >= settings.get_copy_limit():
        messages.error(request, 'Limite de copies atteinte pour ce produit. Impossible de soumettre une nouvelle demande.')
        return redirect('product_detail', product_id=product.id)

    active_seller_copies = ResellerProduct.objects.filter(seller=request.user, status='active').count()
    if active_seller_copies >= settings.get_max_active_copies_for_seller():
        messages.error(request, 'Vous avez atteint le nombre maximum de copies actives autorisées pour votre boutique.')
        return redirect('product_detail', product_id=product.id)

    if request.method == 'POST':
        req = ProductAccessRequest.objects.create(
            seller=request.user,
            product=product,
            owner_shop=product.shop,
            status='pending'
        )

        # Auto-approve/copy if configured
        if settings.allow_auto_copy and not settings.validation_required:
            seller_commission_type, seller_commission_value = settings.get_seller_commission(request.user)
            req.status = 'approved'
            req.commission_type = seller_commission_type
            req.commission_value = seller_commission_value
            req.save()
            rp, created = ResellerProduct.objects.get_or_create(
                seller=request.user,
                original_product=product,
                defaults={
                    'commission_type': seller_commission_type,
                    'commission_value': seller_commission_value,
                    'status': 'active'
                }
            )
            if not rp.copied_product:
                new_prod = product.create_copy_for_reseller(request.user)
                rp.copied_product = new_prod
                rp.save()
            messages.success(request, 'Produit copié dans votre boutique (auto-approval).')
        else:
            messages.success(request, 'Votre demande a été soumise et est en attente de validation.')

    return redirect('product_detail', product_id=product.id)


@login_required
@login_required
def add_product(request):
    # Pour les administrateurs, créer une boutique automatiquement si elle n'existe pas
    if request.user.is_staff:
        shop, created = Shop.objects.get_or_create(
            owner=request.user,
            defaults={'name': f'Boutique Admin - {request.user.username}'}
        )
    else:
        shop = Shop.objects.filter(owner=request.user).first()
        if not shop:
            messages.error(request, 'Vous devez avoir une boutique pour ajouter un produit.')
            return redirect('home')
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            from .image_utils import optimize_image, validate_image, generate_product_image

            product = form.save(commit=False)
            product.shop = shop

            # Convertir le prix saisi dans la devise locale en USD pour le stockage interne
            price_in_currency = form.cleaned_data.get('price_in_currency')
            price_input_currency = form.cleaned_data.get('price_input_currency')
            if price_in_currency is not None and price_input_currency:
                try:
                    product.price_ht = convert_currency(price_in_currency, price_input_currency, 'USD')
                except Exception:
                    messages.error(request, 'Impossible de convertir le prix en USD. Vérifiez la devise et le montant.')
                    return render(request, 'marketplace/add_product.html', {'form': form, 'shop': shop})
            product.price_input_currency = price_input_currency

            # Générer automatiquement une image si aucune image custom n'est fournie
            if not form.cleaned_data.get('custom_image') and not product.image:
                product.image = generate_product_image(product.name)

            product.save()

            # Gérer l'image personnalisée si fournie
            if form.cleaned_data.get('custom_image'):
                custom_image = form.cleaned_data['custom_image']
                is_valid, error_msg = validate_image(custom_image, max_size_mb=5)
                if is_valid:
                    optimized_image = optimize_image(custom_image)
                    product.custom_image = optimized_image
                    product.save()
                else:
                    messages.warning(request, f"Image personnalisée: {error_msg}")

            # Gérer les images multiples (galerie)
            images = request.FILES.getlist('images')
            is_first = True

            for image_file in images:
                # Valider l'image
                is_valid, error_msg = validate_image(image_file, max_size_mb=5)
                if not is_valid:
                    messages.warning(request, f"Image {image_file.name}: {error_msg}")
                    continue

                # Optimiser l'image
                optimized_image = optimize_image(image_file)

                # Créer l'enregistrement ProductImage
                product_image = ProductImage(
                    product=product,
                    image=optimized_image,
                    is_primary=is_first,
                    alt_text=f"{product.name} - Image {len(images)}" if is_first else f"{product.name}"
                )
                product_image.save()
                is_first = False

            refresh_recommendation_engine()
            messages.success(request, f'Produit ajouté avec succès ! {len(images)} image(s) de galerie')
            return redirect('shop_detail', shop_id=shop.id)
        else:
            messages.error(request, 'Erreur lors de la création du produit')
    else:
        form = ProductForm()
    
    return render(request, 'marketplace/add_product.html', {'form': form, 'shop': shop})


@login_required
def order_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    sold_out = product.quantity <= 0
    if sold_out:
        messages.error(request, 'Ce produit est épuisé et n’est plus disponible à l’achat.')
        return render(request, 'marketplace/order_confirm.html', {
            'product': product,
            'sold_out': True,
            'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', 'VOTRE_CLE_GOOGLE_MAPS_API_ICI')
        })

    if request.method == 'POST':
        form = OrderForm(request.POST)
        quantity = int(request.POST.get('quantity', 1))

        if form.is_valid() and quantity > 0 and quantity <= product.quantity:
            # Vérifier le solde
            price_per_item = product.price_ht
            total_amount = price_per_item * quantity

            buyer_wallet, _ = Wallet.objects.get_or_create(user=request.user)

            if buyer_wallet.balance < total_amount:
                messages.error(request, f'Solde insuffisant. Vous avez {buyer_wallet.balance}$, montant requis: {total_amount}$.')
                return redirect('shop_detail', shop_id=product.shop.id)

            # Empêcher auto-achat
            if request.user == product.shop.owner:
                messages.error(request, 'Auto-achat interdit.')
                return redirect('shop_detail', shop_id=product.shop.id)

            from django.db import transaction
            with transaction.atomic():
                # Calcul des montants
                system_commission = Decimal('0.5') * quantity
                cashback_acheteur = CommissionManager.get_config('cashback_par_produit_acheteur') * Decimal(str(quantity))
                cashback_vendeur = CommissionManager.get_config('cashback_par_produit_vendeur') * Decimal(str(quantity))

                # Débit acheteur
                buyer_wallet.balance -= total_amount
                buyer_wallet.commission_balance_usd += cashback_acheteur
                buyer_wallet.save()

                # Créditer le vendeur sur son compte commission cashback
                seller_wallet, _ = Wallet.objects.get_or_create(user=product.shop.owner)
                if cashback_vendeur > 0:
                    seller_wallet.commission_balance_usd += cashback_vendeur
                    seller_wallet.save()

                # Mettre à jour stock
                product.quantity -= quantity
                if product.quantity <= 0:
                    product.quantity = 0
                product.save()

                # Créer commande avec les informations GPS
                estimated_at = timezone.now() + timedelta(days=3)
                order = Order.objects.create(
                    buyer=request.user,
                    total_amount=total_amount,
                    delivery_address=form.cleaned_data['delivery_address'],
                    buyer_lat=form.cleaned_data.get('buyer_lat'),
                    buyer_lng=form.cleaned_data.get('buyer_lng'),
                    buyer_address_details=form.cleaned_data.get('buyer_address_details'),
                    status='awaiting_delivery',
                    delivery_estimated_at=estimated_at,
                    product_name=product.name,
                )
                OrderItem.objects.create(order=order, product=product, quantity=quantity, price_ht=price_per_item)

                # Transactions de séquestre et frais
                Transaction.objects.create(sender=request.user, receiver=None, amount=total_amount, type='escrow_hold', status='pending')
                admin_wallet = get_system_admin_wallet()
                if admin_wallet:
                    admin_amount, distribution_amount = MarketplaceSettings.get_solo().get_commission_split(system_commission)
                    admin_wallet.credit_commission(admin_amount, currency='USD')
                    if distribution_amount > 0:
                        admin_wallet.credit_distribution(distribution_amount, currency='USD')
                    Transaction.objects.create(sender=None, receiver=admin_wallet.user, amount=admin_amount, type='commission', status='approved')
                else:
                    Transaction.objects.create(sender=None, receiver=product.shop.owner, amount=system_commission, type='commission', status='approved')
                if cashback_acheteur > 0:
                    Transaction.objects.create(sender=None, receiver=request.user, amount=cashback_acheteur, type='cashback', status='approved')
                if cashback_vendeur > 0:
                    Transaction.objects.create(sender=None, receiver=product.shop.owner, amount=cashback_vendeur, type='cashback', status='approved')

                # Assigner automatiquement la livraison
                from .business_logic import DeliveryAssignmentManager
                assignment_manager = DeliveryAssignmentManager()
                assignment_manager.assign_delivery_roundrobin(order)

            messages.success(request, 'Commande passée avec succès ! Le livreur pourra voir votre position GPS.')
            return redirect('order_confirm', order_id=order.id)
        else:
            messages.error(request, 'Erreur dans le formulaire. Vérifiez les informations saisies.')
    else:
        form = OrderForm()

    return render(request, 'marketplace/order_confirm.html', {
        'product': product,
        'form': form,
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', 'VOTRE_CLE_GOOGLE_MAPS_API_ICI')
    })


@login_required
def order_confirm(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    commission_breakdown = CommissionManager.calcul_commande_from_order(order)
    return render(request, 'marketplace/order_confirm.html', {
        'order': order,
        'commission_breakdown': commission_breakdown,
        'server_time': timezone.now(),
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', 'VOTRE_CLE_GOOGLE_MAPS_API_ICI')
    })


@login_required
def hide_order_timer(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    if order.status == 'awaiting_delivery':
        order.timer_hidden = True
        order.save()
        messages.success(request, 'Le timer a été masqué. L’administrateur et le vendeur peuvent toujours voir les informations de livraison.')
    else:
        messages.error(request, 'Impossible de masquer le timer pour cette commande.')
    return redirect('order_confirm', order_id=order.id)


def liberer_paiement(order):
    seller_revenue_total = Decimal('0')
    for item in order.items.all():
        seller_revenue = (item.price_ht - Decimal('0.6')) * item.quantity
        seller_revenue_total += seller_revenue
        seller_wallet = Wallet.objects.get(user=item.product.shop.owner)
        seller_wallet.balance += seller_revenue
        seller_wallet.save()
        Transaction.objects.create(sender=None, receiver=item.product.shop.owner, amount=seller_revenue, type='sale', status='approved')

    escrow_transaction = Transaction.objects.filter(sender=order.buyer, type='escrow_hold', amount=order.total_amount, status='pending').first()
    if escrow_transaction:
        escrow_transaction.status = 'released'
        escrow_transaction.save()

    return seller_revenue_total


@login_required
def confirm_delivery(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    if order.status != 'awaiting_delivery':
        messages.error(request, 'Cette commande ne peut pas être confirmée.')
        return redirect('profile')
    
    liberer_paiement(order)
    order.status = 'delivered'
    order.date_reception_confirmee = timezone.now()
    order.timer_hidden = False
    order.save()
    
    # Envoyer une notification au livreur
    try:
        delivery_assignment = DeliveryAssignment.objects.filter(order=order).first()
        if delivery_assignment:
            delivery_driver = delivery_assignment.employee.user
            
            # Créer/récupérer la conversation privée entre l'acheteur et le livreur
            conversation, _ = PrivateConversation.get_or_create(request.user, delivery_driver)
            
            # Créer un message privé au livreur
            PrivateMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                receiver=delivery_driver,
                content=f"✅ Commande #{order.id} a été livrée avec succès - Merci pour votre service!"
            )
            
            # Créer une notification sur le profil du livreur
            create_delivery_notification(
                delivery_assignment,
                delivery_driver,
                'delivered',
                '✅ Commande livrée avec succès',
                f'Commande #{order.id} a été confirmée livrée par le client.'
            )
        
        # Notifier l'administrateur
        admin_user = User.objects.filter(is_superuser=True).order_by('id').first() or User.objects.filter(role='super_admin').order_by('id').first()
        if admin_user and admin_user != request.user:
            # Créer/récupérer la conversation privée entre l'acheteur et l'admin
            admin_conversation, _ = PrivateConversation.get_or_create(request.user, admin_user)
            
            # Créer un message privé à l'administrateur
            PrivateMessage.objects.create(
                conversation=admin_conversation,
                sender=request.user,
                receiver=admin_user,
                content=f"✅ Commande #{order.id} a été livrée avec succès par {request.user.get_full_name() or request.user.username} (Montant: {order.total_amount})"
            )
            
            # Créer une notification sur le profil de l'admin
            if delivery_assignment:
                create_delivery_notification(
                    delivery_assignment,
                    admin_user,
                    'delivered',
                    '✅ Commande livrée avec succès',
                    f'Commande #{order.id} a été confirmée livrée. Client: {request.user.get_full_name() or request.user.username}'
                )
    except Exception as e:
        # Log l'erreur mais ne bloque pas le processus
        print(f"Erreur lors de la notification: {str(e)}")
    
    messages.success(request, 'Réception confirmée, paiement libéré au vendeur.')
    return redirect('profile')


@login_required
def stats(request):
    top_products = OrderItem.objects.filter(order__status='paid').values('product__name').annotate(total_sold=Sum('quantity')).order_by('-total_sold')[:10]
    total_sales = OrderItem.objects.filter(order__status='paid', product__shop__owner=request.user).aggregate(total=Sum('price_ht'))['total'] or 0
    return render(request, 'marketplace/stats.html', {
        'top_products': top_products,
        'total_sales': total_sales,
    })


@login_required
def admin_add_money(request):
    is_principal_admin = request.user.is_superuser or request.user.has_perm('marketplace.principal_admin_power')
    if not request.user.is_staff and not is_principal_admin:
        messages.error(request, 'Accès refusé.')
        return redirect('home')

    users = User.objects.all().order_by('username')
    if request.method == 'POST':
        action = request.POST.get('action', 'add')
        target = request.POST.get('target', 'single')
        user_id = request.POST.get('user_id')
        amount = request.POST.get('amount')
        currency = request.POST.get('currency', 'HTG')

        try:
            amount_decimal = Decimal(amount)
            if amount_decimal <= 0:
                raise ValueError('Montant doit être supérieur à zéro.')
        except (ValueError, InvalidOperation):
            messages.error(request, 'Montant invalide. Veuillez entrer un nombre positif.')
            return redirect('admin_add_money')

        if currency != 'USD':
            from .business_logic import convert_currency
            amount_decimal = convert_currency(amount_decimal, currency, 'USD')

        account_type = request.POST.get('account_type', 'principal')
        commission_field = get_commission_balance_field(currency)

        if target == 'all':
            users_changed = 0
            users_skipped = 0
            for user in users:
                wallet, _ = Wallet.objects.get_or_create(user=user)
                if action == 'add':
                    if account_type == 'agent':
                        current_value = getattr(wallet, commission_field, Decimal('0')) or Decimal('0')
                        setattr(wallet, commission_field, current_value + amount_decimal)
                        wallet.save(update_fields=[commission_field])
                        Transaction.objects.create(
                            sender=None,
                            receiver=user,
                            amount=amount_decimal,
                            currency=currency,
                            type='admin_add_all_agent',
                            status='approved'
                        )
                    else:
                        wallet.balance += amount_decimal
                        wallet.save(update_fields=['balance'])
                        Transaction.objects.create(
                            sender=None,
                            receiver=user,
                            amount=amount_decimal,
                            currency='USD',
                            type='admin_add_all',
                            status='approved'
                        )
                    users_changed += 1
                else:
                    if account_type == 'agent':
                        current_value = getattr(wallet, commission_field, Decimal('0')) or Decimal('0')
                        if current_value >= amount_decimal:
                            setattr(wallet, commission_field, current_value - amount_decimal)
                            wallet.save(update_fields=[commission_field])
                            Transaction.objects.create(
                                sender=user,
                                receiver=None,
                                amount=amount_decimal,
                                currency=currency,
                                type='admin_withdraw_all_agent',
                                status='approved'
                            )
                            users_changed += 1
                        else:
                            users_skipped += 1
                    else:
                        if wallet.balance >= amount_decimal:
                            wallet.balance -= amount_decimal
                            wallet.save(update_fields=['balance'])
                            Transaction.objects.create(
                                sender=user,
                                receiver=None,
                                amount=amount_decimal,
                                currency='USD',
                                type='admin_withdraw_all',
                                status='approved'
                            )
                            users_changed += 1
                        else:
                            users_skipped += 1

            if action == 'add':
                messages.success(request, f'Ajout de {amount} {currency} effectué pour {users_changed} utilisateurs.')
            else:
                if users_skipped:
                    messages.warning(request, f'Retrait de {amount} {currency} effectué pour {users_changed} utilisateurs. {users_skipped} utilisateurs avaient un solde insuffisant et ont été ignorés.')
                else:
                    messages.success(request, f'Retrait de {amount} {currency} effectué pour {users_changed} utilisateurs.')
            return redirect('admin_add_money')

        try:
            user = User.objects.get(id=user_id)
            wallet, _ = Wallet.objects.get_or_create(user=user)
            if action == 'add':
                if account_type == 'agent':
                    current_value = getattr(wallet, commission_field, Decimal('0')) or Decimal('0')
                    setattr(wallet, commission_field, current_value + amount_decimal)
                    wallet.save(update_fields=[commission_field])
                    Transaction.objects.create(
                        sender=None,
                        receiver=user,
                        amount=amount_decimal,
                        currency=currency,
                        type='admin_add_agent',
                        status='approved'
                    )
                    messages.success(request, f'Ajout de {amount} {currency} au compte agent de {user.username}.')
                else:
                    wallet.balance += amount_decimal
                    wallet.save(update_fields=['balance'])
                    Transaction.objects.create(
                        sender=None,
                        receiver=user,
                        amount=amount_decimal,
                        currency='USD',
                        type='admin_add',
                        status='approved'
                    )
                    messages.success(request, f'Ajout de {amount} {currency} au portefeuille principal de {user.username}.')
            else:
                if account_type == 'agent':
                    current_value = getattr(wallet, commission_field, Decimal('0')) or Decimal('0')
                    if current_value < amount_decimal:
                        messages.error(request, f'Solde agent insuffisant pour {user.username}.')
                        return redirect('admin_add_money')
                    setattr(wallet, commission_field, current_value - amount_decimal)
                    wallet.save(update_fields=[commission_field])
                    Transaction.objects.create(
                        sender=user,
                        receiver=None,
                        amount=amount_decimal,
                        currency=currency,
                        type='admin_withdraw_agent',
                        status='approved'
                    )
                    messages.success(request, f'Retrait de {amount} {currency} effectué du compte agent de {user.username}.')
                else:
                    if wallet.balance < amount_decimal:
                        messages.error(request, f'Solde insuffisant pour {user.username}.')
                        return redirect('admin_add_money')
                    wallet.balance -= amount_decimal
                    wallet.save(update_fields=['balance'])
                    Transaction.objects.create(
                        sender=user,
                        receiver=None,
                        amount=amount_decimal,
                        currency='USD',
                        type='admin_withdraw',
                        status='approved'
                    )
                    messages.success(request, f'Retrait de {amount} {currency} effectué pour {user.username}.')
        except User.DoesNotExist:
            messages.error(request, 'Utilisateur invalide.')
        return redirect('admin_add_money')

    default_amount = request.GET.get('amount', '')
    default_currency = request.GET.get('currency', 'HTG')
    default_target = request.GET.get('target', 'single')
    default_action = request.GET.get('action', 'add')
    default_account_type = request.GET.get('account_type', 'principal')

    return render(request, 'marketplace/admin_add_money.html', {
        'users': users,
        'default_amount': default_amount,
        'default_currency': default_currency,
        'default_target': default_target,
        'default_action': default_action,
        'default_account_type': default_account_type,
    })


@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_add_agent(request):
    """Vue pour qu'un admin gère l’accès agent."""
    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')
        if not user_id:
            messages.error(request, 'Sélectionnez un utilisateur valide.')
            return redirect('admin_add_agent')

        try:
            user = User.objects.get(id=user_id)
            agent, created = Agent.objects.get_or_create(user=user)
            if action == 'activate':
                if agent.is_active and user.is_agent:
                    messages.error(request, f'{user.username} est déjà un agent actif.')
                else:
                    agent.is_active = True
                    agent.save()
                    user.is_agent = True
                    user.save(update_fields=['is_agent'])
                    messages.success(request, f'{user.username} a été activé comme agent.')
            elif action == 'suspend':
                if not agent.is_active:
                    messages.error(request, f'{user.username} est déjà suspendu ou n’est pas agent.')
                else:
                    agent.is_active = False
                    agent.save()
                    user.is_agent = False
                    user.save(update_fields=['is_agent'])
                    messages.success(request, f'{user.username} a été suspendu comme agent.')
            elif action == 'reactivate':
                if agent.is_active:
                    messages.error(request, f'{user.username} est déjà actif.')
                else:
                    agent.is_active = True
                    agent.save()
                    user.is_agent = True
                    user.save(update_fields=['is_agent'])
                    messages.success(request, f'{user.username} a été réactivé comme agent.')
            elif action == 'remove':
                if agent.is_active or user.is_agent:
                    agent.is_active = False
                    agent.save()
                    user.is_agent = False
                    user.save(update_fields=['is_agent'])
                    messages.success(request, f'L’accès agent de {user.username} a été retiré.')
                else:
                    messages.error(request, f'{user.username} n’a pas d’accès agent actif.')
            else:
                messages.error(request, 'Action agent non reconnue.')
        except User.DoesNotExist:
            messages.error(request, 'Utilisateur invalide.')
        return redirect('admin_add_agent')
    
    users = User.objects.exclude(is_staff=True).order_by('username')
    active_agents = Agent.objects.filter(is_active=True).select_related('user').order_by('user__username')
    suspended_agents = Agent.objects.filter(is_active=False).select_related('user').order_by('user__username')
    return render(request, 'marketplace/admin_add_agent.html', {
        'users': users,
        'active_agents': active_agents,
        'suspended_agents': suspended_agents,
    })


@login_required
def add_product(request):
    """Vue pour ajouter ou modifier un produit"""
    # Vérifier que l'utilisateur est vendeur ou admin
    if not (request.user.is_seller or request.user.is_staff):
        messages.error(request, 'Vous n\'avez pas accès à cette fonctionnalité.')
        return redirect('profile')

    # Récupérer ou créer la boutique de l'utilisateur
    shop, created = Shop.objects.get_or_create(
        owner=request.user,
        defaults={'name': f'Boutique {request.user.username}'}
    )

    # Vérifier si on édite un produit existant
    edit_product_id = request.GET.get('edit')
    product = None
    if edit_product_id:
        try:
            product = Product.objects.get(id=edit_product_id, shop=shop)
        except Product.DoesNotExist:
            messages.error(request, 'Produit non trouvé ou vous n\'avez pas accès à ce produit.')
            return redirect('my_shop')

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            product = form.save(commit=False)
            product.shop = shop

            # Conserver le prix original et le convertir en USD pour la base
            price_in_currency = form.cleaned_data.get('price_in_currency')
            price_input_currency = form.cleaned_data.get('price_input_currency')
            if price_in_currency is not None and price_input_currency:
                product.price_original = price_in_currency
                product.price_original_currency = price_input_currency
                try:
                    product.price_ht = convert_currency(price_in_currency, price_input_currency, 'USD')
                except Exception:
                    messages.error(request, 'Impossible de convertir le prix en USD. Vérifiez la devise et le montant.')
                    return render(request, 'marketplace/add_product.html', {'form': form, 'shop': shop, 'product': product, 'is_edit': bool(edit_product_id), 'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY})
                product.price_input_currency = price_input_currency

            # Gestion de l'image personnalisée
            if form.cleaned_data.get('custom_image'):
                product.custom_image = form.cleaned_data['custom_image']
                product.image = None  # Supprimer l'ancienne image générée

            product.save()

            # Gestion des images multiples
            if request.FILES.getlist('images'):
                for image_file in request.FILES.getlist('images'):
                    ProductImage.objects.create(
                        product=product,
                        image=image_file
                    )

            if edit_product_id:
                messages.success(request, f'Produit "{product.name}" modifié avec succès.')
            else:
                messages.success(request, f'Produit "{product.name}" ajouté avec succès.')

            return redirect('my_shop')
        else:
            messages.error(request, 'Veuillez corriger les erreurs dans le formulaire.')
    else:
        form = ProductForm(instance=product)

    return render(request, 'marketplace/add_product.html', {
        'form': form,
        'product': product,
        'shop': shop,
        'is_edit': bool(edit_product_id),
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    })


# ------------------------------
# API views
# ------------------------------

# API pour génération automatique d'images
def generate_product_image_api(request):
    """API pour générer une image automatique basée sur le nom du produit"""
    if request.method == 'GET':
        product_name = request.GET.get('name', '').strip()
        if not product_name:
            return JsonResponse({'error': 'Nom du produit requis'}, status=400)

        from .image_utils import generate_product_image
        image_url = generate_product_image(product_name)

        return JsonResponse({
            'image_url': image_url,
            'product_name': product_name
        })

    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


def get_image_suggestions_api(request):
    """API pour obtenir plusieurs suggestions d'images"""
    if request.method == 'GET':
        product_name = request.GET.get('name', '').strip()
        count = int(request.GET.get('count', 3))

        if not product_name:
            return JsonResponse({'error': 'Nom du produit requis'}, status=400)

        from .image_utils import get_image_suggestions
        suggestions = get_image_suggestions(product_name, count)

        return JsonResponse({
            'suggestions': suggestions,
            'product_name': product_name,
            'count': len(suggestions)
        })

    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.AllowAny])
    def similar(self, request, pk=None):
        """Retourne les produits similaires"""
        try:
            product = self.get_object()
            similar = get_similar_products(pk, limit=5)
            serializer = ProductSerializer(similar, many=True)
            return Response({
                'product_id': pk,
                'similar_products': serializer.data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def recommendations(self, request):
        """Retourne les recommandations personnalisées"""
        try:
            limit = int(request.query_params.get('limit', 5))
            if request.user.is_authenticated:
                products = get_personalized_recommendations(request.user, limit=limit)
                recommendation_type = 'personalized'
            else:
                products = get_trending_products(limit=limit)
                recommendation_type = 'trending'
            
            serializer = ProductSerializer(products, many=True)
            return Response({
                'type': recommendation_type,
                'products': serializer.data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def trending(self, request):
        """Retourne les produits tendances"""
        try:
            limit = int(request.query_params.get('limit', 5))
            products = get_trending_products(limit=limit)
            serializer = ProductSerializer(products, many=True)
            return Response(serializer.data, many=True)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ShopViewSet(viewsets.ModelViewSet):
    queryset = Shop.objects.all()
    serializer_class = ShopSerializer
    permission_classes = [permissions.IsAuthenticated]


class WalletViewSet(viewsets.ModelViewSet):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Wallet.objects.filter(user=self.request.user)

    @action(detail=False, methods=['post'])
    def request_transfer(self, request):
        wallet = self.get_queryset().first()
        if not wallet:
            return Response({'error': 'Wallet not found'}, status=status.HTTP_404_NOT_FOUND)
        amount = request.data.get('amount')
        receiver_id = request.data.get('receiver_id')
        if not amount or not receiver_id:
            return Response({'error': 'Amount and receiver_id required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            receiver = User.objects.get(id=receiver_id)
        except User.DoesNotExist:
            return Response({'error': 'Receiver not found'}, status=status.HTTP_404_NOT_FOUND)
        if wallet.balance < float(amount):
            return Response({'error': 'Insufficient balance'}, status=status.HTTP_400_BAD_REQUEST)
        Transaction.objects.create(
            sender=request.user,
            receiver=receiver,
            amount=amount,
            type='transfer',
            status='pending'
        )
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def admin_add_money(self, request):
        user_id = request.data.get('user_id')
        amount = request.data.get('amount')
        if not user_id or not amount:
            return Response({'error': 'user_id and amount required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        wallet = Wallet.objects.get(user=user)
        wallet.balance += Decimal(amount)
        wallet.save()
        Transaction.objects.create(
            sender=None,
            receiver=user,
            amount=amount,
            type='admin_add',
            status='approved'
        )
        return Response({'message': 'Money added successfully'}, status=status.HTTP_200_OK)


class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:  # admin
            return Transaction.objects.all()
        return Transaction.objects.filter(sender=user) | Transaction.objects.filter(receiver=user)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def complete_transaction(self, request, pk=None):
        """Marquer une transaction comme complétée"""
        transaction = self.get_object()
        transaction.status = 'completed'
        transaction.save()
        return Response({'message': 'Transaction completed'}, status=status.HTTP_200_OK)


# =======================================
# API ENDPOINTS POUR GEOLOCALISATION
# =======================================

@login_required
def update_driver_location_api(request):
    """API endpoint pour mettre à jour la position du livreur en temps réel"""
    if request.method == 'POST':
        import json
        
        try:
            data = json.loads(request.body)
            latitude = float(data.get('latitude'))
            longitude = float(data.get('longitude'))
            assignment_id = data.get('assignment_id')
            
            if not assignment_id:
                return JsonResponse({'error': 'assignment_id requis'}, status=400)
            
            # Vérifier que l'utilisateur est un livreur
            if not request.user.is_delivery_employee:
                return JsonResponse({'error': 'Accès réservé aux livreurs'}, status=403)
            
            try:
                assignment = DeliveryAssignment.objects.get(id=assignment_id)
                
                # Vérifier que le livreur est assigné à cette livraison
                if assignment.employee.user != request.user:
                    return JsonResponse({'error': 'Vous n\'êtes pas assigné à cette livraison'}, status=403)
                
                # Mettre à jour la position du livreur
                assignment.driver_lat = latitude
                assignment.driver_lng = longitude
                assignment.save()
                
                # Créer un suivi GPS
                update_delivery_tracking(
                    assignment,
                    latitude=latitude,
                    longitude=longitude,
                    status_update='Position mise à jour'
                )
                
                return JsonResponse({
                    'success': True,
                    'message': 'Position mise à jour',
                    'latitude': float(latitude),
                    'longitude': float(longitude),
                    'distance_km': calculate_distance(
                        float(assignment.driver_lat),
                        float(assignment.driver_lng),
                        float(assignment.buyer_lat),
                        float(assignment.buyer_lng)
                    ) if assignment.buyer_lat and assignment.buyer_lng else None
                })
            
            except DeliveryAssignment.DoesNotExist:
                return JsonResponse({'error': 'Livraison non trouvée'}, status=404)
        
        except (ValueError, json.JSONDecodeError) as e:
            return JsonResponse({'error': f'Erreur: {str(e)}'}, status=400)
    
    return JsonResponse({'error': 'Méthode POST requise'}, status=405)


@login_required
def manage_delivery_assignments(request):
    """
    Page d'administration pour gérer les assignations de livraison.
    Affiche les commandes assignées et non assignées, permet d'assigner/réassigner.
    """
    if not request.user.is_staff and request.user.role != 'super_admin':
        messages.error(request, 'Accès refusé.')
        return redirect('profile')
    
    # Récupérer toutes les commandes sans assignation ou en attente
    unassigned_orders = Order.objects.filter(
        status__in=['pending', 'awaiting_delivery']
    ).exclude(
        deliveryassignment__isnull=False
    ).order_by('-created_at')
    
    # Récupérer les commandes déjà assignées avec prefetch_related
    assigned_orders = Order.objects.filter(
        status__in=['pending', 'awaiting_delivery'],
        deliveryassignment__isnull=False
    ).prefetch_related(
        'deliveryassignment_set__employee__user'
    ).order_by('-created_at')
    
    # Récupérer tous les livreurs disponibles
    available_drivers = DeliveryEmployee.objects.filter(is_available=True).order_by('user__first_name')
    
    context = {
        'unassigned_orders': unassigned_orders,
        'assigned_orders': assigned_orders,
        'available_drivers': available_drivers,
    }
    
    return render(request, 'marketplace/manage_delivery_assignments.html', context)


@login_required
def assign_order_to_driver(request):
    """
    Assigne manuellement une commande à un livreur spécifique.
    Requête AJAX POST.
    """
    if not request.user.is_staff and request.user.role != 'super_admin':
        return JsonResponse({'error': 'Accès refusé'}, status=403)
    
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        driver_id = request.POST.get('driver_id')
        
        try:
            order = Order.objects.get(id=order_id)
            driver = DeliveryEmployee.objects.get(id=driver_id)
            
            # Supprimer l'assignation existante si elle existe
            existing_assignment = DeliveryAssignment.objects.filter(order=order).first()
            if existing_assignment:
                existing_assignment.delete()
            
            # Assigner manuellement
            from .business_logic import DeliveryAssignmentManager
            assignment = DeliveryAssignmentManager.assign_delivery_manual(order, driver)
            
            # Créer une notification pour le livreur
            create_delivery_notification(
                assignment,
                driver.user,
                'status_update',
                '📦 Nouvelle commande assignée',
                f'Commande #{order.id} a été assignée manuellement par l\'administrateur.'
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Commande #{order.id} assignée à {driver.user.get_full_name() or driver.identifier}',
                'assignment_id': assignment.id
            })
        
        except Order.DoesNotExist:
            return JsonResponse({'error': 'Commande non trouvée'}, status=404)
        except DeliveryEmployee.DoesNotExist:
            return JsonResponse({'error': 'Livreur non trouvé'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Méthode POST requise'}, status=405)


@login_required
def reassign_delivery_order(request, order_id):
    """
    Réassigne une commande à un autre livreur.
    Vue GET et POST.
    """
    if not request.user.is_staff and request.user.role != 'super_admin':
        messages.error(request, 'Accès refusé.')
        return redirect('profile')
    
    order = get_object_or_404(Order, id=order_id)
    assignment = DeliveryAssignment.objects.filter(order=order).first()
    available_drivers = DeliveryEmployee.objects.filter(is_available=True).exclude(id=assignment.employee.id if assignment else None)
    
    if request.method == 'POST':
        driver_id = request.POST.get('driver_id')
        
        try:
            new_driver = DeliveryEmployee.objects.get(id=driver_id)
            
            # Réassigner
            from .business_logic import DeliveryAssignmentManager
            DeliveryAssignmentManager.assign_delivery_manual(order, new_driver)
            
            messages.success(request, f'Commande réassignée à {new_driver.user.get_full_name() or new_driver.identifier}')
            return redirect('manage_delivery_assignments')
        
        except DeliveryEmployee.DoesNotExist:
            messages.error(request, 'Livreur non trouvé.')
    
    context = {
        'order': order,
        'assignment': assignment,
        'available_drivers': available_drivers,
    }
    
    return render(request, 'marketplace/reassign_delivery_order.html', context)


@login_required
def get_delivery_location_api(request, assignment_id):
    """API endpoint pour récupérer les positions en temps réel"""
    if request.method == 'GET':
        try:
            assignment = DeliveryAssignment.objects.get(id=assignment_id)
            
            # Vérifier que l'utilisateur peut voir cette livraison
            if (request.user != assignment.employee.user and 
                request.user != assignment.order.buyer and 
                request.user != assignment.order.seller.owner):
                return JsonResponse({'error': 'Accès refusé'}, status=403)
            
            # Calculer les distances
            driver_to_buyer_distance = None
            driver_to_buyer_time = None
            
            if (assignment.driver_lat and assignment.driver_lng and 
                assignment.buyer_lat and assignment.buyer_lng):
                driver_to_buyer_distance = calculate_distance(
                    float(assignment.driver_lat),
                    float(assignment.driver_lng),
                    float(assignment.buyer_lat),
                    float(assignment.buyer_lng)
                )
                # Estimer le temps (moyenne 40 km/h)
                driver_to_buyer_time = (driver_to_buyer_distance / 40) * 60  # en minutes
            
            return JsonResponse({
                'success': True,
                'driver': {
                    'lat': float(assignment.driver_lat) if assignment.driver_lat else None,
                    'lng': float(assignment.driver_lng) if assignment.driver_lng else None,
                },
                'buyer': {
                    'lat': float(assignment.buyer_lat) if assignment.buyer_lat else None,
                    'lng': float(assignment.buyer_lng) if assignment.buyer_lng else None,
                },
                'seller': {
                    'lat': float(assignment.seller_lat) if assignment.seller_lat else None,
                    'lng': float(assignment.seller_lng) if assignment.seller_lng else None,
                },
                'distance_km': round(driver_to_buyer_distance, 2) if driver_to_buyer_distance else None,
                'estimated_time_minutes': round(driver_to_buyer_time, 0) if driver_to_buyer_time else None,
                'status': assignment.status,
            })
        
        except DeliveryAssignment.DoesNotExist:
            return JsonResponse({'error': 'Livraison non trouvée'}, status=404)
    
    return JsonResponse({'error': 'Méthode GET requise'}, status=405)


def calculate_distance(lat1, lng1, lat2, lng2):
    """Calcule la distance en km entre 2 points GPS (formule de Haversine)"""
    from math import radians, cos, sin, asin, sqrt
    
    lon1, lat1, lon2, lat2 = map(radians, [lng1, lat1, lng2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6371 * c
    return km
    def approve_transfer(self, request, pk=None):
        transaction = self.get_object()
        if transaction.status != 'pending' or transaction.type != 'transfer':
            return Response({'error': 'Invalid transaction'}, status=status.HTTP_400_BAD_REQUEST)
        sender_wallet = Wallet.objects.get(user=transaction.sender)
        receiver_wallet = Wallet.objects.get(user=transaction.receiver)
        if sender_wallet.balance < transaction.amount:
            return Response({'error': 'Insufficient balance'}, status=status.HTTP_400_BAD_REQUEST)
        sender_wallet.balance -= transaction.amount
        receiver_wallet.balance += transaction.amount
        sender_wallet.save()
        receiver_wallet.save()
        transaction.status = 'approved'
        transaction.save()
        return Response({'message': 'Transfer approved'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def reject_transfer(self, request, pk=None):
        transaction = self.get_object()
        if transaction.status != 'pending':
            return Response({'error': 'Transaction not pending'}, status=status.HTTP_400_BAD_REQUEST)
        transaction.status = 'rejected'
        transaction.save()
        return Response({'message': 'Transfer rejected'}, status=status.HTTP_200_OK)


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'])
    def recharge(self, request):
        if not hasattr(request.user, 'agent') or not request.user.agent.is_active:
            return Response({'error': 'Not an active agent'}, status=status.HTTP_403_FORBIDDEN)
        amount = request.data.get('amount')
        user_id = request.data.get('user_id')
        if not amount or not user_id:
            return Response({'error': 'Amount and user_id required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        agent_wallet = Wallet.objects.get(user=request.user)
        if agent_wallet.balance < float(amount):
            return Response({'error': 'Insufficient balance in agent wallet'}, status=status.HTTP_400_BAD_REQUEST)
        user_wallet = Wallet.objects.get(user=user)
        agent_wallet.balance -= float(amount)
        user_wallet.balance += float(amount)
        agent_wallet.save()
        user_wallet.save()
        Transaction.objects.create(
            sender=request.user,
            receiver=user,
            amount=amount,
            type='recharge',
            status='approved'
        )
        return Response({'message': 'Recharge successful'}, status=status.HTTP_200_OK)


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        order = self.get_object()
        if order.status != 'pending':
            return Response({'error': 'Order already paid'}, status=status.HTTP_400_BAD_REQUEST)
        order.status = 'paid'
        order.save()
        return Response({'status': 'paid'})


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated]


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]


class DeliveryEmployeeViewSet(viewsets.ModelViewSet):
    queryset = DeliveryEmployee.objects.all()
    serializer_class = DeliveryEmployeeSerializer
    permission_classes = [permissions.IsAdminUser]


class DeliveryAssignmentViewSet(viewsets.ModelViewSet):
    queryset = DeliveryAssignment.objects.all()
    serializer_class = DeliveryAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['status', 'assigned_at', 'delivered_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        employee_id = self.request.query_params.get('employee')
        status_values = self.request.query_params.get('status')

        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if status_values:
            statuses = [value.strip() for value in status_values.split(',') if value.strip()]
            queryset = queryset.filter(status__in=statuses)

        return queryset

    @action(detail=True, methods=['post'])
    def update_location(self, request, pk=None):
        """Met à jour la position GPS du livreur"""
        assignment = self.get_object()

        # Vérifier que l'utilisateur est le livreur assigné ou un admin
        if not (request.user == assignment.employee.user or request.user.is_staff):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        location_name = request.data.get('location_name')

        if not latitude or not longitude:
            return Response({'error': 'Latitude and longitude required'}, status=status.HTTP_400_BAD_REQUEST)

        update_delivery_tracking(
            assignment=assignment,
            latitude=latitude,
            longitude=longitude,
            location_name=location_name,
            status_update=f"Position mise à jour: {location_name or f'{latitude}, {longitude}'}"
        )

        return Response({'status': 'Location updated'})

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Met à jour le statut de livraison"""
        assignment = self.get_object()

        # Vérifier que l'utilisateur est le livreur assigné ou un admin
        if not (request.user == assignment.employee.user or request.user.is_staff):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        new_status = request.data.get('status')
        delivery_notes = request.data.get('delivery_notes', '')

        if new_status not in dict(DeliveryAssignment.status_choices):
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        old_status = assignment.status
        assignment.status = new_status
        if delivery_notes:
            assignment.delivery_notes = delivery_notes

        # Gestion des timestamps selon le statut
        if new_status == 'picked_up' and not assignment.picked_up_at:
            assignment.picked_up_at = timezone.now()
        elif new_status == 'delivered' and not assignment.delivered_at:
            assignment.delivered_at = timezone.now()
            assignment.actual_delivery_time = timezone.now()
            # Mettre à jour les statistiques du livreur
            assignment.employee.total_deliveries += 1
            assignment.employee.successful_deliveries += 1
            assignment.employee.save()

        assignment.save()

        # Créer un tracking et notifications
        status_messages = {
            'picked_up': 'Commande récupérée par le livreur',
            'in_transit': 'Commande en cours de livraison',
            'arrived': 'Livreur arrivé à destination',
            'delivered': 'Commande livrée avec succès',
            'failed': 'Échec de livraison',
        }

        update_delivery_tracking(
            assignment=assignment,
            status_update=status_messages.get(new_status, f'Statut: {assignment.get_status_display()}')
        )

        return Response({'status': f'Status updated to {new_status}'})

    @action(detail=True, methods=['get'])
    def tracking(self, request, pk=None):
        """Obtenir l'historique de suivi de la livraison"""
        assignment = self.get_object()

        # Vérifier que l'utilisateur est le client, le livreur ou un admin
        if not (request.user == assignment.order.buyer or
                request.user == assignment.employee.user or
                request.user.is_staff):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        tracking_data = DeliveryTracking.objects.filter(assignment=assignment).order_by('-timestamp')
        data = [{
            'timestamp': t.timestamp,
            'status_update': t.status_update,
            'latitude': t.latitude,
            'longitude': t.longitude,
            'location_name': t.location_name,
            'estimated_eta': t.estimated_eta
        } for t in tracking_data]

        return Response(data)

    @action(detail=True, methods=['get'])
    def notifications(self, request, pk=None):
        """Obtenir les notifications de livraison"""
        assignment = self.get_object()

        # Vérifier que l'utilisateur est le client ou le livreur
        if not (request.user == assignment.order.buyer or request.user == assignment.employee.user):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        notifications = DeliveryNotification.objects.filter(
            assignment=assignment,
            recipient=request.user
        ).order_by('-created_at')

        data = [{
            'id': n.id,
            'type': n.notification_type,
            'title': n.title,
            'message': n.message,
            'is_read': n.is_read,
            'created_at': n.created_at
        } for n in notifications]

        return Response(data)


@login_required
def my_shop(request):
    """Vue pour que les vendeurs gèrent leur boutique et leurs produits"""
    # Vérifier que l'utilisateur est vendeur ou admin
    if not (request.user.is_seller or request.user.is_staff):
        messages.error(request, 'Vous n\'avez pas accès à cette page.')
        return redirect('profile')

    # Récupérer ou créer la boutique de l'utilisateur
    shop, created = Shop.objects.get_or_create(
        owner=request.user,
        defaults={'name': f'Boutique {request.user.username}'}
    )

    # Récupérer les produits de la boutique
    products = Product.objects.filter(shop=shop).select_related('category').prefetch_related('images').order_by('-created_at')

    # Inclure les produits copiés (reseller) si existants
    reseller_entries = ResellerProduct.objects.filter(seller=request.user, status='active').select_related('original_product__category').prefetch_related('original_product__images')
    reseller_products = []
    for rp in reseller_entries:
        # Utiliser la copie locale si elle existe, sinon montrer le produit original
        prod = rp.copied_product if rp.copied_product else rp.original_product
        setattr(prod, 'reseller_entry', rp)
        setattr(prod, 'is_reseller_copy', True)
        reseller_products.append(prod)
    # Fusionner en évitant les doublons
    combined_products = list(products) + [p for p in reseller_products if p not in products]

    # Statistiques de la boutique
    total_products = len(combined_products)
    active_products = sum(1 for p in combined_products if p.quantity > 0)
    total_sales = OrderItem.objects.filter(product__shop=shop).aggregate(
        total=Sum('price_ht', field='price_ht * quantity')
    )['total'] or 0

    # Récupérer les commandes récentes pour cette boutique
    recent_orders = Order.objects.filter(
        items__product__shop=shop
    ).distinct().select_related('buyer').order_by('-created_at')[:10]

    return render(request, 'marketplace/my_shop.html', {
        'shop': shop,
        'products': combined_products,
        'total_products': total_products,
        'active_products': active_products,
        'total_sales': total_sales,
        'recent_orders': recent_orders,
    })


class ReturnRequestViewSet(viewsets.ModelViewSet):
    queryset = ReturnRequest.objects.all()
    serializer_class = ReturnRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Filtrer selon le rôle de l'utilisateur"""
        user = self.request.user
        if user.is_staff:
            return ReturnRequest.objects.all()
        elif hasattr(user, 'deliveryemployee'):
            # Les livreurs voient les retours de leurs livraisons
            return ReturnRequest.objects.filter(
                order__deliveryassignment__employee__user=user
            )
        else:
            # Les clients voient leurs propres demandes
            return ReturnRequest.objects.filter(customer=user)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approuver une demande de retour (admin seulement)"""
        if not request.user.is_staff:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        return_request = self.get_object()
        return_request.approve_return()
        return Response({'status': 'Return request approved'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Rejeter une demande de retour (admin seulement)"""
        if not request.user.is_staff:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        return_request = self.get_object()
        return_request.reject_return()
        return Response({'status': 'Return request rejected'})

    @action(detail=True, methods=['post'])
    def process_refund(self, request, pk=None):
        """Traiter le remboursement (admin seulement)"""
        if not request.user.is_staff:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        return_request = self.get_object()
        amount = request.data.get('amount')

        if amount:
            return_request.process_refund(amount)
        else:
            return_request.process_refund()

        return Response({'status': 'Refund processed'})


class AdminViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAdminUser]

    @action(detail=False, methods=['post'])
    def add_money(self, request):
        user_id = request.data.get('user_id')
        amount = request.data.get('amount')
        wallet = get_object_or_404(Wallet, user_id=user_id)
        wallet.total += amount
        wallet.save()
        Transaction.objects.create(user_id=user_id, amount=amount, type='admin_credit')
        return Response({'status': 'Money added'})

    @action(detail=False, methods=['post'])
    def authorize_transfer(self, request):
        user_id = request.data.get('user_id')
        wallet = get_object_or_404(Wallet, user_id=user_id)
        wallet.can_transfer = True
        wallet.save()
        return Response({'status': 'Transfer authorized'})


# ==========================================
# CONTRÔLE SYSTÈME - Gestion Mots de Passe
# ==========================================

@login_required
@user_passes_test(lambda u: u.is_staff)
def system_control_panel(request):
    """
    Panneau de contrôle système pour admin - Gestion des mots de passe et permissions
    """
    from .models import PasswordManagementPermission
    
    # Vérifier que l'utilisateur est super admin
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        messages.error(request, "Accès refusé. Seul le super admin peut accéder au contrôle système.")
        return redirect('profile')
    
    # Récupérer tous les utilisateurs pour affichage du contrôle système
    all_users = User.objects.exclude(id=request.user.id).order_by('username')
    
    # Récupérer tous les utilisateurs avec leurs portefeuilles et produits
    all_users_with_wallets = []
    for user in all_users:
        try:
            wallet = Wallet.objects.get(user=user)
        except Wallet.DoesNotExist:
            wallet = Wallet.objects.create(user=user, balance=Decimal('0.00'))
        
        # Récupérer les produits du vendeur (si c'est un vendeur)
        user_products = []
        if user.is_seller:
            user_products = list(Product.objects.filter(shop__owner=user).order_by('-created_at')[:5])  # Limiter à 5 produits récents
        
        all_users_with_wallets.append({
            'user': user,
            'wallet': wallet,
            'products': user_products
        })
    
    # Récupérer les admins secondaires (include inactifs aussi)
    secondary_admins = User.objects.filter(is_staff=True, is_superuser=False).order_by('username')
    
    # Récupérer les permissions avec les admins
    admin_permissions = []
    for admin in secondary_admins:
        try:
            perm = PasswordManagementPermission.objects.get(admin=admin)
        except PasswordManagementPermission.DoesNotExist:
            perm = PasswordManagementPermission.objects.create(admin=admin)
        admin_permissions.append((admin, perm))
    
    # Traiter les actions
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # 1. Modifier le mot de passe d'un utilisateur
        if action == 'change_user_password':
            user_id = request.POST.get('user_id')
            new_password = request.POST.get('new_password')
            user_obj = get_object_or_404(User, id=user_id)
            user_obj.set_password(new_password)
            user_obj.save()
            messages.success(request, f"Mot de passe de {user_obj.username} modifié avec succès.")
        
        # 4. Modifier le solde d'un utilisateur
        elif action == 'change_user_balance':
            user_id = request.POST.get('user_id')
            new_balance = Decimal(request.POST.get('new_balance', '0'))
            balance_reason = request.POST.get('balance_reason', '')
            
            user_obj = get_object_or_404(User, id=user_id)
            wallet, created = Wallet.objects.get_or_create(user=user_obj)
            
            old_balance = wallet.balance
            wallet.balance = new_balance
            wallet.save()
            
            # Créer un audit log pour la modification de solde
            AuditLog.objects.create(
                user=request.user,
                action='MODIFICATION_SOLDE',
                details=f"Solde de {user_obj.username} modifié de {old_balance} à {new_balance} HTG. Raison: {balance_reason}",
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            messages.success(request, f"Solde de {user_obj.username} modifié avec succès de {old_balance} à {new_balance} HTG.")
        
        # 2. Modifier les permissions d'un admin secondaire
        elif action == 'update_admin_permission':
            admin_id = request.POST.get('admin_id')
            can_view = request.POST.get('can_view_passwords') == 'on'
            can_change = request.POST.get('can_change_passwords') == 'on'
            can_manage = request.POST.get('can_manage_other_admins') == 'on'
            
            admin_obj = get_object_or_404(User, id=admin_id)
            perm, created = PasswordManagementPermission.objects.get_or_create(admin=admin_obj)
            perm.can_view_passwords = can_view
            perm.can_change_passwords = can_change
            perm.can_manage_other_admins = can_manage
            perm.updated_by = request.user
            perm.save()
            messages.success(request, f"Permissions de {admin_obj.username} mises à jour.")
        
        # 3. Créer un nouvel admin secondaire
        elif action == 'create_secondary_admin':
            username = request.POST.get('username').strip()
            email = request.POST.get('email').strip()
            first_name = request.POST.get('first_name').strip()
            last_name = request.POST.get('last_name').strip()
            password = request.POST.get('password')
            password_confirm = request.POST.get('password_confirm')
            
            # Validation
            if not username or len(username) < 3:
                messages.error(request, "Le nom d'utilisateur doit contenir au moins 3 caractères.")
                return redirect('system_control_panel')
            
            if User.objects.filter(username=username).exists():
                messages.error(request, f"Le nom d'utilisateur '{username}' existe déjà.")
                return redirect('system_control_panel')
            
            if User.objects.filter(email=email).exists():
                messages.error(request, f"L'email '{email}' est déjà utilisé.")
                return redirect('system_control_panel')
            
            if password != password_confirm:
                messages.error(request, "Les mots de passe ne correspondent pas.")
                return redirect('system_control_panel')
            
            if len(password) < 8:
                messages.error(request, "Le mot de passe doit contenir au moins 8 caractères.")
                return redirect('system_control_panel')
            
            # Créer l'utilisateur admin secondaire
            new_admin = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_staff=True,
                is_superuser=False,
                role='admin_secondary'
            )
            
            # Créer les permissions par défaut (aucune permission)
            PasswordManagementPermission.objects.create(
                admin=new_admin,
                can_view_passwords=False,
                can_change_passwords=False,
                can_manage_other_admins=False,
                updated_by=request.user
            )
            
            messages.success(request, f"Administrateur secondaire '{username}' créé avec succès. Vous pouvez maintenant définir ses permissions.")
            return redirect('system_control_panel')

        # 4. Modifier manuellement les taux de change
        elif action == 'update_exchange_rate':
            usd_to_htg = request.POST.get('usd_to_htg', '').strip()
            usd_to_peso = request.POST.get('usd_to_peso', '').strip()
            eur_to_usd = request.POST.get('eur_to_usd', '').strip()

            try:
                usd_to_htg = Decimal(usd_to_htg)
                usd_to_peso = Decimal(usd_to_peso)
                eur_to_usd = Decimal(eur_to_usd)
            except (InvalidOperation, TypeError):
                messages.error(request, "Les valeurs du taux de change doivent être des nombres valides.")
                return redirect('system_control_panel')

            if usd_to_htg <= 0 or usd_to_peso <= 0 or eur_to_usd <= 0:
                messages.error(request, "Les taux de change doivent être des nombres strictement positifs.")
                return redirect('system_control_panel')

            usd_to_eur = Decimal('1') / eur_to_usd
            htg_to_peso = usd_to_peso / usd_to_htg if usd_to_htg else Decimal('0')
            eur_to_htg = usd_to_htg / usd_to_eur if usd_to_eur else Decimal('0')
            eur_to_peso = usd_to_peso / usd_to_eur if usd_to_eur else Decimal('0')

            ExchangeRate.objects.filter(is_active=True).update(is_active=False)
            ExchangeRate.objects.create(
                usd_to_htg=usd_to_htg,
                usd_to_peso=usd_to_peso,
                htg_to_peso=htg_to_peso,
                eur_to_usd=eur_to_usd,
                eur_to_htg=eur_to_htg,
                eur_to_peso=eur_to_peso,
                is_active=True,
            )

            messages.success(request, "Les taux de change ont été mis à jour manuellement avec succès.")
            return redirect('system_control_panel')
    
    active_rate = ExchangeRate.objects.filter(is_active=True).order_by('-created_at').first()

    context = {
        'all_users_with_wallets': all_users_with_wallets,
        'secondary_admins': secondary_admins,
        'admin_permissions': admin_permissions,
        'active_rate': active_rate,
    }
    return render(request, 'marketplace/system_control_panel.html', context)


@login_required
@user_passes_test(lambda u: u.is_staff)
def refresh_exchange_rates(request):
    """Actualise les taux de change depuis l'API depuis le contrôle système."""
    if not (request.user.is_superuser or request.user.role == 'super_admin'):
        messages.error(request, "Accès refusé. Seul le super admin peut actualiser le taux de change.")
        return redirect('profile')

    if request.method != 'POST':
        return redirect('system_control_panel')

    rate = fetch_exchange_rates_from_api()
    if rate:
        messages.success(request, f"Taux de change actualisé : 1 USD = {rate.usd_to_htg} HTG, {rate.usd_to_peso} DOP, 1 EUR = {rate.eur_to_usd} USD.")
    else:
        messages.error(request, "Impossible de récupérer les taux de change depuis l'API. Le système conservera les taux existants.")
    return redirect('system_control_panel')


@login_required
@user_passes_test(lambda u: u.is_staff)
def security_dashboard_api(request):
    """API endpoint pour le tableau de bord cybersécurité intelligent en temps réel"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    try:
        # Récupérer les paramètres de filtrage
        time_filter = request.GET.get('time_filter', '24h')  # 1h, 24h, 7d

        # Déterminer la limite de temps
        from datetime import timedelta
        now = timezone.now()
        if time_filter == '1h':
            start_time = now - timedelta(hours=1)
        elif time_filter == '7d':
            start_time = now - timedelta(days=7)
        else:  # 24h par défaut
            start_time = now - timedelta(hours=24)

        # 1. Événements par minute (dernière heure)
        from django.db.models import Count, Avg, Sum
        from django.db.models.functions import TruncMinute

        last_hour = now - timedelta(hours=1)
        events_by_minute = list(
            SecurityEvent.objects.filter(created_at__gte=last_hour)
            .annotate(minute=TruncMinute('created_at'))
            .values('minute')
            .annotate(count=Count('id'))
            .order_by('minute')
        )

        # 2. Surveillance des ports
        ports_data = list(
            PortMonitoring.objects.all()
            .values('port', 'is_open', 'traffic_count', 'suspicious_activity', 'risk_level', 'blocked_connections')
        )

        # 3. Analyse IA des menaces
        ai_analysis = AIThreatAnalysis.objects.first()
        if not ai_analysis:
            ai_analysis = AIThreatAnalysis.objects.create()
        ai_data = {
            'threat_score': ai_analysis.threat_score,
            'threat_level': ai_analysis.threat_level,
            'bot_detections': ai_analysis.bot_detections,
            'brute_force_attempts': ai_analysis.brute_force_attempts,
            'sql_injection_attempts': ai_analysis.sql_injection_attempts,
            'xss_attempts': ai_analysis.xss_attempts,
            'ai_confidence': ai_analysis.ai_confidence,
            'last_analysis': ai_analysis.last_analysis.strftime('%H:%M:%S') if ai_analysis.last_analysis else None,
        }

        # 4. Événements honeypot récents
        honeypot_events = list(
            HoneypotEvent.objects.filter(created_at__gte=start_time)
            .order_by('-created_at')[:10]
            .values('event_type', 'source_ip', 'attempted_username', 'created_at', 'alerted')
        )

        # 5. Alertes de sécurité actives
        active_alerts = list(
            SecurityAlert.objects.filter(resolved=False)
            .order_by('-created_at')[:15]
            .values('id', 'alert_type', 'priority', 'title', 'description', 'source_ip', 'created_at')
        )

        # 6. Logs temps réel récents
        recent_logs = list(
            SecurityLog.objects.filter(created_at__gte=start_time)
            .order_by('-created_at')[:20]
            .values('level', 'component', 'message', 'source_ip', 'created_at')
        )

        # 7. Métriques temps réel
        latest_metrics = SecurityMetrics.objects.order_by('-timestamp').first()
        metrics_data = {
            'active_connections': latest_metrics.active_connections if latest_metrics else 0,
            'requests_per_minute': latest_metrics.requests_per_minute if latest_metrics else 0.0,
            'blocked_requests': latest_metrics.blocked_requests if latest_metrics else 0,
            'suspicious_ips': latest_metrics.suspicious_ips if latest_metrics else 0,
            'ai_threat_score': latest_metrics.ai_threat_score if latest_metrics else 0.0,
            'bot_detections': latest_metrics.bot_detections if latest_metrics else 0,
            'anomaly_detections': latest_metrics.anomaly_detections if latest_metrics else 0,
            'network_traffic': latest_metrics.network_traffic if latest_metrics else 0,
            'port_scans_detected': latest_metrics.port_scans_detected if latest_metrics else 0,
            'cpu_usage': latest_metrics.cpu_usage if latest_metrics else 0.0,
            'memory_usage': latest_metrics.memory_usage if latest_metrics else 0.0,
            'disk_usage': latest_metrics.disk_usage if latest_metrics else 0.0,
            'active_alerts': latest_metrics.active_alerts if latest_metrics else 0,
            'resolved_alerts_today': latest_metrics.resolved_alerts_today if latest_metrics else 0,
            'honeypot_triggers': latest_metrics.honeypot_triggers if latest_metrics else 0,
            'timestamp': latest_metrics.timestamp.strftime('%H:%M:%S') if latest_metrics else None,
        }

        # 8. Types d'incidents
        incident_types = list(
            SecurityEvent.objects.filter(created_at__gte=start_time)
            .values('event_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        # 9. Top IPs suspectes
        suspicious_ips = list(
            SecurityEvent.objects.filter(
                created_at__gte=start_time,
                event_type__in=['http_4xx', 'http_5xx', 'admin_access', 'brute_force', 'malicious_payload']
            )
            .values('source_ip')
            .annotate(count=Count('id'))
            .order_by('-count')[:15]
        )

        # 10. Alertes critiques récentes
        critical_alerts = list(
            SecurityIncident.objects.filter(severity='critical', resolved=False)
            .order_by('-created_at')[:8]
            .values('id', 'incident_type', 'severity', 'description', 'source_ip', 'created_at')
        )

        # 11. Statistiques globales étendues
        total_events = SecurityEvent.objects.filter(created_at__gte=start_time).count()
        errors_4xx = SecurityEvent.objects.filter(created_at__gte=start_time, event_type='http_4xx').count()
        errors_5xx = SecurityEvent.objects.filter(created_at__gte=start_time, event_type='http_5xx').count()
        failed_logins = SecurityEvent.objects.filter(created_at__gte=start_time, event_type='login_failed').count()
        brute_force = SecurityEvent.objects.filter(created_at__gte=start_time, event_type='brute_force').count()
        sql_injections = SecurityEvent.objects.filter(created_at__gte=start_time, event_type='malicious_payload').count()

        # 12. Utilisateurs connectés
        total_users_online = User.objects.filter(last_login__gte=now - timedelta(minutes=5)).count()

        # 13. Temps de réponse moyen
        avg_response_time = SecurityEvent.objects.filter(
            created_at__gte=start_time,
            response_time_ms__isnull=False
        ).aggregate(avg=Avg('response_time_ms'))['avg'] or 0

        # 14. IPs bloquées et autres stats
        blocked_ips = IPBlocklist.objects.count()
        honeypot_triggers = HoneypotEvent.objects.filter(created_at__gte=start_time).count()
        active_security_alerts = SecurityAlert.objects.filter(resolved=False).count()

        # 15. Données pour les visualisations 3D
        geo_data = list(
            SecurityEvent.objects.filter(
                created_at__gte=start_time,
                source_ip__isnull=False
            )
            .values('source_ip')
            .annotate(count=Count('id'))
            .order_by('-count')[:20]
        )

        system_settings = SystemSettings.objects.first()

        # Structure de données complète
        data = {
            # Données temporelles
            'events_by_minute': [
                {
                    'time': e['minute'].strftime('%H:%M') if e['minute'] else 'N/A',
                    'count': e['count']
                }
                for e in events_by_minute
            ],

            # Surveillance des ports
            'ports_monitoring': ports_data,

            # Analyse IA
            'ai_analysis': ai_data,

            # Événements honeypot
            'honeypot_events': [
                {
                    'type': dict(HoneypotEvent.EVENT_TYPE_CHOICES).get(e['event_type'], 'Inconnu'),
                    'ip': e['source_ip'],
                    'username': e['attempted_username'],
                    'time': e['created_at'].strftime('%H:%M:%S'),
                    'alerted': e['alerted']
                }
                for e in honeypot_events
            ],

            # Alertes de sécurité
            'security_alerts': [
                {
                    'id': a['id'],
                    'type': dict(SecurityAlert.ALERT_TYPE_CHOICES).get(a['alert_type'], 'Inconnu'),
                    'priority': a['priority'],
                    'title': a['title'],
                    'description': a['description'],
                    'ip': a['source_ip'],
                    'time': a['created_at'].strftime('%H:%M:%S')
                }
                for a in active_alerts
            ],

            # Logs temps réel
            'recent_logs': [
                {
                    'level': l['level'],
                    'component': l['component'],
                    'message': l['message'][:100] + '...' if len(l['message']) > 100 else l['message'],
                    'ip': l['source_ip'],
                    'time': l['created_at'].strftime('%H:%M:%S')
                }
                for l in recent_logs
            ],

            # Métriques temps réel
            'live_metrics': metrics_data,

            # Données classiques
            'incident_types': [
                {
                    'type': dict(SecurityEvent.EVENT_TYPE_CHOICES).get(e['event_type'], 'Inconnu'),
                    'count': e['count']
                }
                for e in incident_types
            ],
            'suspicious_ips': [
                {
                    'ip': e['source_ip'] or 'Unknown',
                    'count': e['count'],
                    'is_blocked': IPBlocklist.objects.filter(ip_address=e['source_ip']).exists() if e['source_ip'] else False
                }
                for e in suspicious_ips
            ],
            'critical_alerts': [
                {
                    'id': a['id'],
                    'type': dict(SecurityIncident.INCIDENT_TYPE_CHOICES).get(a['incident_type'], 'Inconnu'),
                    'description': a['description'],
                    'ip': a['source_ip'],
                    'time': a['created_at'].strftime('%H:%M:%S')
                }
                for a in critical_alerts
            ],

            # Statistiques étendues
            'stats': {
                'total_events': total_events,
                'errors_4xx': errors_4xx,
                'errors_5xx': errors_5xx,
                'failed_logins': failed_logins,
                'brute_force_attempts': brute_force,
                'sql_injection_attempts': sql_injections,
                'avg_response_time': round(avg_response_time, 2),
                'users_online': total_users_online,
                'blocked_ips': blocked_ips,
                'honeypot_triggers': honeypot_triggers,
                'active_security_alerts': active_security_alerts,
            },

            # Données géographiques pour visualisations
            'geo_attack_data': [
                {
                    'ip': g['source_ip'],
                    'count': g['count']
                }
                for g in geo_data
            ],

            # État du système
            'system_status': {
                'emergency_lockdown': system_settings.emergency_lockdown if system_settings else False,
                'cybersecurity_enabled': system_settings.enable_cybersecurity if system_settings else False,
                'last_update': now.strftime('%H:%M:%S'),
            }
        }

        return JsonResponse(data)
    except Exception as error:
        logger.exception('Erreur API security_dashboard_api')
        return JsonResponse({'error': 'Erreur interne du dashboard cybersécurité. Voir les logs.'}, status=500)


# ==========================================
# GESTION DES CONFIRMATIONS DE LIVRAISON
# ==========================================

@login_required
def confirm_delivery_buyer(request, order_id):
    """L'acheteur confirme qu'il a reçu sa commande"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    
    if order.buyer_confirmed_delivery:
        messages.warning(request, "Vous avez déjà confirmé la réception de cette commande.")
        return redirect('profile')
    
    if request.method == 'POST':
        order.buyer_confirmed_delivery = True
        order.buyer_confirmed_at = timezone.now()
        order.status = 'delivered'
        order.date_reception_confirmee = timezone.now()
        order.save()
        
        # Envoyer une notification à l'admin
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            # Créer un message privé d'alerte
            conversation, created = PrivateConversation.objects.get_or_create(
                user1_id=min(request.user.id, admin_user.id),
                user2_id=max(request.user.id, admin_user.id)
            )
            
            msg = PrivateMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                receiver=admin_user,
                content=f"🎉 Commande #{order.id} confirmée comme livrée par l'acheteur {order.buyer.username}. Montant: {order.total_amount} HTG"
            )
            
            # Créer une notification persistante avec sonnerie
            notification = PersistentNotification.objects.create(
                recipient=admin_user,
                title="✅ Confirmation de livraison",
                message=f"Commande #{order.id} de {order.buyer.username} a été confirmée livrée. Montant: {order.total_amount} HTG",
                notification_type='delivery_confirmed',
                sound_interval_minutes=1  # Sonner chaque minute
            )
        
        messages.success(request, "✅ Merci! Vous avez confirmé la réception de votre commande.")
        return redirect('profile')
    
    return render(request, 'marketplace/confirm_delivery.html', {'order': order})


def confirm_delivery_driver(request, assignment_id):
    """Le livreur confirme qu'il a livré la commande"""
    assignment = get_object_or_404(DeliveryAssignment, id=assignment_id, driver=request.user)
    
    if assignment.driver_confirmed_delivery:
        messages.warning(request, "Vous avez déjà confirmé la livraison de cette commande.")
        return redirect('driver_dashboard')
    
    if request.method == 'POST':
        assignment.driver_confirmed_delivery = True
        assignment.driver_confirmed_at = timezone.now()
        assignment.status = 'delivered'
        assignment.save()
        
        # Marquer la commande comme prête pour confirmation acheteur
        order = assignment.order
        order.status = 'ready_for_buyer_confirmation'
        order.save()
        
        # Envoyer une notification à l'admin
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            # Créer un message privé d'alerte
            conversation, created = PrivateConversation.objects.get_or_create(
                user1_id=min(request.user.id, admin_user.id),
                user2_id=max(request.user.id, admin_user.id)
            )
            
            msg = PrivateMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                receiver=admin_user,
                content=f"🚚 Livreur {request.user.username} confirme avoir livré la commande #{order.id} à {order.buyer.username}. Montant: {order.total_amount} HTG"
            )
            
            # Créer une notification persistante avec sonnerie
            notification = PersistentNotification.objects.create(
                recipient=admin_user,
                title="🚚 Livraison effectuée",
                message=f"Livreur {request.user.username} confirme la livraison de commande #{order.id} à {order.buyer.username}. Montant: {order.total_amount} HTG",
                notification_type='delivery_completed',
                sound_interval_minutes=1  # Sonner chaque minute
            )
        
        # Notifier l'acheteur aussi
        buyer_notification = PersistentNotification.objects.create(
            recipient=order.buyer,
            title="📦 Commande livrée",
            message=f"Votre commande #{order.id} a été livrée. Veuillez confirmer sa réception.",
            notification_type='delivery_ready',
            sound_interval_minutes=1
        )
        
        messages.success(request, "🚚 Merci! Vous avez confirmé la livraison de cette commande.")
        return redirect('driver_dashboard')
    
    return render(request, 'marketplace/confirm_delivery_driver.html', {'assignment': assignment})


# ==========================================
# NOTIFICATIONS PERSISTANTES AVEC SONNERIE
# ==========================================
# CONTRÔLE SYSTÈME - Gestion Mots de Passe
# ==========================================

# ------------------------------
# NOTIFICATIONS PERSISTANTES AVEC SONNERIE
# ------------------------------

@login_required
def get_persistent_notifications_api(request):
    """API pour récupérer les notifications persistantes non lues"""
    if request.method == 'GET':
        notifications = PersistentNotification.objects.filter(
            recipient=request.user,
            is_read=False
        ).order_by('-created_at')

        notifications_data = []
        for notification in notifications:
            notifications_data.append({
                'id': notification.id,
                'title': notification.title,
                'message': notification.message,
                'notification_type': notification.notification_type,
                'created_at': notification.created_at.isoformat(),
                'should_sound': notification.should_sound(),
                'sound_interval_minutes': notification.sound_interval_minutes,
                'related_assignment_id': notification.related_assignment.id if notification.related_assignment else None,
            })

        return JsonResponse({
            'notifications': notifications_data,
            'count': len(notifications_data)
        })

    return JsonResponse({'error': 'Méthode GET requise'}, status=405)


@login_required
def mark_persistent_notification_read_api(request, notification_id):
    """API pour marquer une notification persistante comme lue"""
    if request.method == 'POST':
        try:
            notification = PersistentNotification.objects.get(
                id=notification_id,
                recipient=request.user
            )
            notification.mark_as_read()

            return JsonResponse({
                'success': True,
                'message': 'Notification marquée comme lue'
            })

        except PersistentNotification.DoesNotExist:
            return JsonResponse({'error': 'Notification non trouvée'}, status=404)

    return JsonResponse({'error': 'Méthode POST requise'}, status=405)


@login_required
def check_notifications_sound_api(request):
    """API pour vérifier quelles notifications doivent sonner maintenant"""
    if request.method == 'GET':
        notifications = PersistentNotification.objects.filter(
            recipient=request.user,
            is_read=False
        )

        sound_data = []
        for notification in notifications:
            if notification.should_sound():
                sound_data.append({
                    'id': notification.id,
                    'title': notification.title,
                    'message': notification.message[:100] + '...' if len(notification.message) > 100 else notification.message,
                    'notification_type': notification.notification_type,
                })
                # Mettre à jour le timestamp du dernier son
                notification.update_sound_timestamp()

        return JsonResponse({
            'notifications_to_sound': sound_data,
            'count': len(sound_data)
        })

    return JsonResponse({'error': 'Méthode GET requise'}, status=405)


@login_required
def persistent_notifications_page(request):
    """Page pour afficher toutes les notifications persistantes de l'utilisateur"""
    notifications = PersistentNotification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')

    # Quand l'utilisateur ouvre la page, considérer que les notifications visibles ont été consultées.
    unread_notifications = notifications.filter(is_read=False)
    if unread_notifications.exists():
        unread_notifications.update(is_read=True, read_at=timezone.now())
        notifications = notifications.order_by('-created_at')

    unread_count = notifications.filter(is_read=False).count()

    return render(request, 'marketplace/persistent_notifications.html', {
        'notifications': notifications,
        'unread_count': unread_count,
    })


@login_required
def mark_all_persistent_notifications_read_api(request):
    """API pour marquer toutes les notifications persistantes comme lues"""
    if request.method == 'POST':
        PersistentNotification.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )

        return JsonResponse({
            'success': True,
            'message': 'Toutes les notifications ont été marquées comme lues'
        })

    return JsonResponse({'error': 'Méthode POST requise'}, status=405)


@login_required
@user_passes_test(lambda u: u.is_staff)
def view_user_password(request, user_id):
    """
    API pour voir le mot de passe masqué d'un utilisateur (remplacé par des points)
    Cette fonction n'affiche pas le mot de passe en clair mais une représentation masquée
    """
    from .models import PasswordManagementPermission
    
    # Vérifier les permissions
    try:
        perm = PasswordManagementPermission.objects.get(admin=request.user)
        if not perm.can_view_passwords:
            return JsonResponse({'error': 'Permission refusée'}, status=403)
    except PasswordManagementPermission.DoesNotExist:
        if not request.user.is_superuser:
            return JsonResponse({'error': 'Permission refusée'}, status=403)
    
    user_obj = get_object_or_404(User, id=user_id)
    # Retourner une représentation masquée (pour sécurité, on n'affiche pas le vrai mot de passe)
    return JsonResponse({
        'username': user_obj.username,
        'has_usable_password': user_obj.has_usable_password(),
        'last_password_change': user_obj.last_login,
    })


@login_required
def view_withdrawal_receipt(request, withdrawal_id):
    """Vue pour afficher le reçu de retrait approuvé"""
    from .models import WithdrawalRequest

    # Récupérer la demande de retrait approuvée
    withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id, status='approved')

    # Autoriser l'accès si l'utilisateur est le propriétaire, ou si c'est un staff/superuser
    # ou s'il dispose de la permission explicite `marketplace.view_withdrawalreceipt`.
    if withdrawal.user != request.user and not (
        request.user.is_staff or request.user.is_superuser or request.user.has_perm('marketplace.view_withdrawalreceipt')
    ):
        return HttpResponseForbidden('Permission refusée')

    # Générer le numéro de reçu si pas encore fait
    receipt_number = f"WR-{withdrawal.id}-{withdrawal.confirmed_at.strftime('%Y%m%d%H%M%S')}"
    if not withdrawal.receipt_generated:
        withdrawal.receipt_generated = True
        withdrawal.save(update_fields=['receipt_generated'])

    profile = getattr(withdrawal.user, 'profile', None)
    account_number = withdrawal.user.account_code or f"MSDI-{withdrawal.user.id:05d}"
    
    # Calculer les soldes avant et après retrait en se basant sur le solde actuel du portefeuille
    wallet = Wallet.objects.filter(user=withdrawal.user).first()
    previous_balance = None
    remaining_balance = None
    reduction_amount = Decimal('0.00')

    if wallet:
        if withdrawal.account_type == 'principal':
            remaining_balance = wallet.balance
        else:
            field_map = {
                'USD': 'commission_balance_usd',
                'HTG': 'commission_balance_htg',
                'DOP': 'commission_balance_peso',
                'EUR': 'commission_balance_eur',
            }
            field_name = field_map.get(withdrawal.currency.upper())
            if field_name:
                remaining_balance = getattr(wallet, field_name, Decimal('0.00'))

        if remaining_balance is not None:
            previous_balance = remaining_balance + withdrawal.amount

    context = {
        'withdrawal': withdrawal,
        'receipt_number': receipt_number,
        'confirmed_at': withdrawal.confirmed_at,
        'confirmed_by': withdrawal.confirmed_by,
        'profile': profile,
        'account_number': account_number,
        'client_id': account_number,
        'account_type_display': 'Principal' if withdrawal.account_type == 'principal' else 'Multi-appareils',
        'previous_balance': previous_balance,
        'remaining_balance': remaining_balance,
        'reduction_amount': reduction_amount,
        'security_pin': '********',
        'security_secondary': '********',
    }

    return render(request, 'marketplace/withdrawal_receipt.html', context)
