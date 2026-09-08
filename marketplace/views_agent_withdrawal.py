# Vue pour permettre aux agents de faire des retraits pour d'autres utilisateurs
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db import transaction as db_transaction
from django.db.models import Q
from decimal import Decimal, InvalidOperation
import json
import logging

from .models import User, Wallet, WithdrawalRequest, Profile, Transaction, WithdrawalTransaction, WithdrawalCommissionTier
from .business_logic import CommissionManager, get_system_admin_wallet

logger = logging.getLogger(__name__)


def is_agent(user):
    """Vérifier si l'utilisateur est un agent ou un admin principal"""
    return (
        user.is_agent or
        user.role == 'agent' or
        user.is_superuser or
        user.has_perm('marketplace.principal_admin_power')
    )


@login_required
def agent_withdrawal_dashboard(request):
    """Dashboard pour que les agents gèrent les retraits des utilisateurs"""
    
    # Vérifier que l'utilisateur est un agent
    if not is_agent(request.user):
        messages.error(request, "Vous n'avez pas accès à cette page.")
        return redirect('home')
    
    # Récupérer l'historique des retraits effectués par cet agent
    agent_withdrawals = WithdrawalRequest.objects.filter(
        processed_by=request.user
    ).order_by('-created_at')[:50]
    
    context = {
        'agent_withdrawals': agent_withdrawals,
        'total_withdrawals': agent_withdrawals.count(),
    }
    
    return render(request, 'marketplace/agent_withdrawal_dashboard.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def agent_process_withdrawal(request):
    """Permettre à un agent de traiter un retrait pour un utilisateur"""
    
    if not is_agent(request.user):
        return JsonResponse({'success': False, 'message': 'Accès refusé.'}, status=403)
    
    if request.method == 'GET':
        # Récupérer tous les utilisateurs (sauf l'agent lui-même)
        users = User.objects.filter(is_agent=False).order_by('username')[:100]
        CommissionManager.ensure_default_withdrawal_tiers()
        withdrawal_tiers = WithdrawalCommissionTier.objects.filter(active=True).order_by('currency', 'min_amount')
        context = {
            'users': users,
            'withdrawal_tiers_json': json.dumps([
                {
                    'currency': tier.currency,
                    'min_amount': str(tier.min_amount),
                    'max_amount': str(tier.max_amount),
                    'total_fee': str(tier.total_fee),
                    'system_fee': str(tier.system_fee),
                    'agent_fee': str(tier.agent_fee)
                }
                for tier in withdrawal_tiers
            ])
        }
        return render(request, 'marketplace/agent_process_withdrawal.html', context)
    
    # POST : Traiter le retrait
    user_id = request.POST.get('user_id')
    amount_str = request.POST.get('amount')
    currency = request.POST.get('currency', 'USD')
    account_type = request.POST.get('account_type', 'multidevice')
    
    # Validation des données
    if not all([user_id, amount_str]):
        messages.error(request, 'Tous les champs sont requis.')
        return redirect('agent_process_withdrawal')
    
    try:
        user = User.objects.get(id=user_id)
        amount = Decimal(amount_str)
    except (User.DoesNotExist, ValueError, InvalidOperation):
        messages.error(request, 'Utilisateur ou montant invalide.')
        return redirect('agent_process_withdrawal')
    
    if amount < Decimal('5.00'):
        messages.error(request, 'Le montant minimum de retrait est de 5 USD.')
        return redirect('agent_process_withdrawal')
    
    if currency not in ['USD', 'HTG', 'DOP', 'EUR']:
        messages.error(request, 'Devise invalide.')
        return redirect('agent_process_withdrawal')
    
    if account_type not in ['principal', 'multidevice']:
        messages.error(request, 'Type de compte invalide.')
        return redirect('agent_process_withdrawal')
    
    try:
        with db_transaction.atomic():
            # Récupérer le portefeuille de l'utilisateur
            wallet, _ = Wallet.objects.get_or_create(user=user)
            breakdown = CommissionManager.get_withdrawal_commission_breakdown(amount, currency)
            fee = breakdown['total_fee']
            system_fee = breakdown['system_fee']
            agent_fee = breakdown['agent_fee']
            
            # Vérifier le solde
            if account_type == 'principal':
                if currency != 'USD':
                    messages.error(request, 'Le compte principal ne supporte que USD.')
                    return redirect('agent_process_withdrawal')
                if wallet.balance < amount + fee:
                    messages.error(request, f"Solde insuffisant. Solde actuel: {wallet.balance} USD")
                    return redirect('agent_process_withdrawal')
                wallet.balance -= amount + fee
            elif account_type == 'multidevice':
                field_map = {
                    'USD': 'commission_balance_usd',
                    'HTG': 'commission_balance_htg',
                    'DOP': 'commission_balance_peso',
                    'EUR': 'commission_balance_eur',
                }
                field_name = field_map.get(currency.upper())
                if not field_name:
                    messages.error(request, 'Devise non supportée pour multi-device.')
                    return redirect('agent_process_withdrawal')
                
                current_balance = getattr(wallet, field_name)
                if current_balance < amount + fee:
                    messages.error(
                        request, 
                        f"Solde insuffisant pour couvrir le montant ({amount} {currency}) et les frais ({fee} {currency}). "
                        f"Solde actuel: {current_balance} {currency}"
                    )
                    return redirect('agent_process_withdrawal')
                setattr(wallet, field_name, current_balance - amount - fee)
            
            # Débiter l'argent
            wallet.save()
            
            # Créer la WithdrawalRequest
            withdrawal = WithdrawalRequest.objects.create(
                user=user,
                amount=amount,
                currency=currency,
                account_type=account_type,
                status='completed',  # Traité directement par l'agent
                amount_debited=True,
                processed_by=request.user,
                fee_total=fee,
                fee_system=system_fee,
                fee_agent=agent_fee,
                notes=f"Retrait traité par l'agent {request.user.username}"
            )
            
            # Ajouter les parts système et agent aux portefeuilles
            if fee > Decimal('0'):
                admin_wallet = get_system_admin_wallet()
                if admin_wallet and system_fee > Decimal('0'):
                    admin_field_map = {
                        'USD': 'commission_balance_usd',
                        'HTG': 'commission_balance_htg',
                        'DOP': 'commission_balance_peso',
                        'EUR': 'commission_balance_eur',
                    }
                    admin_field_name = admin_field_map.get(currency.upper())
                    if admin_field_name:
                        current_admin_balance = getattr(admin_wallet, admin_field_name)
                        setattr(admin_wallet, admin_field_name, current_admin_balance + system_fee)
                        admin_wallet.save(update_fields=[admin_field_name])
                        Transaction.objects.create(
                            sender=user,
                            receiver=admin_wallet.user,
                            type='withdrawal_system_commission',
                            amount=system_fee,
                            currency=currency,
                            status='approved'
                        )
                if agent_fee > Decimal('0'):
                    agent_wallet, _ = Wallet.objects.get_or_create(user=request.user)
                    agent_field_name = {
                        'USD': 'commission_balance_usd',
                        'HTG': 'commission_balance_htg',
                        'DOP': 'commission_balance_peso',
                        'EUR': 'commission_balance_eur',
                    }.get(currency.upper())
                    if agent_field_name:
                        current_agent_balance = getattr(agent_wallet, agent_field_name)
                        setattr(agent_wallet, agent_field_name, current_agent_balance + agent_fee)
                        agent_wallet.save(update_fields=[agent_field_name])
                        Transaction.objects.create(
                            sender=user,
                            receiver=request.user,
                            type='withdrawal_agent_commission',
                            amount=agent_fee,
                            currency=currency,
                            status='approved'
                        )
            
            # Créer une transaction de retrait et un enregistrement de retrait détaillé
            Transaction.objects.create(
                sender=user,
                receiver=request.user,
                type='withdrawal_agent',
                amount=amount,
                currency=currency,
                status='completed'
            )
            WithdrawalTransaction.objects.create(
                withdrawal_request=withdrawal,
                user=user,
                agent=request.user,
                amount=amount,
                currency=currency,
                account_type=account_type,
                fee_total=fee,
                fee_system=system_fee,
                fee_agent=agent_fee,
                status='completed'
            )
            
            messages.success(
                request,
                f"Retrait de {amount} {currency} traité avec succès pour {user.username}."
            )
            logger.info(f"Agent {request.user.username} a traité un retrait de {amount} {currency} pour {user.username}")
            
    except Exception as e:
        messages.error(request, f"Erreur lors du traitement du retrait: {str(e)}")
        logger.error(f"Erreur lors du retrait par agent: {str(e)}")
    
    return redirect('agent_withdrawal_dashboard')


@login_required
def agent_user_search(request):
    """API pour rechercher des utilisateurs par nom ou username"""
    
    if not is_agent(request.user):
        return JsonResponse({'error': 'Accès refusé'}, status=403)
    
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'users': []})
    
    users = User.objects.filter(
        is_agent=False
    ).filter(
        Q(account_code__icontains=query) |
        Q(username__icontains=query) | 
        Q(first_name__icontains=query) | 
        Q(last_name__icontains=query) |
        Q(email__icontains=query)
    )[:20]
    
    users_data = [
        {
            'id': user.id,
            'account_code': user.account_code,
            'username': user.username,
            'full_name': user.get_full_name() or user.username,
            'email': user.email,
        }
        for user in users
    ]
    
    return JsonResponse({'users': users_data})
