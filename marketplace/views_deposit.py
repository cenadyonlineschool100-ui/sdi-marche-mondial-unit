# Views pour les dépôts MicrosDiCash
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.db import transaction as db_transaction
from django.utils import timezone
from datetime import datetime
from decimal import Decimal
import secrets
import json
from django.db.models import Sum, Q, Case, When, Value, IntegerField, F

from .models import (
    User, Wallet, Deposit, DepositCommissionConfig,
    Transaction, Agent, Profile, DepositLimit,
    DepositReceipt, TransactionLog, SecurityLog,
    AgentCommission, CommissionRule, TiKaneDailyPayment
)
from .business_logic import (
    create_persistent_notification, begin_financial_operation,
    complete_financial_operation, get_financial_operation_result,
    get_session_idempotency_key, rotate_session_idempotency_key,
)


def is_principal_admin(user):
    return user.is_superuser or user.has_perm('marketplace.principal_admin_power')


@login_required
@require_http_methods(["GET", "POST"])
def agent_deposit_view(request):
    """Vue pour créer un dépôt MicrosDiCash"""
    
    # Vérifier que l'utilisateur est un agent actif ou un admin principal
    try:
        agent = Agent.objects.get(user=request.user)
        if not agent.is_active and not is_principal_admin(request.user):
            messages.error(request, "Votre compte agent n'est pas encore activé. Contactez l'administrateur.")
            return redirect('dashboard')
    except Agent.DoesNotExist:
        if not is_principal_admin(request.user):
            messages.error(request, "Vous n'êtes pas un agent MicrosDiCash.")
            return redirect('dashboard')
        agent = None
    
    if request.method == 'GET':
        # Générer des codes de sécurité si l'agent n'en a pas encore
        if not request.user.display_security_pin:
            pin = ''.join(secrets.choice('0123456789') for _ in range(8))
            request.user.set_security_pin(pin)

        if not request.user.display_otp_code:
            otp = ''.join(secrets.choice('0123456789') for _ in range(4))
            request.user.set_otp_code(otp)

        # Afficher le formulaire
        currencies = [('USD', 'USD'), ('HTG', 'HTG'), ('DOP', 'DOP'), ('EUR', 'EUR')]
        agent_wallet = request.user.wallet
        commissions = DepositCommissionConfig.objects.filter(is_active=True)
        commission_rules = CommissionRule.objects.filter(
            Q(agent=request.user) | Q(agent__isnull=True)
        ).annotate(
            priority=Case(
                When(agent__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        ).order_by('priority', 'min_amount')
        
        context = {
            'currencies': currencies,
            'deposit_idempotency_key': get_session_idempotency_key(request, 'agent_deposit'),
            'agent_wallet': agent_wallet,
            'commissions': {c.currency: {'type': c.commission_type, 'value': c.commission_value} for c in commissions},
            'commissions_json': json.dumps({c.currency: {'type': c.commission_type, 'value': str(c.commission_value)} for c in commissions}),
            'commission_rules_json': json.dumps([
                {
                    'min_amount': str(rule.min_amount),
                    'max_amount': str(rule.max_amount),
                    'commission_amount': str(rule.commission_amount),
                    'is_agent_rule': bool(rule.agent)
                }
                for rule in commission_rules
            ]),
            'agent_security_pin': request.user.display_security_pin or '••••••••',
            'agent_final_code': request.user.display_otp_code or '••••'
        }
        return render(request, 'marketplace/agent_deposit.html', context)
    
    elif request.method == 'POST':
        # Traiter le dépôt
        account_number = request.POST.get('account_number', '').strip()
        amount_str = request.POST.get('amount', '0')
        currency = request.POST.get('currency', 'USD')
        tikane_deposit = request.POST.get('tikane_deposit') == 'on'
        agent_pin = request.POST.get('agent_pin', '').strip()
        final_code = request.POST.get('final_code', '').strip()

        errors = []

        if not account_number:
            errors.append("Numéro de compte client requis")

        try:
            amount = Decimal(amount_str)
            if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('0.01')):
                errors.append("Le montant doit être positif et limité à deux décimales")
        except Exception:
            errors.append("Montant invalide")

        if currency not in ['USD', 'HTG', 'DOP', 'EUR']:
            errors.append("Devise invalide")

        if not agent_pin:
            errors.append("PIN agent requis")

        if not final_code:
            errors.append("Code final de confirmation requis")

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('agent_deposit')

        # Identifier le client via le numéro de compte
        client = User.objects.filter(account_code__iexact=account_number).first()
        if not client:
            messages.error(request, "Aucun client trouvé.")
            return redirect('agent_deposit')

        if not client.is_active:
            messages.error(request, "Compte suspendu ou inactif.")
            return redirect('agent_deposit')

        if not hasattr(client, 'wallet'):
            messages.error(request, "Le client n'a pas de portefeuille configuré.")
            return redirect('agent_deposit')

        if tikane_deposit and (not hasattr(client, 'tikane_account') or not client.tikane_account or client.tikane_account.status != 'active'):
            messages.error(request, "Client sans compte Ti Kanè Digital actif. Impossible de faire un dépôt Ti Kanè.")
            return redirect('agent_deposit')

        # Vérifier l'agent et l'autorisation
        try:
            agent = Agent.objects.get(user=request.user)
            if not agent.is_active and not is_principal_admin(request.user):
                messages.error(request, "Agent non autorisé ou inactif.")
                return redirect('agent_deposit')
        except Agent.DoesNotExist:
            if not is_principal_admin(request.user):
                messages.error(request, "Vous n'êtes pas un agent MicrosDiCash.")
                return redirect('agent_deposit')
            agent = None

        if not request.user.check_security_pin(agent_pin):
            messages.error(request, "PIN incorrect.")
            return redirect('agent_deposit')

        if not request.user.check_otp_code(final_code):
            messages.error(request, "Code final de confirmation invalide.")
            return redirect('agent_deposit')

        # Chercher la configuration de commission
        try:
            commission_config = DepositCommissionConfig.objects.get(
                currency=currency,
                is_active=True
            )
        except DepositCommissionConfig.DoesNotExist:
            messages.error(request, f"Dépôts non disponibles pour {currency}")
            return redirect('agent_deposit')

        if amount < commission_config.min_deposit:
            messages.error(request, f"Montant minimum: {commission_config.min_deposit} {currency}")
            return redirect('agent_deposit')

        if amount > commission_config.max_deposit:
            messages.error(request, f"Montant maximum: {commission_config.max_deposit} {currency}")
            return redirect('agent_deposit')

        deposit_limit = DepositLimit.objects.order_by('-updated_at').first()
        if deposit_limit:
            if amount < deposit_limit.min_amount:
                messages.error(request, f"Montant inférieur au dépôt minimum autorisé : {deposit_limit.min_amount} {currency}")
                return redirect('agent_deposit')
            if amount > deposit_limit.max_amount:
                messages.error(request, f"Montant supérieur au dépôt maximum autorisé : {deposit_limit.max_amount} {currency}")
                return redirect('agent_deposit')

        def get_applicable_commission_rule(user, amount):
            rule = CommissionRule.objects.filter(agent=user, min_amount__lte=amount, max_amount__gte=amount).order_by('min_amount').first()
            if rule:
                return rule
            return CommissionRule.objects.filter(agent__isnull=True, min_amount__lte=amount, max_amount__gte=amount).order_by('min_amount').first()

        def calculate_commission_for_deposit(user, amount, default_config):
            rule = get_applicable_commission_rule(user, amount)
            if rule:
                return rule.commission_amount
            return default_config.calculate_commission(amount)

        def get_system_admin_user():
            admin_user = User.objects.filter(username__iexact='admin').first()
            if not admin_user:
                admin_user = User.objects.filter(is_superuser=True).first()
            return admin_user

        commission = calculate_commission_for_deposit(request.user, amount, commission_config)
        required_amount = amount

        agent_wallet, _ = Wallet.objects.get_or_create(user=request.user)
        wallet_field = {
            'USD': 'balance_usd',
            'HTG': 'balance_htg',
            'DOP': 'balance_peso',
            'EUR': 'balance_eur',
        }[currency]
        agent_balance = getattr(agent_wallet, wallet_field, Decimal('0'))

        if agent_balance < required_amount:
            messages.error(request, f"Solde insuffisant. Vous avez {agent_balance} {currency}, besoin de {required_amount} {currency} pour le dépôt.")
            return redirect('agent_deposit')

        client_wallet, _ = Wallet.objects.get_or_create(user=client)
        commission_field = {
            'USD': 'commission_balance_usd',
            'HTG': 'commission_balance_htg',
            'DOP': 'commission_balance_peso',
            'EUR': 'commission_balance_eur',
        }[currency]

        admin_user = get_system_admin_user()
        if not admin_user:
            messages.error(request, "Compte administrateur introuvable pour payer la commission.")
            return redirect('agent_deposit')

        admin_wallet, _ = Wallet.objects.get_or_create(user=admin_user)
        admin_balance = getattr(admin_wallet, wallet_field, Decimal('0'))

        if commission > 0 and admin_balance < commission:
            messages.error(request, f"Solde administrateur insuffisant pour payer la commission de {commission} {currency}.")
            return redirect('agent_deposit')

        try:
            with db_transaction.atomic():
                operation, operation_created = begin_financial_operation(
                    request.user,
                    'agent_deposit',
                    request.POST.get('idempotency_key'),
                    {
                        'client_id': client.pk,
                        'amount': str(amount),
                        'currency': currency,
                        'tikane_deposit': tikane_deposit,
                    },
                )
                if not operation_created:
                    existing_deposit = get_financial_operation_result(operation, Deposit)
                    return redirect('deposit_confirmation', deposit_id=existing_deposit.pk)

                locked_wallets = {
                    item.pk: item
                    for item in Wallet.objects.select_for_update().filter(
                        pk__in=[agent_wallet.pk, client_wallet.pk, admin_wallet.pk]
                    ).order_by('pk')
                }
                agent_wallet = locked_wallets[agent_wallet.pk]
                client_wallet = locked_wallets[client_wallet.pk]
                admin_wallet = locked_wallets[admin_wallet.pk]

                agent_debit = Wallet.objects.filter(
                    pk=agent_wallet.pk,
                    **{f'{wallet_field}__gte': required_amount},
                ).update(**{wallet_field: F(wallet_field) - required_amount})
                if not agent_debit:
                    db_transaction.set_rollback(True)
                    messages.error(request, "Solde agent insuffisant pour effectuer le dépôt.")
                    return redirect('agent_deposit')

                if tikane_deposit:
                    tikane_account = client.tikane_account.__class__.objects.select_for_update().get(
                        pk=client.tikane_account.pk
                    )
                    tikane_account.balance = F('balance') + amount
                    tikane_account.total_deposits = F('total_deposits') + amount
                    tikane_account.save(update_fields=['balance', 'total_deposits'])
                    tikane_account.refresh_from_db(fields=['balance', 'total_deposits'])
                else:
                    loan_repayment = Decimal('0')
                    if currency == 'HTG' and client_wallet.real_estate_loan_balance_htg > 0:
                        loan_balance = client_wallet.real_estate_loan_balance_htg
                        loan_repayment = min(amount, loan_balance)
                        loan_updated = Wallet.objects.filter(
                            pk=client_wallet.pk,
                            real_estate_loan_balance_htg__gte=loan_repayment,
                        ).update(
                            real_estate_loan_balance_htg=F('real_estate_loan_balance_htg') - loan_repayment
                        )
                        if not loan_updated:
                            db_transaction.set_rollback(True)
                            messages.error(request, "Le solde du prêt a changé pendant l'opération. Veuillez réessayer.")
                            return redirect('agent_deposit')

                    amount_to_credit = amount - loan_repayment
                    if amount_to_credit > 0:
                        Wallet.objects.filter(pk=client_wallet.pk).update(
                            **{wallet_field: F(wallet_field) + amount_to_credit}
                        )

                    tikane_account = None

                if commission > 0:
                    admin_debit = Wallet.objects.filter(
                        pk=admin_wallet.pk,
                        **{f'{wallet_field}__gte': commission},
                    ).update(**{wallet_field: F(wallet_field) - commission})
                    if not admin_debit:
                        db_transaction.set_rollback(True)
                        messages.error(request, f"Solde administrateur insuffisant pour payer la commission de {commission} {currency}.")
                        return redirect('agent_deposit')
                    Wallet.objects.filter(pk=agent_wallet.pk).update(
                        **{commission_field: F(commission_field) + commission}
                    )

                deposit = Deposit.objects.create(
                    agent=request.user,
                    client=client,
                    amount=amount,
                    currency=currency,
                    commission=commission,
                    tikane_deposit=tikane_deposit,
                    tikane_account=tikane_account,
                    status='confirmed',
                    confirmed_by=request.user,
                    confirmed_at=timezone.now()
                )

                Transaction.objects.create(
                    sender=request.user,
                    receiver=client,
                    amount=amount,
                    currency=currency,
                    type='deposit',
                    status='approved'
                )

                if commission > 0:
                    Transaction.objects.create(
                        sender=admin_user,
                        receiver=request.user,
                        amount=commission,
                        currency=currency,
                        type='commission',
                        status='approved'
                    )

                TransactionLog.objects.create(
                    transaction_type='deposit',
                    transaction_ref=deposit.reference,
                    actor=request.user,
                    details=f"Dépôt agent {request.user.username} vers client {client.username} : {amount} {currency}, commission {commission} {currency} payée par {admin_user.username}"
                )
                create_persistent_notification(
                    recipient=client,
                    title=f'💰 Argent reçu : {amount} {currency}',
                    message=f'Votre dépôt confirmé par {request.user.username}. Référence : {deposit.reference}.',
                    notification_type='money_received',
                    deduplication_key=f'deposit-received:{deposit.pk}:user:{client.pk}',
                    target_url='/profile/',
                )

                if commission > 0:
                    agent_commission = AgentCommission.objects.create(
                        agent=request.user,
                        deposit=deposit,
                        commission_amount=commission,
                        source_account='admin_wallet',
                        credited=True
                    )
                    create_persistent_notification(
                        recipient=request.user,
                        title=f'💰 Commission reçue : {commission} {currency}',
                        message=f'Votre commission sur le dépôt {deposit.reference} a été créditée.',
                        notification_type='commission_received',
                        deduplication_key=(
                            f'deposit-commission:{agent_commission.pk}:user:{request.user.pk}'
                        ),
                        target_url='/profile/',
                    )

                if tikane_deposit and tikane_account:
                    tikane_account.mark_next_unpaid_day_paid(deposit=deposit)

                SecurityLog.objects.create(
                    level='info',
                    component='deposit',
                    message=f"Dépôt agent {request.user.username} vers client {client.username} : {amount} {currency}",
                    source_ip=request.META.get('REMOTE_ADDR'),
                    user=request.user,
                    metadata={
                        'account_number': account_number,
                        'client_id': client.id,
                        'amount': str(amount),
                        'currency': currency,
                        'status': 'confirmed'
                    }
                )

                receipt = DepositReceipt.objects.create(
                    receipt_number=f"DP-{deposit.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    client=client,
                    agent=request.user,
                    deposit=deposit
                )
                receipt.generate_content()
                receipt.save(update_fields=['content'])
                complete_financial_operation(operation, deposit)
                db_transaction.on_commit(
                    lambda: rotate_session_idempotency_key(request, 'agent_deposit', request.POST.get('idempotency_key'))
                )

                messages.success(request, f"Dépôt de {amount} {currency} confirmé pour {client.username}. Référence: {deposit.reference}")

                if tikane_deposit:
                    messages.info(request, "Montant réservé pour Ti Kanè Digital. Retrait indisponible avant la date prévue.")
        except Exception as e:
            messages.error(request, f"Erreur lors du dépôt: {str(e)}")
            return redirect('agent_deposit')

        return redirect('deposit_confirmation', deposit_id=deposit.id)


@login_required
def deposit_confirmation(request, deposit_id):
    """Afficher la confirmation du dépôt"""
    try:
        deposit = Deposit.objects.get(id=deposit_id)
        # Vérifier les permissions
        if deposit.agent != request.user and not request.user.is_staff:
            messages.error(request, "Accès non autorisé")
            return redirect('dashboard')
    except Deposit.DoesNotExist:
        messages.error(request, "Dépôt non trouvé")
        return redirect('dashboard')
    
    wallet_field = 'balance'
    if deposit.currency != 'USD':
        wallet_field = f"balance_{deposit.currency.lower()}"

    client_wallet = getattr(deposit.client, 'wallet', None)
    current_balance = getattr(client_wallet, wallet_field, None) if client_wallet else None
    previous_balance = None
    if current_balance is not None:
        previous_balance = (current_balance - deposit.amount).quantize(Decimal('0.01')) if hasattr(current_balance, 'quantize') else current_balance - deposit.amount

    receipt = DepositReceipt.objects.filter(deposit=deposit).first()
    context = {
        'deposit': deposit,
        'receipt': receipt,
        'current_balance': current_balance,
        'previous_balance': previous_balance,
    }
    return render(request, 'marketplace/deposit_confirmation.html', context)


@login_required
def download_deposit_receipt(request, receipt_id):
    receipt = get_object_or_404(DepositReceipt, id=receipt_id)
    if receipt.agent != request.user and receipt.client != request.user and not request.user.is_staff:
        messages.error(request, "Accès non autorisé au reçu.")
        return redirect('dashboard')

    response = HttpResponse(receipt.content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="MicroSDICash-{receipt.receipt_number}.txt"'
    return response


@login_required
def view_deposit_receipt(request, receipt_id):
    receipt = get_object_or_404(DepositReceipt, id=receipt_id)
    if receipt.agent != request.user and receipt.client != request.user and not request.user.is_staff:
        messages.error(request, "Accès non autorisé au reçu.")
        return redirect('dashboard')

    deposit = receipt.deposit
    current_balance = None
    previous_balance = None
    if deposit and deposit.client and hasattr(deposit.client, 'wallet'):
        wallet_field = 'balance' if deposit.currency == 'USD' else f'balance_{deposit.currency.lower()}'
        client_wallet = getattr(deposit.client, 'wallet', None)
        current_balance = getattr(client_wallet, wallet_field, None) if client_wallet else None
        if current_balance is not None:
            previous_balance = (current_balance - deposit.amount).quantize(Decimal('0.01')) if hasattr(current_balance, 'quantize') else current_balance - deposit.amount

    context = {
        'receipt': receipt,
        'deposit': deposit,
        'current_balance': current_balance,
        'previous_balance': previous_balance,
    }
    return render(request, 'marketplace/deposit_receipt.html', context)


@login_required
def client_deposit_receipts(request):
    receipts = DepositReceipt.objects.filter(client=request.user).select_related('deposit', 'agent').order_by('-created_at')
    total_received = receipts.aggregate(total_amount=Sum('deposit__amount'))['total_amount'] or Decimal('0')
    receipt_count = receipts.count()
    context = {
        'receipts': receipts,
        'total_received': total_received,
        'receipt_count': receipt_count,
    }
    return render(request, 'marketplace/client_deposit_receipts.html', context)


@login_required
def agent_client_deposit_receipts(request, client_id):
    """Permet à un agent de voir les reçus d'un client identifié par ID"""
    # Vérifier que l'utilisateur est agent
    if not getattr(request.user, 'is_agent', False) and not request.user.is_staff:
        messages.error(request, "Accès refusé.")
        return redirect('dashboard')

    client = get_object_or_404(User, id=client_id)
    receipts = DepositReceipt.objects.filter(client=client).select_related('deposit', 'agent').order_by('-created_at')
    total_received = receipts.aggregate(total_amount=Sum('deposit__amount'))['total_amount'] or Decimal('0')
    receipt_count = receipts.count()
    context = {
        'receipts': receipts,
        'total_received': total_received,
        'receipt_count': receipt_count,
        'client': client,
    }
    return render(request, 'marketplace/client_deposit_receipts.html', context)


@login_required
@require_http_methods(["GET"])
def agent_deposit_history(request):
    """Historique des dépôts de l'agent"""
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        messages.error(request, "Vous n'êtes pas un agent MicrosDiCash.")
        return redirect('dashboard')
    
    deposits = Deposit.objects.filter(agent=request.user).order_by('-created_at')

    # Filtres de recherche pour l'historique
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    search = request.GET.get('search', '').strip()

    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, '%Y-%m-%d')
            deposits = deposits.filter(created_at__date__gte=parsed_start.date())
        except ValueError:
            pass

    if end_date:
        try:
            parsed_end = datetime.strptime(end_date, '%Y-%m-%d')
            deposits = deposits.filter(created_at__date__lte=parsed_end.date())
        except ValueError:
            pass

    if search:
        deposits = deposits.filter(
            Q(client__username__icontains=search) |
            Q(client__account_code__icontains=search) |
            Q(reference__icontains=search)
        )

    deposits = list(deposits[:100])

    # Statistiques
    currencies = dict.fromkeys(deposit.currency for deposit in deposits)
    stats = {}
    for currency in currencies:
        confirmed_deposits = [
            deposit for deposit in deposits
            if deposit.currency == currency and deposit.status == 'confirmed'
        ]
        total = sum(
            (deposit.amount for deposit in confirmed_deposits),
            Decimal('0'),
        )
        commission_total = sum(
            (deposit.commission for deposit in confirmed_deposits),
            Decimal('0'),
        )
        stats[currency] = {
            'total_amount': total,
            'total_commission': commission_total
        }

    context = {
        'deposits': deposits,
        'stats': stats,
        'start_date': start_date,
        'end_date': end_date,
        'search': search,
    }
    return render(request, 'marketplace/agent_deposit_history.html', context)
