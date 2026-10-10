# Vue pour permettre aux agents de faire des retraits pour d'autres utilisateurs
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db import transaction as db_transaction
from django.db.models import F, Q
from django.utils import timezone
import logging

from .models import Agent, User, Wallet, WithdrawalRequest, Transaction, WithdrawalTransaction
from .business_logic import create_persistent_notification

logger = logging.getLogger(__name__)


def is_agent(user):
    """Vérifier si l'utilisateur est un agent ou un admin principal"""
    if user.is_superuser or user.has_perm('marketplace.principal_admin_power'):
        return True
    return (
        (user.is_agent or user.role == 'agent')
        and Agent.objects.filter(user=user, is_active=True).exists()
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
    """Permettre à un agent de finaliser une demande de retrait déjà débitée."""
    
    if not is_agent(request.user):
        return JsonResponse({'success': False, 'message': 'Accès refusé.'}, status=403)
    
    if request.method == 'GET':
        pending_withdrawals = WithdrawalRequest.objects.filter(
            status='pending',
            amount_debited=True,
        ).select_related('user').order_by('created_at')[:100]
        return render(request, 'marketplace/agent_process_withdrawal.html', {
            'pending_withdrawals': pending_withdrawals,
        })

    withdrawal_id = request.POST.get('withdrawal_id')
    if not withdrawal_id:
        messages.error(request, 'Sélectionnez une demande de retrait en attente.')
        return redirect('agent_process_withdrawal')
    try:
        withdrawal_id = int(withdrawal_id)
    except (TypeError, ValueError):
        messages.error(request, 'Demande de retrait invalide.')
        return redirect('agent_process_withdrawal')
    if withdrawal_id < 1:
        messages.error(request, 'Demande de retrait invalide.')
        return redirect('agent_process_withdrawal')

    with db_transaction.atomic():
        withdrawal = WithdrawalRequest.objects.select_for_update().filter(
            pk=withdrawal_id,
            status='pending',
            amount_debited=True,
        ).select_related('user').first()
        if not withdrawal:
            messages.error(request, 'Cette demande est introuvable ou a déjà été traitée.')
            return redirect('agent_process_withdrawal')

        withdrawal_transactions = list(
            WithdrawalTransaction.objects.select_for_update().filter(
                withdrawal_request=withdrawal,
                status='pending',
            )
        )
        if len(withdrawal_transactions) != 1:
            logger.error(
                'Pending withdrawal %s has %s pending detail rows.',
                withdrawal.pk,
                len(withdrawal_transactions),
            )
            messages.error(request, 'Historique de retrait incohérent ; contactez l’administration.')
            return redirect('agent_process_withdrawal')

        agent_commission_field = {
            'USD': 'commission_balance_usd',
            'HTG': 'commission_balance_htg',
            'DOP': 'commission_balance_peso',
            'EUR': 'commission_balance_eur',
        }.get(withdrawal.currency.upper())
        if withdrawal.fee_agent > 0 and not agent_commission_field:
            logger.error('Unsupported commission currency for withdrawal %s.', withdrawal.pk)
            messages.error(request, 'Devise de commission non prise en charge.')
            return redirect('agent_process_withdrawal')

        completed_at = timezone.now()
        claimed = WithdrawalRequest.objects.filter(
            pk=withdrawal.pk,
            status='pending',
            amount_debited=True,
        ).update(
            status='completed',
            processed_by=request.user,
            confirmed_at=completed_at,
        )
        if not claimed:
            messages.error(request, 'Cette demande a déjà été traitée.')
            return redirect('agent_process_withdrawal')

        withdrawal_transaction = withdrawal_transactions[0]
        withdrawal_transaction.status = 'completed'
        withdrawal_transaction.agent = request.user
        withdrawal_transaction.save(update_fields=['status', 'agent'])

        if withdrawal.fee_agent > 0 and agent_commission_field:
            agent_wallet, _ = Wallet.objects.get_or_create(user=request.user)
            Wallet.objects.filter(pk=agent_wallet.pk).update(
                **{
                    agent_commission_field: F(agent_commission_field) + withdrawal.fee_agent,
                }
            )
            Transaction.objects.create(
                sender=withdrawal.user,
                receiver=request.user,
                type='withdrawal_agent_commission',
                amount=withdrawal.fee_agent,
                currency=withdrawal.currency,
                status='approved',
            )

        Transaction.objects.create(
            sender=withdrawal.user,
            receiver=request.user,
            type='withdrawal_agent',
            amount=withdrawal.amount,
            currency=withdrawal.currency,
            status='completed',
        )
        create_persistent_notification(
            recipient=withdrawal.user,
            title=f'Retrait effectué : {withdrawal.amount} {withdrawal.currency}',
            message=f"Votre retrait a été traité par l'agent {request.user.username}.",
            notification_type='withdrawal_completed',
            deduplication_key=(
                f'agent-withdrawal-completed:{withdrawal.pk}:user:{withdrawal.user.pk}'
            ),
            target_url='/profile/',
        )

    messages.success(
        request,
        f"Retrait de {withdrawal.amount} {withdrawal.currency} traité pour {withdrawal.user.username}.",
    )
    logger.info(
        "Agent %s completed withdrawal request %s for user %s.",
        request.user.username,
        withdrawal.pk,
        withdrawal.user.username,
    )
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
