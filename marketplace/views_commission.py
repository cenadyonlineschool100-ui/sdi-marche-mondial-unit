# Gestion des commissions des dépôts agents
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal

from .models import (
    User, CommissionRule, Deposit, AgentCommission, Wallet,
    DepositCommissionConfig, Transaction, CommissionConfig,
    WithdrawalCommissionTier, AdminCommissionLog, MarketplaceSettings,
    CommissionCategory, UserCommissionCategory, CommissionDistributionLog
)
from .business_logic import CommissionManager, get_system_admin_wallet


def has_commission_permission(user):
    """Vérifier si l'utilisateur a la permission de gérer les commissions"""
    if not user.is_staff:
        return False
    
    # Les super admins ont toujours accès
    if user.is_superuser:
        return True
    
    # Vérifier la permission personnalisée
    try:
        permission = Permission.objects.get(codename='manage_agent_commissions')
        return user.has_perm('marketplace.manage_agent_commissions')
    except Permission.DoesNotExist:
        return False


def get_commission_eligible_users():
    CommissionCategory.ensure_default_categories()
    user_ids = set()

    if CommissionCategory.objects.filter(slug='peuple', is_active=True).exists():
        peuple_ids = set(User.objects.filter(
            Q(orders__isnull=False) |
            Q(shop__product__orderitem__isnull=False)
        ).distinct().values_list('id', flat=True))
        user_ids |= peuple_ids

    privilege_ids = set(UserCommissionCategory.objects.filter(
        category__slug='privilege',
        category__is_active=True
    ).values_list('user_id', flat=True))
    premiere_ids = set(UserCommissionCategory.objects.filter(
        category__slug='premiere',
        category__is_active=True
    ).values_list('user_id', flat=True))
    user_ids |= privilege_ids | premiere_ids
    return User.objects.filter(id__in=user_ids)


@login_required
def manage_agent_commissions(request):
    """Voir et modifier les commissions des agents"""
    
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions.")
        return redirect('dashboard')
    
    # Récupérer tous les agents
    agents = User.objects.filter(is_agent=True).order_by('username')
    
    # Statistiques par agent
    agent_stats = []
    for agent in agents:
        total_deposits = Deposit.objects.filter(agent=agent, status='confirmed').count()
        total_amount = sum(d.amount for d in Deposit.objects.filter(agent=agent, status='confirmed'))
        total_commission = sum(d.commission for d in Deposit.objects.filter(agent=agent, status='confirmed'))
        commission_earned = agent.wallet.commission_balance_usd + agent.wallet.commission_balance_htg + agent.wallet.commission_balance_peso + agent.wallet.commission_balance_eur if hasattr(agent, 'wallet') else 0
        
        agent_stats.append({
            'agent': agent,
            'total_deposits': total_deposits,
            'total_amount': total_amount,
            'total_commission': total_commission,
            'commission_earned': commission_earned,
            'commission_rules': CommissionRule.objects.filter(agent=agent)
        })
    
    # Récupérer la configuration globale de commission de dépôt agent (système)
    deposit_commission_configs = DepositCommissionConfig.objects.order_by('currency')
    global_rules = CommissionRule.objects.filter(agent__isnull=True)
    marketplace_settings = MarketplaceSettings.get_solo()
    system_admin_wallet = get_system_admin_wallet()
    distribution_balance = system_admin_wallet.get_distribution_summary() if system_admin_wallet else {
        'USD': 0, 'HTG': 0, 'PESO': 0, 'EUR': 0
    }
    categories = CommissionCategory.ensure_default_categories()
    category_stats = []
    for category in categories:
        if category.slug == 'peuple':
            eligible_count = User.objects.filter(
                Q(orders__isnull=False) |
                Q(shop__product__orderitem__isnull=False)
            ).distinct().count() if category.is_active else 0
        else:
            eligible_count = UserCommissionCategory.objects.filter(category=category).count()
        category_stats.append({
            'category': category,
            'eligible_count': eligible_count,
        })

    context = {
        'agent_stats': agent_stats,
        'deposit_commission_configs': deposit_commission_configs,
        'global_rules': global_rules,
        'total_agents': agents.count(),
        'marketplace_settings': marketplace_settings,
        'distribution_balance': distribution_balance,
        'commission_categories': category_stats,
    }
    
    return render(request, 'marketplace/manage_commissions.html', context)


@login_required
def commission_peuple_configuration_adm(request):
    """Page d’administration pour la configuration Commission Peuple."""
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions.")
        return redirect('dashboard')

    categories = CommissionCategory.ensure_default_categories()
    marketplace_settings = MarketplaceSettings.get_solo()
    system_admin_wallet = get_system_admin_wallet()
    distribution_balance = system_admin_wallet.get_distribution_summary() if system_admin_wallet else {
        'USD': 0, 'HTG': 0, 'PESO': 0, 'EUR': 0
    }

    context = {
        'marketplace_settings': marketplace_settings,
        'distribution_balance': distribution_balance,
        'commission_categories': categories,
    }
    return render(request, 'marketplace/commission_peuple_configuration_adm.html', context)


@login_required
@require_http_methods(['POST'])
def update_commission_share_settings(request):
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions.")
        return redirect('dashboard')

    try:
        admin_share = Decimal(request.POST.get('admin_share', '70.00'))
        distribution_share = Decimal(request.POST.get('distribution_share', '30.00'))

        if admin_share < 0 or distribution_share < 0:
            raise ValueError('Les pourcentages ne peuvent pas être négatifs.')
        if admin_share + distribution_share > Decimal('100'):
            distribution_share = Decimal('100') - admin_share

        settings = MarketplaceSettings.get_solo()
        settings.commission_admin_share = admin_share
        settings.commission_distribution_share = distribution_share
        settings.full_clean()
        settings.save()

        messages.success(request, 'Les ratios de partage de commission ont été mis à jour.')
    except Exception as exc:
        messages.error(request, f'Erreur lors de la mise à jour des ratios: {exc}')

    return redirect('manage_agent_commissions')


@login_required
@require_http_methods(['POST'])
def distribute_commission_pool(request):
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions.")
        return redirect('dashboard')

    admin_wallet = get_system_admin_wallet()
    if not admin_wallet:
        messages.error(request, 'Portefeuille admin système introuvable.')
        return redirect('manage_agent_commissions')

    eligible_users = get_commission_eligible_users()
    if not eligible_users.exists():
        messages.warning(request, 'Aucun utilisateur éligible trouvé pour la distribution de commissions.')
        return redirect('manage_agent_commissions')

    user_count = eligible_users.count()
    currencies = ['USD', 'HTG', 'PESO', 'EUR']
    distributed_records = 0

    for currency in currencies:
        distribution_field = f'distribution_balance_{currency.lower()}'
        balance = getattr(admin_wallet, distribution_field, Decimal('0')) or Decimal('0')
        if balance <= 0:
            continue

        share = (balance / user_count).quantize(Decimal('0.01'))
        if share <= 0:
            continue

        distributed_total = share * user_count
        for user in eligible_users:
            wallet, _ = Wallet.objects.get_or_create(user=user)
            peuple_field = f'peuple_commission_balance_{currency.lower()}'
            current_balance = getattr(wallet, peuple_field, Decimal('0')) or Decimal('0')
            setattr(wallet, peuple_field, current_balance + share)
            wallet.save(update_fields=[peuple_field])
            CommissionDistributionLog.objects.create(
                admin=request.user,
                user=user,
                action='distribution',
                amount=share,
                currency=currency,
                description=f'Distribution Commission Peuple de {share} {currency} depuis le pool de réserve.'
            )
            distributed_records += 1

        setattr(admin_wallet, distribution_field, balance - distributed_total)

    admin_wallet.save()
    messages.success(request, f'Commissions Peuple distribuées à {user_count} utilisateur(s). {distributed_records} enregistrements créés.')
    return redirect('manage_agent_commissions')


@login_required
@require_http_methods(['POST'])
def return_commission_pool_to_system(request):
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions.")
        return redirect('dashboard')

    admin_wallet = get_system_admin_wallet()
    if not admin_wallet:
        messages.error(request, 'Portefeuille admin système introuvable.')
        return redirect('manage_agent_commissions')

    currencies = ['USD', 'HTG', 'PESO', 'EUR']
    returned_total = Decimal('0')

    for currency in currencies:
        returned_amount = admin_wallet.transfer_distribution_to_commission(currency=currency)
        if returned_amount > 0:
            CommissionDistributionLog.objects.create(
                admin=request.user,
                user=None,
                action='return',
                amount=returned_amount,
                currency=currency,
                description='Retour de la réserve de distribution au portefeuille principal du système.'
            )
            returned_total += returned_amount

    if returned_total > 0:
        messages.success(request, f'{returned_total} ont été retournés au portefeuille système.')
    else:
        messages.info(request, 'Aucune réserve de distribution disponible à retourner.')
    return redirect('manage_agent_commissions')


@login_required
@require_http_methods(['POST'])
def assign_commission_category(request):
    if not request.user.is_superuser:
        messages.error(request, "Seul l'admin principal peut attribuer les catégories de commission.")
        return redirect('manage_agent_commissions')

    user_identifier = request.POST.get('user_identifier', '').strip()
    category_id = request.POST.get('category_id')
    action = request.POST.get('assign_action')

    if not user_identifier or not category_id:
        messages.error(request, 'Veuillez renseigner l’utilisateur et la catégorie.')
        return redirect('manage_agent_commissions')

    user = User.objects.filter(Q(username=user_identifier) | Q(email=user_identifier)).first()
    if not user:
        messages.error(request, 'Utilisateur introuvable.')
        return redirect('manage_agent_commissions')

    category = get_object_or_404(CommissionCategory, id=category_id)

    if action == 'assign':
        obj, created = UserCommissionCategory.objects.get_or_create(user=user, category=category)
        if created:
            CommissionDistributionLog.objects.create(
                admin=request.user,
                user=user,
                action='assignment',
                amount=Decimal('0'),
                currency='USD',
                description=f'Attribution de la catégorie {category.name} à {user.username}.'
            )
            messages.success(request, f'{user.username} a été ajouté à {category.name}.')
        else:
            messages.info(request, f'{user.username} est déjà dans {category.name}.')
    else:
        UserCommissionCategory.objects.filter(user=user, category=category).delete()
        CommissionDistributionLog.objects.create(
            admin=request.user,
            user=user,
            action='unassignment',
            amount=Decimal('0'),
            currency='USD',
            description=f'Retrait de la catégorie {category.name} pour {user.username}.'
        )
        messages.success(request, f'{user.username} a été retiré de {category.name}.')

    return redirect('manage_agent_commissions')


@login_required
def toggle_commission_category(request, category_id):
    if not request.user.is_superuser:
        messages.error(request, "Seul l'admin principal peut activer/désactiver les catégories de commission.")
        return redirect('manage_agent_commissions')

    category = get_object_or_404(CommissionCategory, id=category_id)
    category.is_active = not category.is_active
    category.save()
    status = 'activée' if category.is_active else 'désactivée'
    messages.success(request, f'La catégorie {category.name} a été {status}.')
    return redirect('manage_agent_commissions')


@login_required
@require_http_methods(["GET", "POST"])
def edit_deposit_commission_config(request, config_id):
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions.")
        return redirect('dashboard')

    config = get_object_or_404(DepositCommissionConfig, id=config_id)

    if request.method == 'POST':
        try:
            commission_type = request.POST.get('commission_type', config.commission_type)
            commission_value = Decimal(request.POST.get('commission_value', config.commission_value))
            min_deposit = Decimal(request.POST.get('min_deposit', config.min_deposit))
            max_deposit = Decimal(request.POST.get('max_deposit', config.max_deposit))
            is_active = request.POST.get('is_active') == 'on'

            if commission_value < 0 or min_deposit < 0 or max_deposit < 0:
                messages.error(request, "Les montants de commission et les limites de dépôt ne peuvent pas être négatifs.")
                return redirect('edit_deposit_commission_config', config_id=config.id)

            if min_deposit >= max_deposit:
                messages.error(request, "Le dépôt minimum doit être inférieur au dépôt maximum.")
                return redirect('edit_deposit_commission_config', config_id=config.id)

            config.commission_type = commission_type
            config.commission_value = commission_value
            config.min_deposit = min_deposit
            config.max_deposit = max_deposit
            config.is_active = is_active
            config.updated_by = request.user
            config.save()

            messages.success(request, f"Configuration de commission dépôt {config.currency} mise à jour.")
            return redirect('manage_agent_commissions')
        except Exception as e:
            messages.error(request, f"Erreur: {str(e)}")
            return redirect('edit_deposit_commission_config', config_id=config.id)

    context = {
        'config': config,
    }
    return render(request, 'marketplace/edit_deposit_commission_config.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def edit_agent_commission_rule(request, rule_id):
    """Modifier une règle de commission d'agent"""
    
    if not has_commission_permission(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    rule = get_object_or_404(CommissionRule, id=rule_id)
    
    if request.method == 'POST':
        try:
            min_amount = Decimal(request.POST.get('min_amount', rule.min_amount))
            max_amount = Decimal(request.POST.get('max_amount', rule.max_amount))
            commission_amount = Decimal(request.POST.get('commission_amount', rule.commission_amount))
            
            if min_amount < 0 or max_amount < 0 or commission_amount < 0:
                messages.error(request, "Les montants ne peuvent pas être négatifs.")
                return redirect('manage_agent_commissions')
            
            if min_amount >= max_amount:
                messages.error(request, "Le montant minimum doit être inférieur au montant maximum.")
                return redirect('manage_agent_commissions')
            
            rule.min_amount = min_amount
            rule.max_amount = max_amount
            rule.commission_amount = commission_amount
            rule.save()
            
            # Log l'action
            Transaction.objects.create(
                sender=request.user,
                receiver=rule.agent if rule.agent else None,
                type='commission_rule_update',
                amount=commission_amount,
                currency='ALL',
                status='approved'
            )
            
            messages.success(request, f"Règle de commission mise à jour pour {rule.agent.username if rule.agent else 'Global'}.")
            return redirect('manage_agent_commissions')
        except Exception as e:
            messages.error(request, f"Erreur: {str(e)}")
            return redirect('manage_agent_commissions')
    
    context = {
        'rule': rule,
    }
    return render(request, 'marketplace/edit_commission_rule.html', context)


@login_required
def add_agent_commission_rule(request, agent_id):
    """Ajouter une règle de commission personnalisée pour un agent"""
    
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    agent = get_object_or_404(User, id=agent_id, is_agent=True)
    
    if request.method == 'POST':
        try:
            min_amount = Decimal(request.POST.get('min_amount', 0))
            max_amount = Decimal(request.POST.get('max_amount', 0))
            commission_amount = Decimal(request.POST.get('commission_amount', 0))
            
            if min_amount < 0 or max_amount < 0 or commission_amount < 0:
                messages.error(request, "Les montants ne peuvent pas être négatifs.")
                return redirect('manage_agent_commissions')
            
            if min_amount >= max_amount:
                messages.error(request, "Le montant minimum doit être inférieur au montant maximum.")
                return redirect('manage_agent_commissions')
            
            # Vérifier les chevauchements
            existing = CommissionRule.objects.filter(
                agent=agent,
                min_amount__lt=max_amount,
                max_amount__gt=min_amount
            ).exists()
            
            if existing:
                messages.warning(request, "Cette plage chevauche une règle existante pour cet agent.")
            
            rule = CommissionRule.objects.create(
                agent=agent,
                min_amount=min_amount,
                max_amount=max_amount,
                commission_amount=commission_amount
            )
            
            messages.success(request, f"Règle de commission créée pour {agent.username}.")
            return redirect('manage_agent_commissions')
        except Exception as e:
            messages.error(request, f"Erreur: {str(e)}")
            return redirect('manage_agent_commissions')
    
    context = {
        'agent': agent,
    }
    return render(request, 'marketplace/add_commission_rule.html', context)


@login_required
def delete_agent_commission_rule(request, rule_id):
    """Supprimer une règle de commission"""
    
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    rule = get_object_or_404(CommissionRule, id=rule_id)
    agent_name = rule.agent.username if rule.agent else 'Global'
    
    if request.method == 'POST':
        rule.delete()
        messages.success(request, f"Règle de commission supprimée pour {agent_name}.")
        return redirect('manage_agent_commissions')
    
    context = {
        'rule': rule,
        'agent_name': agent_name,
    }
    return render(request, 'marketplace/confirm_delete_rule.html', context)


@login_required
def grant_commission_permission(request, user_id):
    """Donner la permission de gérer les commissions à un autre admin"""
    
    if not request.user.is_superuser and not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    target_user = get_object_or_404(User, id=user_id, is_staff=True)
    
    try:
        permission = Permission.objects.get(codename='manage_agent_commissions')
    except Permission.DoesNotExist:
        # Créer la permission si elle n'existe pas
        content_type = ContentType.objects.get_for_model(User)
        permission = Permission.objects.create(
            codename='manage_agent_commissions',
            name='Can manage agent commissions',
            content_type=content_type,
        )
    
    target_user.user_permissions.add(permission)
    messages.success(request, f"Permission accordée à {target_user.username} pour gérer les commissions.")
    return redirect('manage_agent_commissions')


@login_required
def revoke_commission_permission(request, user_id):
    """Retirer la permission de gérer les commissions"""
    
    if not request.user.is_superuser and not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    target_user = get_object_or_404(User, id=user_id, is_staff=True)
    
    try:
        permission = Permission.objects.get(codename='manage_agent_commissions')
        target_user.user_permissions.remove(permission)
        messages.success(request, f"Permission retirée à {target_user.username}.")
    except Permission.DoesNotExist:
        pass
    
    return redirect('manage_agent_commissions')


@login_required
def view_agent_deposit_history(request, agent_id):
    """Voir l'historique des dépôts et commissions d'un agent"""
    
    if not has_commission_permission(request.user):
        messages.error(request, "Vous n'avez pas la permission.")
        return redirect('dashboard')
    
    agent = get_object_or_404(User, id=agent_id, is_agent=True)
    deposits = Deposit.objects.filter(agent=agent, status='confirmed').order_by('-created_at')[:100]
    
    context = {
        'agent': agent,
        'deposits': deposits,
    }
    return render(request, 'marketplace/agent_deposit_history_admin.html', context)


@login_required
def manage_withdrawal_commissions(request):
    """Gérer les commissions de retrait (HTG)"""
    if not request.user.is_superuser and not request.user.has_perm('marketplace.manage_withdrawal_commissions'):
        messages.error(request, "Vous n'avez pas la permission de gérer les commissions de retrait.")
        return redirect('dashboard')

    CommissionManager.ensure_default_withdrawal_tiers()

    if request.method == 'POST':
        action = request.POST.get('action')
        ip_address = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        if ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()

        if action == 'add':
            if not request.user.is_superuser and not request.user.has_perm('marketplace.create_commission'):
                messages.error(request, "Vous n'avez pas la permission de créer une tranche de commission.")
                return redirect('manage_withdrawal_commissions')
            try:
                currency = request.POST.get('currency', 'HTG').upper()
                min_amount = Decimal(request.POST.get('min_amount', '0'))
                max_amount = Decimal(request.POST.get('max_amount', '0'))
                total_fee = Decimal(request.POST.get('total_fee', '0'))
                system_fee = Decimal(request.POST.get('system_fee', '0'))
                agent_fee = Decimal(request.POST.get('agent_fee', '0'))
                description = request.POST.get('description', '').strip()
                is_active = request.POST.get('active') == 'on'

                if min_amount < 0 or max_amount < 0 or total_fee < 0 or system_fee < 0 or agent_fee < 0:
                    raise ValueError('Les montants ne peuvent pas être négatifs.')
                if min_amount >= max_amount:
                    raise ValueError('Le montant minimum doit être inférieur au montant maximum.')

                tier = WithdrawalCommissionTier.objects.create(
                    currency=currency,
                    min_amount=min_amount,
                    max_amount=max_amount,
                    total_fee=total_fee,
                    system_fee=system_fee,
                    agent_fee=agent_fee,
                    description=description,
                    active=is_active
                )
                AdminCommissionLog.objects.create(
                    admin=request.user,
                    action_type='create',
                    target_name=str(tier),
                    target_type='WithdrawalCommissionTier',
                    old_value='',
                    new_value=f'{tier.total_fee}/{tier.system_fee}/{tier.agent_fee}',
                    ip_address=ip_address,
                )
                messages.success(request, 'Nouvelle tranche de commission ajoutée avec succès.')
            except Exception as exc:
                messages.error(request, f'Erreur lors de la création de la tranche: {exc}')
            return redirect('manage_withdrawal_commissions')

        if action == 'update':
            if not request.user.is_superuser and not request.user.has_perm('marketplace.edit_commission'):
                messages.error(request, "Vous n'avez pas la permission de modifier une tranche de commission.")
                return redirect('manage_withdrawal_commissions')
            try:
                tier_id = request.POST.get('tier_id')
                tier = WithdrawalCommissionTier.objects.get(id=tier_id)
                old_value = f'{tier.total_fee}/{tier.system_fee}/{tier.agent_fee}'
                tier.min_amount = Decimal(request.POST.get('min_amount', tier.min_amount))
                tier.max_amount = Decimal(request.POST.get('max_amount', tier.max_amount))
                tier.total_fee = Decimal(request.POST.get('total_fee', tier.total_fee))
                tier.system_fee = Decimal(request.POST.get('system_fee', tier.system_fee))
                tier.agent_fee = Decimal(request.POST.get('agent_fee', tier.agent_fee))
                tier.description = request.POST.get('description', tier.description)
                tier.active = request.POST.get('active') == 'on'
                tier.save()
                AdminCommissionLog.objects.create(
                    admin=request.user,
                    action_type='update',
                    target_name=str(tier),
                    target_type='WithdrawalCommissionTier',
                    old_value=old_value,
                    new_value=f'{tier.total_fee}/{tier.system_fee}/{tier.agent_fee}',
                    ip_address=ip_address,
                )
                messages.success(request, 'Tranche de commission mise à jour avec succès.')
            except WithdrawalCommissionTier.DoesNotExist:
                messages.error(request, 'Tranche de commission introuvable.')
            except Exception as exc:
                messages.error(request, f'Erreur lors de la mise à jour: {exc}')
            return redirect('manage_withdrawal_commissions')

        if action == 'delete':
            if not request.user.is_superuser and not request.user.has_perm('marketplace.delete_commission'):
                messages.error(request, "Vous n'avez pas la permission de supprimer une tranche de commission.")
                return redirect('manage_withdrawal_commissions')
            try:
                tier_id = request.POST.get('tier_id')
                tier = WithdrawalCommissionTier.objects.get(id=tier_id)
                AdminCommissionLog.objects.create(
                    admin=request.user,
                    action_type='delete',
                    target_name=str(tier),
                    target_type='WithdrawalCommissionTier',
                    old_value=f'{tier.total_fee}/{tier.system_fee}/{tier.agent_fee}',
                    new_value='',
                    ip_address=ip_address,
                )
                tier.delete()
                messages.success(request, 'Tranche de commission supprimée.')
            except WithdrawalCommissionTier.DoesNotExist:
                messages.error(request, 'Tranche de commission introuvable.')
            except Exception as exc:
                messages.error(request, f'Erreur lors de la suppression: {exc}')
            return redirect('manage_withdrawal_commissions')

    withdrawal_configs = WithdrawalCommissionTier.objects.order_by('min_amount')
    withdrawal_logs = AdminCommissionLog.objects.filter(target_type='WithdrawalCommissionTier').order_by('-created_at')[:20]
    total_withdrawal_fees = sum(t.total_fee for t in withdrawal_configs)
    system_revenue = sum(t.system_fee for t in withdrawal_configs)

    context = {
        'withdrawal_configs': withdrawal_configs,
        'withdrawal_logs': withdrawal_logs,
        'total_withdrawal_fees_configured': total_withdrawal_fees,
        'system_revenue_configured': system_revenue,
    }
    return render(request, 'marketplace/manage_withdrawal_commissions.html', context)


@login_required
def view_peuple_commission(request):
    """Voir et gérer la Commission Peuple de l'utilisateur"""
    user = request.user
    wallet, _ = Wallet.objects.get_or_create(user=user)
    
    peuple_summary = wallet.get_peuple_commission_summary()
    distribution_logs = CommissionDistributionLog.objects.filter(
        user=user,
        action='distribution'
    ).order_by('-created_at')[:50]
    
    # Vérifier l'éligibilité selon la règle Commission Peuple
    is_eligible_for_peuple = get_commission_eligible_users().filter(id=user.id).exists()
    peuple_rule_active = CommissionCategory.objects.filter(slug='peuple', is_active=True).exists()

    context = {
        'peuple_summary': peuple_summary,
        'distribution_logs': distribution_logs,
        'wallet': wallet,
        'is_eligible_for_peuple': is_eligible_for_peuple,
        'peuple_rule_active': peuple_rule_active,
    }
    return render(request, 'marketplace/view_peuple_commission.html', context)
