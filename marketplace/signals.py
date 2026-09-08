from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from decimal import Decimal
from .models import User, Wallet, Order, Transaction, DeliveryEmployee, DeliveryAssignment, Agent, AuditLog, Profile, MarketplaceSettings
from .utils import calcul_cashback
from .business_logic import CommissionManager, get_system_admin_wallet

@receiver(pre_save, sender=Wallet)
def wallet_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_wallet = Wallet.objects.get(pk=instance.pk)
            instance._old_balance = old_wallet.balance
        except Wallet.DoesNotExist:
            instance._old_balance = Decimal('0')

@receiver(post_save, sender=User)
def user_post_save(sender, instance, created, **kwargs):
    if created:
        # Créer wallet automatique
        Wallet.objects.create(
            user=instance,
            balance=Decimal('0'),
            balance_usd=Decimal('0'),
            balance_htg=Decimal('0'),
            balance_peso=Decimal('0'),
            balance_eur=Decimal('0'),
            commission_balance_usd=Decimal('0'),
            commission_balance_htg=Decimal('0'),
            commission_balance_peso=Decimal('0'),
            commission_balance_eur=Decimal('0'),
            distribution_balance_usd=Decimal('0'),
            distribution_balance_htg=Decimal('0'),
            distribution_balance_peso=Decimal('0'),
            distribution_balance_eur=Decimal('0')
        )
        # Créer profil utilisateur et générer les codes de retrait par défaut
        profile = Profile.objects.create(user=instance)
        if not profile.withdrawal_pin or not profile.withdrawal_code:
            profile.withdrawal_pin = profile._generate_withdrawal_pin()
            profile.withdrawal_code = profile._generate_withdrawal_code()
            profile.save()
        # Créer boutique automatique pour les vendeurs
        if instance.is_seller:
            from .models import Shop
            Shop.objects.create(owner=instance, name=f"Boutique de {instance.username}")
        # Créer un agent passif pour chaque nouveau compte
        Agent.objects.create(user=instance, is_active=False)
        # Si employé livraison ou livreur autorisé par profil
        if instance.is_delivery_employee or instance.is_delivery_agent:
            if not DeliveryEmployee.objects.filter(user=instance).exists():
                DeliveryEmployee.objects.create(
                    user=instance,
                    identifier=f"EMP{instance.id}",
                    assigned_zone=instance.zone or "Zone par défaut"
                )
    else:
        profile, _ = Profile.objects.get_or_create(user=instance)
        if not profile.withdrawal_pin or not profile.withdrawal_code:
            profile.withdrawal_pin = profile._generate_withdrawal_pin()
            profile.withdrawal_code = profile._generate_withdrawal_code()
            profile.save()
        if instance.is_delivery_agent and not DeliveryEmployee.objects.filter(user=instance).exists():
            DeliveryEmployee.objects.create(
                user=instance,
                identifier=f"EMP{instance.id}",
                assigned_zone=instance.zone or "Zone par défaut"
            )

@receiver(pre_save, sender=Order)
def order_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_order = Order.objects.get(pk=instance.pk)
            instance._old_status = old_order.status
        except Order.DoesNotExist:
            instance._old_status = None

@receiver(post_save, sender=Order)
def order_post_save(sender, instance, created, **kwargs):
    if not created and hasattr(instance, '_old_status') and instance.status != instance._old_status:
        AuditLog.objects.create(
            user=instance.buyer,
            action='order_status_update',
            details=f'Statut commande #{instance.id} changé de {instance._old_status} à {instance.status}'
        )
    if created and instance.status == "paid":
        total_quantity = sum(item.quantity for item in instance.items.all())
        buyer_cashback = calcul_cashback(total_quantity)
        seller_cashback_per_product = CommissionManager.get_config('cashback_par_produit_vendeur')
        admin_wallet = get_system_admin_wallet()

        # Mettre à jour wallet vendeur
        for item in instance.items.all():
            seller_wallet = Wallet.objects.get(user=item.product.shop.owner)
            taux_commission = CommissionManager.get_category_commission(item.product.category)
            commission_min = CommissionManager.get_config('commission_minimum')
            commission_amount = item.price_ht * taux_commission
            if commission_amount < commission_min:
                commission_amount = commission_min

            seller_wallet.balance += (item.price_ht * item.quantity) - commission_amount
            seller_cashback_amount = seller_cashback_per_product * Decimal(str(item.quantity))
            if seller_cashback_amount > 0:
                seller_wallet.commission_balance_usd += seller_cashback_amount
            seller_wallet.save()

            if admin_wallet and commission_amount > 0:
                admin_amount, distribution_amount = MarketplaceSettings.get_solo().get_commission_split(commission_amount)
                admin_wallet.credit_commission(admin_amount, currency='USD')
                if distribution_amount > 0:
                    admin_wallet.credit_distribution(distribution_amount, currency='USD')
                Transaction.objects.create(
                    sender=None,
                    receiver=admin_wallet.user,
                    amount=admin_amount,
                    type="commission",
                    status="approved"
                )
            else:
                Transaction.objects.create(
                    sender=None,
                    receiver=item.product.shop.owner,
                    amount=commission_amount,
                    type="commission",
                    status="approved"
                )

            if seller_cashback_amount > 0:
                Transaction.objects.create(
                    sender=None,
                    receiver=item.product.shop.owner,
                    amount=seller_cashback_amount,
                    type="cashback",
                    status="approved"
                )

        if admin_wallet:
            admin_wallet.save()

        buyer_wallet = Wallet.objects.get(user=instance.buyer)
        buyer_wallet.commission_balance_usd += buyer_cashback
        buyer_wallet.save()

        Transaction.objects.create(
            sender=None,
            receiver=instance.buyer,
            amount=buyer_cashback,
            type="cashback",
            status="approved"
        )

        # Assigner livraison
        assign_delivery_strict(instance)

def assign_delivery_strict(order):
    client_zone = order.buyer.zone
    if not client_zone:
        # Notifier admin
        return "Zone client non définie"

    available_employees = DeliveryEmployee.objects.filter(
        assigned_zone=client_zone, is_available=True
    ).order_by('deliveryassignment_set__count')

    if not available_employees.exists():
        # Notifier admin
        return "Aucun employé disponible"

    employee = available_employees.first()
    DeliveryAssignment.objects.create(employee=employee, order=order)
    employee.is_available = False
    employee.save()

    return f"Assigné à {employee.user.username}"