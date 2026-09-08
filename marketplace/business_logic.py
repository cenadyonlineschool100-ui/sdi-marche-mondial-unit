"""
🔥 LOGIQUE MÉTIER - Cœur du système de marketplace

Ce fichier contient toute la logique métier métier (business logic).
C'est ici qu'on gère les workflows réels de la marketplace.

DEVISE INTERNE: USD ✅
━━━━━━━━━━━━━━━━━
Tous les produits, prix, commissions et calculs internes sont en USD.
Les autres devises (HTG, DOP, EUR) sont convertis vers/depuis USD.
Cela évite la chaos comptable.

Structure:
- Assignation des livreurs
- Notifications
- Gestion du wallet/paiement (multi-devises, base USD)
- Gestion des retours
- Statistiques
"""

import json
import os
import urllib.request
import urllib.error
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db import transaction as db_transaction
from django.db.models import Count, Q
from .models import (
    Order, OrderItem, DeliveryAssignment, DeliveryEmployee, 
    DeliveryTracking, DeliveryNotification, ReturnRequest,
    Transaction, Wallet, User, ExchangeRate, CommissionConfig,
    WithdrawalCommissionTier, TransferCommissionTier, PersistentNotification, ResellerProduct, Shop, Product,
    MarketplaceSettings
)

# ===== DEVISE INTERNE =====
USD_INTERNAL_CURRENCY = 'USD'  # Tous les calculs et stockage internes sont en USD

DEFAULT_CURRENCY_RATES = {
    'USD': Decimal('1'),
    'HTG': Decimal('132'),
    'DOP': Decimal('58'),
    'EUR': Decimal('0.92'),
}

EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
EXCHANGE_RATE_API_URL = 'https://v6.exchangerate-api.com/v6/{key}/latest/USD'
EXCHANGE_RATE_FETCH_TIMEOUT = 8

SUPPORTED_CURRENCIES = ['USD', 'HTG', 'DOP', 'EUR']

CURRENCY_SYMBOLS = {
    'USD': '$',
    'HTG': 'G',
    'DOP': 'RD$',
    'EUR': '€',
}

CURRENCY_ALIASES = {
    'PESO': 'DOP',
    'RD': 'DOP',
    'EURO': 'EUR',
    'EUROS': 'EUR',
}


def normalize_currency(currency):
    if not currency:
        return currency
    code = currency.strip().upper()
    return CURRENCY_ALIASES.get(code, code)


def fetch_exchange_rates_from_api():
    """Récupère les taux de change depuis une API externe et enregistre un taux actif."""
    if not EXCHANGE_RATE_API_KEY:
        return None

    try:
        url = EXCHANGE_RATE_API_URL.format(key=EXCHANGE_RATE_API_KEY)
        with urllib.request.urlopen(url, timeout=EXCHANGE_RATE_FETCH_TIMEOUT) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return None

    if data.get('result') != 'success':
        return None

    rates = data.get('conversion_rates', {})
    usd_to_htg = Decimal(str(rates.get('HTG', DEFAULT_CURRENCY_RATES['HTG'])))
    usd_to_peso = Decimal(str(rates.get('DOP', rates.get('PESO', DEFAULT_CURRENCY_RATES['DOP']))))
    usd_to_eur = Decimal(str(rates.get('EUR', DEFAULT_CURRENCY_RATES['EUR'])))

    eur_to_usd = Decimal('1') / usd_to_eur if usd_to_eur else Decimal('0')
    eur_to_htg = usd_to_htg / usd_to_eur if usd_to_eur else Decimal('0')
    eur_to_peso = usd_to_peso / usd_to_eur if usd_to_eur else Decimal('0')
    htg_to_peso = usd_to_peso / usd_to_htg if usd_to_htg else Decimal('0')

    ExchangeRate.objects.filter(is_active=True).update(is_active=False)
    return ExchangeRate.objects.create(
        usd_to_htg=usd_to_htg,
        usd_to_peso=usd_to_peso,
        htg_to_peso=htg_to_peso,
        eur_to_usd=eur_to_usd,
        eur_to_htg=eur_to_htg,
        eur_to_peso=eur_to_peso,
        is_active=True,
    )


def get_active_exchange_rate():
    rate = ExchangeRate.objects.filter(is_active=True).order_by('-created_at').first()
    if rate:
        return rate
    return fetch_exchange_rates_from_api()


def convert_currency(amount, from_currency, to_currency):
    """Convertit un montant entre USD, HTG, PESO/DOP et EUR en utilisant les taux actifs."""
    from_currency = normalize_currency(from_currency)
    to_currency = normalize_currency(to_currency)

    if from_currency == to_currency:
        return amount

    rate = get_active_exchange_rate()
    if not rate:
        if from_currency not in DEFAULT_CURRENCY_RATES or to_currency not in DEFAULT_CURRENCY_RATES:
            raise ValueError('Conversion de devise non prise en charge')
        usd_amount = amount / DEFAULT_CURRENCY_RATES[from_currency] if from_currency != 'USD' else amount
        return usd_amount * DEFAULT_CURRENCY_RATES[to_currency] if to_currency != 'USD' else usd_amount

    # Convertir vers USD d'abord
    if from_currency == 'USD':
        usd_amount = amount
    elif from_currency == 'HTG':
        usd_amount = amount / rate.usd_to_htg if rate.usd_to_htg else Decimal('0')
    elif from_currency in ['DOP', 'PESO']:
        usd_amount = amount / rate.usd_to_peso if rate.usd_to_peso else Decimal('0')
    elif from_currency == 'EUR':
        usd_amount = amount * rate.eur_to_usd if rate.eur_to_usd else Decimal('0')
    else:
        raise ValueError(f'Devise source non prise en charge: {from_currency}')

    # Convertir depuis USD vers la devise cible
    if to_currency == 'USD':
        return usd_amount
    elif to_currency == 'HTG':
        return usd_amount * rate.usd_to_htg
    elif to_currency in ['DOP', 'PESO']:
        return usd_amount * rate.usd_to_peso
    elif to_currency == 'EUR':
        return usd_amount / rate.eur_to_usd if rate.eur_to_usd else Decimal('0')
    else:
        raise ValueError(f'Devise cible non prise en charge: {to_currency}')


# ═══════════════════════════════════════════════════════════════
# � SYSTÈME DE COMMISSIONS
# ═══════════════════════════════════════════════════════════════

def get_system_admin_wallet():
    """Retourne le wallet du compte administrateur système."""
    admin_user = User.objects.filter(is_superuser=True).order_by('id').first() or User.objects.filter(is_staff=True).order_by('id').first()
    if not admin_user:
        return None
    wallet, _ = Wallet.objects.get_or_create(user=admin_user)
    return wallet


class CommissionManager:
    """Gère le calcul et la configuration des commissions"""

    DEFAULT_CONFIGS = {
        'taux_commission_produit': {
            'valeur': Decimal('0.10'),
            'type': 'pourcentage',
            'description': 'Taux de commission sur les produits (10% par défaut)'
        },
        'taux_commission_categorie_default': {
            'valeur': Decimal('0.10'),
            'type': 'pourcentage',
            'description': 'Taux de commission par défaut pour les catégories si aucun taux spécifique n’est défini.'
        },
        'commission_minimum': {
            'valeur': Decimal('0.30'),
            'type': 'fixe',
            'description': 'Commission minimum sur les produits (0.30 USD)'
        },
        'base_livraison': {
            'valeur': Decimal('4.00'),
            'type': 'fixe',
            'description': 'Frais de base pour la livraison (4 USD)'
        },
        'prix_par_km': {
            'valeur': Decimal('1.00'),
            'type': 'variable',
            'description': 'Coût par kilomètre pour la livraison (1 USD/km)'
        },
        'prix_par_kg': {
            'valeur': Decimal('2.00'),
            'type': 'variable',
            'description': 'Coût variable selon le poids du produit (2 USD/kg par défaut)'
        },
        'prix_par_volume': {
            'valeur': Decimal('0.50'),
            'type': 'variable',
            'description': 'Coût variable selon le volume du produit (0.50 USD par litre par défaut)'
        },
        'taux_commission_livraison': {
            'valeur': Decimal('0.20'),
            'type': 'pourcentage',
            'description': 'Taux de commission sur les frais de livraison (20%)'
        },
        'cashback_par_produit_acheteur': {
            'valeur': Decimal('1.00'),
            'type': 'fixe',
            'description': 'Cashback versé à l’acheteur par produit acheté. (1 USD par produit)'
        },
        'cashback_par_produit_vendeur': {
            'valeur': Decimal('1.00'),
            'type': 'fixe',
            'description': 'Cashback versé au vendeur par produit vendu. (1 USD par produit)'
        },
        'withdrawal_fee_htg_20_99': {
            'valeur': Decimal('6.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 20 et 99 HTG'
        },
        'withdrawal_fee_htg_100_249': {
            'valeur': Decimal('12.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 100 et 249 HTG'
        },
        'withdrawal_fee_htg_250_499': {
            'valeur': Decimal('15.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 250 et 499 HTG'
        },
        'withdrawal_fee_htg_500_999': {
            'valeur': Decimal('40.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 500 et 999 HTG'
        },
        'withdrawal_fee_htg_1000_1999': {
            'valeur': Decimal('65.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 1,000 et 1,999 HTG'
        },
        'withdrawal_fee_htg_2000_3999': {
            'valeur': Decimal('115.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 2,000 et 3,999 HTG'
        },
        'withdrawal_fee_htg_4000_7999': {
            'valeur': Decimal('185.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 4,000 et 7,999 HTG'
        },
        'withdrawal_fee_htg_8000_11999': {
            'valeur': Decimal('275.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 8,000 et 11,999 HTG'
        },
        'withdrawal_fee_htg_12000_19999': {
            'valeur': Decimal('380.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 12,000 et 19,999 HTG'
        },
        'withdrawal_fee_htg_20000_39999': {
            'valeur': Decimal('640.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 20,000 et 39,999 HTG'
        },
        'withdrawal_fee_htg_40000_59999': {
            'valeur': Decimal('1050.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 40,000 et 59,999 HTG'
        },
        'withdrawal_fee_htg_60000_74999': {
            'valeur': Decimal('1400.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 60,000 et 74,999 HTG'
        },
        'withdrawal_fee_htg_75000_100000': {
            'valeur': Decimal('1600.00'),
            'type': 'fixe',
            'description': 'Frais HTG pour retrait Multi-appareils entre 75,000 et 100,000 HTG'
        }
    }

    DEFAULT_WITHDRAWAL_TIERS = [
        {'currency': 'HTG', 'min_amount': Decimal('20.00'), 'max_amount': Decimal('99.99'), 'total_fee': Decimal('6.00'), 'system_fee': Decimal('4.00'), 'agent_fee': Decimal('2.00'), 'description': '20 → 99 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('100.00'), 'max_amount': Decimal('249.99'), 'total_fee': Decimal('12.00'), 'system_fee': Decimal('8.00'), 'agent_fee': Decimal('4.00'), 'description': '100 → 249 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('250.00'), 'max_amount': Decimal('499.99'), 'total_fee': Decimal('15.00'), 'system_fee': Decimal('10.00'), 'agent_fee': Decimal('5.00'), 'description': '250 → 499 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('500.00'), 'max_amount': Decimal('999.99'), 'total_fee': Decimal('40.00'), 'system_fee': Decimal('28.00'), 'agent_fee': Decimal('12.00'), 'description': '500 → 999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('1000.00'), 'max_amount': Decimal('1999.99'), 'total_fee': Decimal('65.00'), 'system_fee': Decimal('45.00'), 'agent_fee': Decimal('20.00'), 'description': '1,000 → 1,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('2000.00'), 'max_amount': Decimal('3999.99'), 'total_fee': Decimal('115.00'), 'system_fee': Decimal('80.00'), 'agent_fee': Decimal('35.00'), 'description': '2,000 → 3,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('4000.00'), 'max_amount': Decimal('7999.99'), 'total_fee': Decimal('185.00'), 'system_fee': Decimal('125.00'), 'agent_fee': Decimal('60.00'), 'description': '4,000 → 7,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('8000.00'), 'max_amount': Decimal('11999.99'), 'total_fee': Decimal('275.00'), 'system_fee': Decimal('185.00'), 'agent_fee': Decimal('90.00'), 'description': '8,000 → 11,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('12000.00'), 'max_amount': Decimal('19999.99'), 'total_fee': Decimal('380.00'), 'system_fee': Decimal('250.00'), 'agent_fee': Decimal('130.00'), 'description': '12,000 → 19,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('20000.00'), 'max_amount': Decimal('39999.99'), 'total_fee': Decimal('80.00'), 'system_fee': Decimal('60.00'), 'agent_fee': Decimal('20.00'), 'description': '20,000 → 39,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('40000.00'), 'max_amount': Decimal('59999.99'), 'total_fee': Decimal('100.00'), 'system_fee': Decimal('75.00'), 'agent_fee': Decimal('25.00'), 'description': '40,000 → 59,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('60000.00'), 'max_amount': Decimal('74999.99'), 'total_fee': Decimal('150.00'), 'system_fee': Decimal('120.00'), 'agent_fee': Decimal('30.00'), 'description': '60,000 → 74,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('75000.00'), 'max_amount': Decimal('100000.00'), 'total_fee': Decimal('200.00'), 'system_fee': Decimal('150.00'), 'agent_fee': Decimal('50.00'), 'description': '75,000 → 100,000 HTG'},
    ]

    DEFAULT_TRANSFER_TIERS = [
        {'currency': 'HTG', 'min_amount': Decimal('20.00'), 'max_amount': Decimal('99.99'), 'total_fee': Decimal('6.00'), 'system_fee': Decimal('4.00'), 'agent_fee': Decimal('2.00'), 'description': '20 → 99 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('100.00'), 'max_amount': Decimal('249.99'), 'total_fee': Decimal('8.00'), 'system_fee': Decimal('5.00'), 'agent_fee': Decimal('3.00'), 'description': '100 → 249 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('250.00'), 'max_amount': Decimal('499.99'), 'total_fee': Decimal('12.00'), 'system_fee': Decimal('8.00'), 'agent_fee': Decimal('4.00'), 'description': '250 → 499 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('500.00'), 'max_amount': Decimal('999.99'), 'total_fee': Decimal('15.00'), 'system_fee': Decimal('10.00'), 'agent_fee': Decimal('5.00'), 'description': '500 → 999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('1000.00'), 'max_amount': Decimal('1999.99'), 'total_fee': Decimal('20.00'), 'system_fee': Decimal('13.00'), 'agent_fee': Decimal('7.00'), 'description': '1,000 → 1,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('2000.00'), 'max_amount': Decimal('3999.99'), 'total_fee': Decimal('25.00'), 'system_fee': Decimal('15.00'), 'agent_fee': Decimal('10.00'), 'description': '2,000 → 3,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('4000.00'), 'max_amount': Decimal('7999.99'), 'total_fee': Decimal('35.00'), 'system_fee': Decimal('23.00'), 'agent_fee': Decimal('12.00'), 'description': '4,000 → 7,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('8000.00'), 'max_amount': Decimal('11999.99'), 'total_fee': Decimal('40.00'), 'system_fee': Decimal('27.00'), 'agent_fee': Decimal('13.00'), 'description': '8,000 → 11,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('12000.00'), 'max_amount': Decimal('19999.99'), 'total_fee': Decimal('45.00'), 'system_fee': Decimal('30.00'), 'agent_fee': Decimal('15.00'), 'description': '12,000 → 19,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('20000.00'), 'max_amount': Decimal('39999.99'), 'total_fee': Decimal('80.00'), 'system_fee': Decimal('60.00'), 'agent_fee': Decimal('20.00'), 'description': '20,000 → 39,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('40000.00'), 'max_amount': Decimal('59999.99'), 'total_fee': Decimal('100.00'), 'system_fee': Decimal('75.00'), 'agent_fee': Decimal('25.00'), 'description': '40,000 → 59,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('60000.00'), 'max_amount': Decimal('74999.99'), 'total_fee': Decimal('150.00'), 'system_fee': Decimal('120.00'), 'agent_fee': Decimal('30.00'), 'description': '60,000 → 74,999 HTG'},
        {'currency': 'HTG', 'min_amount': Decimal('75000.00'), 'max_amount': Decimal('100000.00'), 'total_fee': Decimal('200.00'), 'system_fee': Decimal('150.00'), 'agent_fee': Decimal('50.00'), 'description': '75,000 → 100,000 HTG'},
    ]

    @staticmethod
    def ensure_default_configs():
        """Créer les configurations de commission par défaut si elles n'existent pas."""
        for key, meta in CommissionManager.DEFAULT_CONFIGS.items():
            CommissionConfig.objects.get_or_create(
                nom=key,
                defaults={
                    'valeur': meta['valeur'],
                    'type': meta['type'],
                    'description': meta['description'],
                    'actif': True
                }
            )

    @staticmethod
    def ensure_default_withdrawal_tiers():
        """Créer les tranches de commission de retrait par défaut si elles n'existent pas."""
        if not WithdrawalCommissionTier.objects.filter(currency='HTG').exists():
            for tier in CommissionManager.DEFAULT_WITHDRAWAL_TIERS:
                WithdrawalCommissionTier.objects.create(**tier)

    @staticmethod
    def get_config(key):
        """Récupère la valeur d'une configuration de commission"""
        try:
            config = CommissionConfig.objects.get(nom=key, actif=True)
            return config.valeur
        except CommissionConfig.DoesNotExist:
            if key in CommissionManager.DEFAULT_CONFIGS:
                meta = CommissionManager.DEFAULT_CONFIGS[key]
                CommissionConfig.objects.create(
                    nom=key,
                    valeur=meta['valeur'],
                    type=meta['type'],
                    description=meta['description'],
                    actif=True
                )
                return meta['valeur']
            return Decimal('0')

    @staticmethod
    def get_withdrawal_fee_htg(amount):
        """Retourne les frais de retrait HTG selon les tranches Multi-appareils."""
        amount = Decimal(amount)
        tier = CommissionManager.get_withdrawal_commission_tier(amount, 'HTG')
        if tier:
            return tier.total_fee
        thresholds = [
            (Decimal('20'), Decimal('99.99'), 'withdrawal_fee_htg_20_99'),
            (Decimal('100'), Decimal('249.99'), 'withdrawal_fee_htg_100_249'),
            (Decimal('250'), Decimal('499.99'), 'withdrawal_fee_htg_250_499'),
            (Decimal('500'), Decimal('999.99'), 'withdrawal_fee_htg_500_999'),
            (Decimal('1000'), Decimal('1999.99'), 'withdrawal_fee_htg_1000_1999'),
            (Decimal('2000'), Decimal('3999.99'), 'withdrawal_fee_htg_2000_3999'),
            (Decimal('4000'), Decimal('7999.99'), 'withdrawal_fee_htg_4000_7999'),
            (Decimal('8000'), Decimal('11999.99'), 'withdrawal_fee_htg_8000_11999'),
            (Decimal('12000'), Decimal('19999.99'), 'withdrawal_fee_htg_12000_19999'),
            (Decimal('20000'), Decimal('39999.99'), 'withdrawal_fee_htg_20000_39999'),
            (Decimal('40000'), Decimal('59999.99'), 'withdrawal_fee_htg_40000_59999'),
            (Decimal('60000'), Decimal('74999.99'), 'withdrawal_fee_htg_60000_74999'),
            (Decimal('75000'), Decimal('100000.00'), 'withdrawal_fee_htg_75000_100000'),
        ]
        for minimum, maximum, key in thresholds:
            if amount >= minimum and amount <= maximum:
                return CommissionManager.get_config(key)
        return Decimal('0')

    @staticmethod
    def get_withdrawal_commission_tier(amount, currency):
        """Retourne la tranche de commission de retrait active correspondant au montant."""
        currency = normalize_currency(currency)
        amount = Decimal(amount)
        try:
            CommissionManager.ensure_default_withdrawal_tiers()
            return WithdrawalCommissionTier.objects.filter(
                active=True,
                currency=currency,
                min_amount__lte=amount,
                max_amount__gte=amount
            ).order_by('min_amount').first()
        except Exception:
            return None

    @staticmethod
    def get_withdrawal_commission_breakdown(amount, currency):
        """Retourne le détail des commissions de retrait (montant total, système, agent)."""
        currency = normalize_currency(currency)
        if currency != 'HTG':
            return {'total_fee': Decimal('0'), 'system_fee': Decimal('0'), 'agent_fee': Decimal('0')}
        tier = CommissionManager.get_withdrawal_commission_tier(amount, currency)
        if tier:
            return {
                'total_fee': tier.total_fee,
                'system_fee': tier.system_fee,
                'agent_fee': tier.agent_fee,
            }
        total = CommissionManager.get_withdrawal_fee_htg(amount)
        return {'total_fee': total, 'system_fee': total, 'agent_fee': Decimal('0')}

    @staticmethod
    def ensure_default_transfer_tiers():
        """Créer les tranches de commission transfert par défaut si elles n'existent pas."""
        if not TransferCommissionTier.objects.filter(currency='HTG').exists():
            for tier in CommissionManager.DEFAULT_TRANSFER_TIERS:
                TransferCommissionTier.objects.create(**tier)

        for currency in ['USD', 'EUR', 'DOP']:
            if not TransferCommissionTier.objects.filter(currency=currency).exists():
                for tier in CommissionManager.DEFAULT_TRANSFER_TIERS:
                    try:
                        min_amount = CommissionManager.convert_currency(tier['min_amount'], 'HTG', currency).quantize(Decimal('0.01'))
                        max_amount = CommissionManager.convert_currency(tier['max_amount'], 'HTG', currency).quantize(Decimal('0.01'))
                        total_fee = CommissionManager.convert_currency(tier['total_fee'], 'HTG', currency).quantize(Decimal('0.01'))
                        system_fee = CommissionManager.convert_currency(tier['system_fee'], 'HTG', currency).quantize(Decimal('0.01'))
                        agent_fee = CommissionManager.convert_currency(tier['agent_fee'], 'HTG', currency).quantize(Decimal('0.01'))
                    except Exception:
                        min_amount = tier['min_amount']
                        max_amount = tier['max_amount']
                        total_fee = tier['total_fee']
                        system_fee = tier['system_fee']
                        agent_fee = tier['agent_fee']

                    TransferCommissionTier.objects.create(
                        currency=currency,
                        min_amount=min_amount,
                        max_amount=max_amount,
                        total_fee=total_fee,
                        system_fee=system_fee,
                        agent_fee=agent_fee,
                        description=f"{tier.get('description', '')} ({currency})",
                        active=tier.get('active', True),
                    )

    @staticmethod
    def get_transfer_commission_tier(amount, currency):
        """Retourne la tranche de commission de transfert active correspondant au montant."""
        currency = normalize_currency(currency)
        amount = Decimal(amount)
        try:
            CommissionManager.ensure_default_transfer_tiers()
            return TransferCommissionTier.objects.filter(
                active=True,
                currency=currency,
                min_amount__lte=amount,
                max_amount__gte=amount
            ).order_by('min_amount').first()
        except Exception:
            return None

    @staticmethod
    def get_transfer_commission_breakdown(amount, currency):
        """Retourne le détail des commissions de transfert (montant total, système, agent)."""
        currency = normalize_currency(currency)
        tier = CommissionManager.get_transfer_commission_tier(amount, currency)
        if tier:
            return {
                'total_fee': tier.total_fee,
                'system_fee': tier.system_fee,
                'agent_fee': tier.agent_fee,
            }
        return {'total_fee': Decimal('0'), 'system_fee': Decimal('0'), 'agent_fee': Decimal('0')}

    @staticmethod
    def get_transfer_fee(amount, currency):
        """Retourne les frais de transfert pour la devise demandée."""
        breakdown = CommissionManager.get_transfer_commission_breakdown(amount, currency)
        return breakdown['total_fee']

    @staticmethod
    def get_transfer_commission_tiers(currency='HTG'):
        """Retourne les tranches de commission transfert actives."""
        CommissionManager.ensure_default_transfer_tiers()
        return TransferCommissionTier.objects.filter(active=True, currency=normalize_currency(currency)).order_by('min_amount')

    @staticmethod
    def get_withdrawal_fee(amount, currency):
        """Retourne les frais de retrait pour la devise demandée."""
        breakdown = CommissionManager.get_withdrawal_commission_breakdown(amount, currency)
        return breakdown['total_fee']
    
    @staticmethod
    def get_all_configs():
        """Récupère toutes les configurations actives"""
        CommissionManager.ensure_default_configs()
        configs = CommissionConfig.objects.filter(actif=True)
        return {config.nom: config.valeur for config in configs}
    
    @staticmethod
    def get_category_commission(category):
        """Retourne le taux de commission pour une catégorie si défini."""
        if not category:
            return CommissionManager.get_config('taux_commission_produit')

        key = f'taux_commission_categorie_{category.slug}'
        try:
            return CommissionConfig.objects.get(nom=key, actif=True).valeur
        except CommissionConfig.DoesNotExist:
            return CommissionManager.get_config('taux_commission_produit')

    @staticmethod
    def calculate_volume_liters(product):
        """Calcule le volume du produit en litres à partir des dimensions en cm."""
        largeur = product.largeur or Decimal('0')
        hauteur = product.hauteur or Decimal('0')
        longueur = product.longueur or Decimal('0')
        volume_cm3 = largeur * hauteur * longueur
        return volume_cm3 / Decimal('1000')

    @staticmethod
    def calcul_commande(prix_produit, distance_km=0, poids_kg=None, volume_liters=None, quantite=1, category=None):
        """
        Calcule les commissions et répartitions pour une commande
        
        Args:
            prix_produit: Prix total des produits
            distance_km: Distance en km
            poids_kg: Poids total en kg
            volume_liters: Volume total en litres
            quantite: Nombre d'unités vendues
            category: Catégorie de produit pour taux spécifique
        Returns:
            dict avec tous les calculs
        """
        if distance_km is None:
            distance_km = Decimal('0')
        else:
            distance_km = Decimal(str(distance_km))

        poids_kg = Decimal(str(poids_kg or Decimal('0')))
        volume_liters = Decimal(str(volume_liters or Decimal('0')))
        quantite = Decimal(str(quantite or Decimal('1')))

        taux_commission = CommissionManager.get_category_commission(category)
        commission_min = CommissionManager.get_config('commission_minimum')
        base_livraison = CommissionManager.get_config('base_livraison')
        prix_km = CommissionManager.get_config('prix_par_km')
        prix_kg = CommissionManager.get_config('prix_par_kg')
        prix_volume = CommissionManager.get_config('prix_par_volume')
        taux_comm_livraison = CommissionManager.get_config('taux_commission_livraison')
        cashback_acheteur_par_produit = CommissionManager.get_config('cashback_par_produit_acheteur')
        cashback_vendeur_par_produit = CommissionManager.get_config('cashback_par_produit_vendeur')
        
        # Commission produit
        commission_produit = prix_produit * taux_commission
        if commission_produit < commission_min:
            commission_produit = commission_min
        
        # Livraison
        frais_livraison = base_livraison + (distance_km * prix_km) + (poids_kg * prix_kg) + (volume_liters * prix_volume)
        if frais_livraison < Decimal('0'):
            frais_livraison = Decimal('0')
        
        # Commission livraison
        commission_livraison = frais_livraison * taux_comm_livraison

        # Cashbacks
        cashback_acheteur = cashback_acheteur_par_produit * quantite
        cashback_vendeur = cashback_vendeur_par_produit * quantite
        cashback_total = cashback_acheteur + cashback_vendeur
        
        # Gains
        gain_vendeur = prix_produit - commission_produit + cashback_vendeur
        gain_livreur = frais_livraison - commission_livraison
        gain_admin = commission_produit + commission_livraison - cashback_total
        
        return {
            'commission_produit': commission_produit,
            'frais_livraison': frais_livraison,
            'commission_livraison': commission_livraison,
            'gain_vendeur': gain_vendeur,
            'gain_livreur': gain_livreur,
            'gain_admin': gain_admin,
            'cashback_acheteur': cashback_acheteur,
            'cashback_vendeur': cashback_vendeur,
            'cashback_total': cashback_total,
            'total_commande': prix_produit + frais_livraison,
            'taux_commission': taux_commission,
            'prix_par_kg': prix_kg,
            'prix_par_volume': prix_volume,
            'distance_km': distance_km,
            'poids_kg': poids_kg,
            'volume_liters': volume_liters,
            'quantite': quantite,
        }

    @staticmethod
    def calcul_commande_from_order(order):
        """Calcule les frais, commissions et parts à partir d'une commande."""
        prix_total = sum(item.price_ht * item.quantity for item in order.items.all())
        total_poids = sum((item.product.poids or Decimal('0')) * item.quantity for item in order.items.all())
        total_volume_liters = sum(CommissionManager.calculate_volume_liters(item.product) * item.quantity for item in order.items.all())
        total_quantity = sum(item.quantity for item in order.items.all())
        distance_km = order.distance_km if order.distance_km is not None else Decimal('5')

        product_commission_total = Decimal('0')
        for item in order.items.all():
            item_price = item.price_ht * item.quantity
            item_commission = CommissionManager.calcul_commande(
                item_price,
                distance_km=Decimal('0'),
                poids_kg=Decimal('0'),
                volume_liters=Decimal('0'),
                quantite=item.quantity,
                category=item.product.category
            )
            product_commission_total += item_commission['commission_produit']

        base_livraison = CommissionManager.get_config('base_livraison')
        prix_km = CommissionManager.get_config('prix_par_km')
        prix_kg = CommissionManager.get_config('prix_par_kg')
        prix_volume = CommissionManager.get_config('prix_par_volume')
        taux_comm_livraison = CommissionManager.get_config('taux_commission_livraison')
        cashback_acheteur_total = CommissionManager.get_config('cashback_par_produit_acheteur') * Decimal(str(total_quantity))
        cashback_vendeur_total = CommissionManager.get_config('cashback_par_produit_vendeur') * Decimal(str(total_quantity))
        cashback_total = cashback_acheteur_total + cashback_vendeur_total

        frais_livraison = base_livraison + (distance_km * prix_km) + (total_poids * prix_kg) + (total_volume_liters * prix_volume)
        if frais_livraison < Decimal('0'):
            frais_livraison = Decimal('0')

        commission_livraison = frais_livraison * taux_comm_livraison
        gain_vendeur = prix_total - product_commission_total + cashback_vendeur_total
        gain_livreur = frais_livraison - commission_livraison
        gain_admin = product_commission_total + commission_livraison - cashback_total

        return {
            'commission_produit': product_commission_total,
            'frais_livraison': frais_livraison,
            'commission_livraison': commission_livraison,
            'gain_vendeur': gain_vendeur,
            'gain_livreur': gain_livreur,
            'gain_admin': gain_admin,
            'cashback_acheteur': cashback_acheteur_total,
            'cashback_vendeur': cashback_vendeur_total,
            'cashback_total': cashback_total,
            'total_commande': prix_total + frais_livraison,
            'taux_commission': None,
            'prix_par_kg': prix_kg,
            'prix_par_volume': prix_volume,
            'distance_km': distance_km,
            'poids_kg': total_poids,
            'volume_liters': total_volume_liters,
            'prix_produit_total': prix_total,
        }


# ═══════════════════════════════════════════════════════════════
# 🚚 A. ASSIGNATION AUTOMATIQUE DU LIVREUR
# ═══════════════════════════════════════════════════════════════


class DeliveryAssignmentManager:
    """Gère l'assignation automatique des livreurs"""
    
    @staticmethod
    def assign_delivery_agent_to_order(order):
        """
        Assigne automatiquement un livreur optimal à une commande.
        
        Critères de sélection:
        ✅ Zone assignée du livreur
        ✅ Disponibilité
        ✅ Distance minimale
        ✅ Nombre de commandes en cours
        
        Args:
            order: Instance Order
            
        Returns:
            DeliveryAssignment ou None si aucun livreur disponible
        """
        
        # 1. Chercher livreurs disponibles
        available_agents = DeliveryAssignment.objects.filter(
            status__in=['assigned', 'picked_up', 'in_transit']
        ).values_list('employee_id', flat=True)
        
        # 2. Filtrer par zone si possible (extraire zone du user)
        user_zone = getattr(order.buyer, 'zone', None)
        
        agents = DeliveryEmployee.objects.filter(
            is_available=True
        ).exclude(
            id__in=available_agents
        )
        
        if user_zone:
            agents = agents.filter(assigned_zone=user_zone)
        
        # 3. Choisir le meilleur (le moins occupé)
        best_agent = agents.annotate(
            active_deliveries_count=Count(
                'deliveryassignment',
                filter=Q(
                    deliveryassignment__status__in=['assigned', 'picked_up', 'in_transit']
                )
            )
        ).order_by('active_deliveries_count').first()
        
        if not best_agent:
            return None
        
        # 4. Récupérer les coordonnées du vendeur depuis la commande ou sa boutique
        seller_lat = getattr(order, 'seller_lat', None)
        seller_lng = getattr(order, 'seller_lng', None)
        
        # Si les coordonnées du vendeur ne sont pas dans la commande, les récupérer de sa boutique
        if not seller_lat or not seller_lng:
            if order.items.exists():
                shop = order.items.first().product.shop
                seller_lat = getattr(shop, 'latitude', None)
                seller_lng = getattr(shop, 'longitude', None)
        
        # 4. Créer l'assignation
        assignment = DeliveryAssignment.objects.create(
            employee=best_agent,
            order=order,
            status='assigned',
            estimated_delivery_time=timezone.now() + timedelta(hours=2),
            delivery_zone=best_agent.assigned_zone,
            driver_lat=getattr(best_agent, 'current_latitude', None),  # Position actuelle du livreur
            driver_lng=getattr(best_agent, 'current_longitude', None),  # Position actuelle du livreur
            seller_lat=seller_lat,
            seller_lng=seller_lng,
            buyer_lat=getattr(order, 'buyer_lat', None),
            buyer_lng=getattr(order, 'buyer_lng', None)
        )
        
        # 5. Notifier
        NotificationManager.notify_delivery_assigned(assignment)
        
        return assignment
    
    @staticmethod
    def reassign_delivery(assignment, new_agent=None):
        """
        Réassigne une livraison à un autre livreur.
        
        Cas d'usage:
        - Livreur indisponible
        - Livreur changement de zone
        - Load balancing
        """
        if new_agent:
            assignment.employee = new_agent
        else:
            # Trouver automatiquement
            new_agent = DeliveryAssignmentManager.find_best_agent(
                assignment.order
            )
            if not new_agent:
                return False
            assignment.employee = new_agent
        
        assignment.save()
        
        # Notification ancien agent + nouveau + client
        NotificationManager.notify_delivery_reassigned(assignment)
        
        return True
    
    @staticmethod
    def assign_delivery_roundrobin(order):
        """
        Assigne une commande au prochain livreur disponible en mode round-robin.
        Cycle automatiquement entre les livreurs.
        
        Args:
            order: Instance Order
            
        Returns:
            DeliveryAssignment ou None si aucun livreur disponible
        """
        from .models import SystemSettings
        
        # Récupérer tous les livreurs disponibles
        available_employees = DeliveryEmployee.objects.filter(is_available=True).order_by('id')
        
        if not available_employees.exists():
            return None
        
        # Récupérer l'index du dernier livreur assigné
        settings, _ = SystemSettings.objects.get_or_create(id=1)
        current_index = settings.last_assigned_delivery_employee_index
        
        # Calculer le prochain index (round-robin)
        total_employees = available_employees.count()
        next_index = (current_index + 1) % total_employees
        
        # Récupérer le livreur à cet index
        selected_employee = available_employees[next_index]
        
        # Mettre à jour l'index pour la prochaine assignation
        settings.last_assigned_delivery_employee_index = next_index
        settings.save()
        
        # Créer l'assignation
        assignment = DeliveryAssignment.objects.create(
            employee=selected_employee,
            order=order,
            status='assigned',
            estimated_delivery_time=timezone.now() + timedelta(hours=2),
            delivery_zone=selected_employee.assigned_zone,
            driver_lat=selected_employee.current_latitude,
            driver_lng=selected_employee.current_longitude,
            buyer_lat=order.buyer_lat,
            buyer_lng=order.buyer_lng
        )
        
        # Créer un tracking initial
        DeliveryTracking.objects.create(
            assignment=assignment,
            status_update=f"Commande assignée au livreur {selected_employee.user.get_full_name() or selected_employee.identifier}",
            estimated_eta=assignment.estimated_delivery_time
        )
        
        return assignment
    
    @staticmethod
    def assign_delivery_manual(order, delivery_employee):
        """
        Assigne manuellement une commande à un livreur spécifique (par l'administrateur).
        
        Args:
            order: Instance Order
            delivery_employee: Instance DeliveryEmployee
            
        Returns:
            DeliveryAssignment
        """
        # Vérifier si une assignation existe déjà
        existing = DeliveryAssignment.objects.filter(order=order).first()
        if existing:
            existing.delete()
        
        # Créer la nouvelle assignation
        assignment = DeliveryAssignment.objects.create(
            employee=delivery_employee,
            order=order,
            status='assigned',
            estimated_delivery_time=timezone.now() + timedelta(hours=2),
            delivery_zone=delivery_employee.assigned_zone,
            driver_lat=delivery_employee.current_latitude,
            driver_lng=delivery_employee.current_longitude,
            buyer_lat=order.buyer_lat,
            buyer_lng=order.buyer_lng
        )
        
        # Créer un tracking initial
        DeliveryTracking.objects.create(
            assignment=assignment,
            status_update=f"Commande assignée manuellement au livreur {delivery_employee.user.get_full_name() or delivery_employee.identifier}",
            estimated_eta=assignment.estimated_delivery_time
        )
        
        return assignment


# ═══════════════════════════════════════════════════════════════
# 📍 B. SUIVI ET MISE À JOUR STATUT
# ═══════════════════════════════════════════════════════════════

class DeliveryStatusManager:
    """Gère le statut et le suivi des livraisons"""
    
    @staticmethod
    def update_delivery_status(assignment, new_status, notes='', lat=None, lng=None):
        """
        Met à jour le statut de la livraison + Order correspondant.
        
        Statuts possibles:
        - assigned: Laivreur a été assigné
        - picked_up: Livreur a récupéré la commande
        - in_transit: En route vers le client
        - arrived: Livreur arrivé à destination
        - delivered: Livraison confirmée
        - failed: Échec livraison
        
        Args:
            assignment: DeliveryAssignment instance
            new_status: Nouveau statut
            notes: Notes du livreur
            lat/lng: Coordonnées GPS optionnelles
        """
        
        old_status = assignment.status
        assignment.status = new_status
        
        # Auto-update timestamps
        if new_status == 'picked_up' and not assignment.picked_up_at:
            assignment.picked_up_at = timezone.now()
        
        elif new_status == 'in_transit' and not assignment.picked_up_at:
            assignment.picked_up_at = timezone.now()
        
        elif new_status == 'delivered' and not assignment.delivered_at:
            assignment.delivered_at = timezone.now()
            assignment.actual_delivery_time = timezone.now()
            
            # Stats livreur
            assignment.employee.total_deliveries += 1
            assignment.employee.successful_deliveries += 1
            assignment.employee.save()
            
            # Débloquer la transaction de paiement
            PaymentManager.confirm_delivery_payment(assignment.order)
        
        elif new_status == 'failed':
            # Livreur disponible de nouveau
            assignment.employee.is_available = True
            assignment.employee.save()
        
        if notes:
            assignment.delivery_notes = notes
        
        assignment.save()
        
        # 🔄 Créer tracking + notifications
        TrackingManager.record_tracking(
            assignment, lat, lng, new_status, notes
        )
        
        # 📲 Notifier client
        NotificationManager.notify_status_changed(assignment, new_status)
        
        # 📊 Update order status
        OrderStatusManager.sync_order_status(assignment)
        
        # 🌐 Notifier via WebSocket
        DeliveryStatusManager.notify_websocket_clients(assignment, new_status)
    
    @staticmethod
    def handle_failed_delivery(assignment, failure_reason):
        """
        Gère un échec de livraison.
        Options:
        - Nouvelle tentative avec un autre livreur
        - Retour au vendeur
        - Client cherche commande en magasin
        """
        assignment.status = 'failed'
        assignment.delivery_notes = f"Échec: {failure_reason}"
        assignment.save()
        
        # Notifier
        NotificationManager.notify_delivery_failed(assignment, failure_reason)
        
        # Option: réassigner
        new_assignment = DeliveryAssignmentManager.assign_delivery_agent_to_order(
            assignment.order
        )
        
        if new_assignment:
            # Annuler l'ancienne assignation
            assignment.delete()
        else:
            # Marquer commande temporairement
            assignment.order.status = 'awaiting_redelivery'
            assignment.order.save()
    
    @staticmethod
    def notify_websocket_clients(assignment, new_status):
        """Notifie les clients WebSocket du changement de statut"""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            import json
            
            channel_layer = get_channel_layer()
            
            # Données à envoyer
            data = {
                'type': 'status_update',
                'assignment_id': assignment.id,
                'status': new_status,
                'timestamp': timezone.now().isoformat(),
                'driver_location': {
                    'lat': float(assignment.current_lat) if assignment.current_lat else None,
                    'lng': float(assignment.current_lng) if assignment.current_lng else None,
                },
                'eta': assignment.estimated_delivery_time.isoformat() if assignment.estimated_delivery_time else None,
            }
            
            # Notifier le groupe de cette livraison
            async_to_sync(channel_layer.group_send)(
                f'delivery_{assignment.id}',
                {
                    'type': 'delivery_update',
                    'data': data
                }
            )
            
            # Notifier l'admin
            async_to_sync(channel_layer.group_send)(
                'admin_delivery',
                {
                    'type': 'delivery_status_change',
                    'data': {
                        'assignment_id': assignment.id,
                        'order_id': assignment.order.id,
                        'status': new_status,
                        'driver_name': assignment.employee.user.get_full_name(),
                        'client_name': assignment.order.buyer.get_full_name(),
                        'timestamp': timezone.now().isoformat(),
                    }
                }
            )
            
        except Exception as e:
            # Log l'erreur mais ne casse pas le processus
            print(f"Erreur WebSocket notification: {e}")


# ═══════════════════════════════════════════════════════════════
# 📲 C. NOTIFICATIONS (SMS/EMAIL/PUSH)
# ═══════════════════════════════════════════════════════════════

class NotificationManager:
    """Gère toutes les notifications du système"""
    
    NOTIFICATION_TEMPLATES = {
        'delivery_assigned': {
            'title': 'Livreur assigné',
            'message': 'Votre commande #{order_id} a été assignée à {agent_name}. Livraison prévue: {eta}'
        },
        'on_way': {
            'title': 'En route vers vous!',
            'message': 'Votre livreur {agent_name} est en route. Position: {location}'
        },
        'arrived': {
            'title': 'Le livreur est arrivé!',
            'message': 'Votre livreur est à votre porte. Commande: #{order_id}'
        },
        'delivered': {
            'title': '✅ Commande livrée',
            'message': 'Votre commande #{order_id} a été livrée avec succès à {address}'
        },
        'failed': {
            'title': '⚠️ Échec de livraison',
            'message': 'Impossible de livrer votre commande. Raison: {reason}'
        },
    }
    
    @staticmethod
    def notify_delivery_assigned(assignment):
        """Notifier quand livreur assigné"""
        order = assignment.order
        agent = assignment.employee.user
        
        # Message pour le client (notification normale)
        client_message = f"""
        ✅ Livreur assigné!
        
        Commande: #{order.id}
        Livreur: {agent.get_full_name()}
        ETA: {assignment.estimated_delivery_time.strftime('%H:%M')}
        
        Vous pouvez suivre votre colis en direct.
        """
        
        NotificationManager._send_notification(
            order.buyer,
            'delivery_assigned',
            client_message,
            assignment=assignment
        )
        
        # Notification persistante pour le LIVREUR
        driver_message = f"""
        🚚 NOUVELLE LIVRAISON ASSIGNÉE!
        
        Commande: #{order.id}
        Client: {order.buyer.get_full_name()}
        Adresse: {order.delivery_address}
        Montant: ${order.total_amount}
        
        Veuillez récupérer la marchandise et livrer au plus vite.
        """
        
        PersistentNotification.objects.create(
            recipient=agent,
            title="🚨 Nouvelle livraison assignée",
            message=driver_message,
            notification_type='delivery_assigned',
            related_assignment=assignment,
            sound_interval_minutes=1  # Sonne toutes les minutes
        )
        
        # Notifications persistantes pour les ADMINISTRATEURS
        admin_message = f"""
        📋 COMMANDE EN COURS
        
        Commande: #{order.id}
        Livreur: {agent.get_full_name()} ({assignment.employee.identifier})
        Client: {order.buyer.get_full_name()}
        Zone: {assignment.delivery_zone}
        Montant: ${order.total_amount}
        
        Une livraison est en cours. Merci de vérifier la progression.
        """
        
        # Notifier tous les administrateurs
        admin_users = User.objects.filter(
            Q(role='super_admin') | Q(role='admin_secondary') | Q(is_staff=True)
        )
        
        for admin in admin_users:
            PersistentNotification.objects.create(
                recipient=admin,
                title="🔔 Commande en cours",
                message=admin_message,
                notification_type='admin_delivery_assigned',
                related_assignment=assignment,
                sound_interval_minutes=1  # Sonne toutes les minutes
            )
    
    @staticmethod
    def notify_status_changed(assignment, status):
        """Notifier quand le statut change"""
        order = assignment.order
        agent = assignment.employee.user
        
        templates = {
            'picked_up': f"✅ Votre commande #{order.id} a été récupérée par {agent.get_full_name()}",
            'in_transit': f"🚚 Commande #{order.id} en route vers vous! Position: en cours de mise à jour",
            'arrived': f"📍 Votre livreur est arrivé! Commande: #{order.id}",
            'delivered': f"✅ Commande #{order.id} livrée avec succès!",
            'failed': f"⚠️ Problème de livraison pour la commande #{order.id}",
        }
        
        message = templates.get(status, f"Statut mise à jour: {status}")
        
        NotificationManager._send_notification(
            order.buyer,
            status,
            message,
            assignment=assignment
        )
    
    @staticmethod
    def notify_delivery_failed(assignment, reason):
        """Notifier d'un échec de livraison"""
        message = f"❌ Échec livraison commande #{assignment.order.id}: {reason}"
        
        NotificationManager._send_notification(
            assignment.order.buyer,
            'failed',
            message,
            assignment=assignment
        )
    
    @staticmethod
    def notify_delivery_reassigned(assignment):
        """Notifier de réassignation"""
        message = f"🔄 Votre commande #{assignment.order.id} a été réassignée à {assignment.employee.user.get_full_name()}"
        
        NotificationManager._send_notification(
            assignment.order.buyer,
            'reassigned',
            message,
            assignment=assignment
        )
    
    @staticmethod
    def _send_notification(user, notification_type, message, assignment=None):
        """
        Envoyer notification (SMS/EMAIL/PUSH/In-app)
        
        TODO: Intégrer services SMS (Twilio, AWS SNS)
        TODO: Intégrer services Email (SendGrid)
        TODO: Intégrer Firebase Push
        """
        
        # Créer notification in-app
        if assignment:
            DeliveryNotification.objects.create(
                assignment=assignment,
                recipient=user,
                notification_type=notification_type,
                title=f"Notification {notification_type}",
                message=message,
                is_read=False
            )
        
        # TODO: SMS
        # send_sms(user.phone, message)
        
        # TODO: EMAIL
        # send_email(user.email, "Livraison", message)
        
        # TODO: PUSH
        # send_push_notification(user, message)
        
        print(f"📲 [NOTIF] {user.email}: {message}")


# ═══════════════════════════════════════════════════════════════
# 💰 D. GESTION DES PAIEMENTS & WALLET
# ═══════════════════════════════════════════════════════════════

class PaymentManager:
    """Gère les paiements et transactions"""
    
    @staticmethod
    def block_payment_on_order(order):
        """
        Bloquer l'argent du client lors de la commande.
        
        État: En escrow (tiers de confiance)
        """
        buyer_wallet = Wallet.objects.get(user=order.buyer)
        
        # Vérifier solde suffisant
        if buyer_wallet.balance < order.total_amount:
            raise ValueError(f"Solde insuffisant pour commander (besoin: {order.total_amount}, vous avez: {buyer_wallet.balance})")
        
        # Créer transaction "bloquée"
        blocked_tx = Transaction.objects.create(
            sender=order.buyer,
            receiver=None,
            amount=order.total_amount,
            type='order_blocked',
            status='pending'
        )
        
        # Noter en base de données
        order.blocked_amount = order.total_amount
        order.save()
        
        print(f"💰 Paiement bloqué pour commande #{order.id}: {order.total_amount}€")
    
    @staticmethod
    def confirm_delivery_payment(order):
        """
        Débloquer et envoyer l'argent au vendeur après livraison avec calcul des commissions.
        
        Flux:
        1. Client paie → argent bloqué (escrow)
        2. Marchandise livrée ✅
        3. Calcul des commissions et distribution
        """
        
        if not order.items.exists():
            return False

        admin_wallet = get_system_admin_wallet()
        delivery_employee = None
        assignment = DeliveryAssignment.objects.filter(order=order, status='delivered').first()
        if assignment:
            delivery_employee = assignment.employee

        total_product = Decimal('0')
        total_reseller = Decimal('0')
        total_owner = Decimal('0')
        total_admin = Decimal('0')

        # Distribution par item (gère les copies/resellers)
        for item in order.items.all():
            price = item.price_ht * item.quantity
            total_product += price

            # Vérifier si l'item correspond à une copie vendue par un revendeur
            rp = ResellerProduct.objects.filter(copied_product=item.product).first()
            if rp:
                # Calculer commission revendeur
                if rp.commission_type == 'percent' and rp.commission_value:
                    reseller_amount = (price * (rp.commission_value / Decimal('100'))).quantize(Decimal('0.01'))
                elif rp.commission_value:
                    reseller_amount = (rp.commission_value * item.quantity).quantize(Decimal('0.01'))
                else:
                    reseller_amount = Decimal('0')

                # Commission plateforme (utilise config par défaut)
                platform_rate = CommissionManager.get_config('taux_commission_produit') or Decimal('0')
                platform_amount = (price * platform_rate).quantize(Decimal('0.01'))

                owner_amount = price - reseller_amount - platform_amount
                if owner_amount < 0:
                    owner_amount = Decimal('0')

                # Crediter revendeur
                reseller_wallet = Wallet.objects.get(user=rp.seller)
                reseller_wallet.balance += reseller_amount
                reseller_wallet.save()

                # Crediter propriétaire original
                owner = rp.original_product.shop.owner
                owner_wallet = Wallet.objects.get(user=owner)
                owner_wallet.balance += owner_amount
                owner_wallet.save()

                # Crediter plateforme
                if admin_wallet and platform_amount > 0:
                    admin_amount, distribution_amount = MarketplaceSettings.get_solo().get_commission_split(platform_amount)
                    admin_wallet.credit_commission(admin_amount, currency='USD')
                    if distribution_amount > 0:
                        admin_wallet.credit_distribution(distribution_amount, currency='USD')

                # Transactions
                Transaction.objects.create(sender=order.buyer, receiver=rp.seller, amount=reseller_amount, type='reseller_commission', status='approved')
                Transaction.objects.create(sender=order.buyer, receiver=owner, amount=owner_amount, type='order_payment', status='approved')
                if admin_wallet and platform_amount > 0:
                    Transaction.objects.create(sender=order.buyer, receiver=admin_wallet.user, amount=admin_amount, type='commission_admin', status='approved')

                total_reseller += reseller_amount
                total_owner += owner_amount
                total_admin += platform_amount
            else:
                # Flux classique pour produit non-copié
                distance_km = getattr(order, 'distance_km', 0) or 0
                commission_calc = CommissionManager.calcul_commande(price, distance_km)
                seller_amount = commission_calc['gain_vendeur']
                delivery_amount = commission_calc['gain_livreur']
                admin_amount = commission_calc['gain_admin']

                seller = item.product.shop.owner
                seller_wallet = Wallet.objects.get(user=seller)
                seller_wallet.balance += seller_amount
                seller_wallet.save()

                if admin_wallet and admin_amount > 0:
                    admin_amount, distribution_amount = MarketplaceSettings.get_solo().get_commission_split(admin_amount)
                    admin_wallet.credit_commission(admin_amount, currency='USD')
                    if distribution_amount > 0:
                        admin_wallet.credit_distribution(distribution_amount, currency='USD')

                Transaction.objects.create(sender=order.buyer, receiver=seller, amount=seller_amount, type='order_payment', status='approved')
                if admin_amount > 0 and admin_wallet:
                    Transaction.objects.create(sender=order.buyer, receiver=admin_wallet.user, amount=admin_amount, type='commission_admin', status='approved')

                total_owner += seller_amount
                total_admin += admin_amount

        # Paiement livreur
        if delivery_employee:
            delivery_amount = CommissionManager.get_config('taux_commission_livraison') * Decimal(order.items.count())
            delivery_wallet = Wallet.objects.get(user=delivery_employee.user)
            delivery_wallet.balance += delivery_amount
            delivery_wallet.save()
            Transaction.objects.create(sender=order.buyer, receiver=delivery_employee.user, amount=delivery_amount, type='delivery_payment', status='approved')

        print("Paiement confirmé pour commande #{}:".format(order.id))
        print("   Produit total: {}".format(total_product))
        print("   Revendeur: {}".format(total_reseller))
        print("   Propriétaire: {}".format(total_owner))
        print("   Admin: {}".format(total_admin))

        return True
    
    @staticmethod
    def refund_order(order, reason='return_accepted'):
        """
        Rembourser le client (retour approuvé, etc).
        
        Flux d'argent:
        - Client ← Argent retour
        - Vendeur ← Rien (argent retourné)
        """
        
        buyer_wallet = Wallet.objects.get(user=order.buyer)
        buyer_wallet.balance += order.total_amount
        buyer_wallet.save()
        
        # Transaction de remboursement
        tx = Transaction.objects.create(
            sender=None,  # Système
            receiver=order.buyer,
            amount=order.total_amount,
            type='refund',
            status='approved'
        )
        
        print(f"💵 Remboursement pour #{order.id}: {order.total_amount}€ → {order.buyer.username}")
        
        return True


# ═══════════════════════════════════════════════════════════════
# 🔄 E. GESTION DES RETOURS
# ═══════════════════════════════════════════════════════════════

class ReturnManager:
    """Gère les demandes de retour"""
    
    @staticmethod
    def approve_return(return_request):
        """Approuver une demande de retour"""
        return_request.status = 'approved'
        return_request.processed_at = timezone.now()
        return_request.save()
        
        # Rembourser
        PaymentManager.refund_order(
            return_request.order,
            'return_approved'
        )
        
        order = return_request.order
        order.status = 'returned'
        order.save()
        
        # Notifier client
        print(f"✅ Retour approuvé pour commande #{order.id}")
    
    @staticmethod
    def reject_return(return_request, rejection_reason=''):
        """Rejeter une demande de retour"""
        return_request.status = 'rejected'
        return_request.processed_at = timezone.now()
        return_request.admin_notes = rejection_reason
        return_request.save()
        
        print(f"❌ Retour rejeté pour commande #{return_request.order.id}")
    
    @staticmethod
    def get_return_eligibility(order):
        """
        Vérifier si une commande est éligible pour retour.
        
        Critères:
        - Doit être livrée
        - Dans les 30 jours
        - Pas de retour déjà en cours
        """
        
        if order.status != 'delivered':
            return False, "La commande n'est pas encore livrée"
        
        if ReturnRequest.objects.filter(order=order).exists():
            return False, "Un retour est déjà en cours pour cette commande"
        
        days_since_delivery = (timezone.now() - order.date_reception_confirmee).days
        if days_since_delivery > 30:
            return False, f"Délai de retour expiré ({days_since_delivery} jours)"
        
        return True, "Retour possible"


# ═══════════════════════════════════════════════════════════════
# 📊 F. GESTION DES STATUTS
# ═══════════════════════════════════════════════════════════════

class OrderStatusManager:
    """Synchronise les statuts Order ↔ DeliveryAssignment"""
    
    @staticmethod
    def sync_order_status(assignment):
        """
        Mettre à jour le statut Order en fonction de DeliveryAssignment.
        
        Mapping:
        - assigned → awaiting_delivery
        - picked_up → in_delivery
        - in_transit → in_delivery
        - delivered → delivered
        - failed → failed_delivery
        """
        
        order = assignment.order
        status_mapping = {
            'assigned': 'awaiting_delivery',
            'picked_up': 'in_delivery',
            'in_transit': 'in_delivery',
            'arrived': 'in_delivery',
            'delivered': 'delivered',
            'failed': 'failed_delivery',
            'returned': 'returned',
        }
        
        order.status = status_mapping.get(assignment.status, order.status)
        order.save()


# ═══════════════════════════════════════════════════════════════
# 📍 G. TRACKING GPS
# ═══════════════════════════════════════════════════════════════

class TrackingManager:
    """Gère le suivi GPS des livraisons"""
    
    @staticmethod
    def record_tracking(assignment, latitude=None, longitude=None, status_update='', notes=''):
        """
        Enregistrer une position GPS + update.
        
        Conserve l'historique complet pour analytics.
        """
        
        tracking_data = {
            'assignment': assignment,
            'status_update': status_update or f"Statut: {assignment.get_status_display()}",
        }
        
        if latitude and longitude:
            tracking_data['latitude'] = latitude
            tracking_data['longitude'] = longitude
            
            # Mettre à jour position livreur
            assignment.employee.current_latitude = latitude
            assignment.employee.current_longitude = longitude
            assignment.employee.last_location_update = timezone.now()
            assignment.employee.save()

            # Mettre à jour la position courante dans l'assignation
            assignment.current_lat = latitude
            assignment.current_lng = longitude
            assignment.save()
        
        tracking = DeliveryTracking.objects.create(**tracking_data)
        
        return tracking


# ═══════════════════════════════════════════════════════════════
# 📈 H. STATISTIQUES
# ═══════════════════════════════════════════════════════════════

class StatisticsManager:
    """Calcule les métriques du système"""
    
    @staticmethod
    def get_delivery_agent_stats(agent):
        """Obtenir stats complètes d'un livreur"""
        
        total = agent.total_deliveries or 1
        successful = agent.successful_deliveries or 0
        
        return {
            'name': agent.user.get_full_name(),
            'zone': agent.assigned_zone,
            'rating': agent.rating or 0,
            'total_deliveries': total,
            'successful_deliveries': successful,
            'success_rate': (successful / total * 100) if total > 0 else 0,
            'is_available': agent.is_available,
            'pending_deliveries': DeliveryAssignment.objects.filter(
                employee=agent,
                status__in=['assigned', 'picked_up', 'in_transit']
            ).count(),
        }
    
    @staticmethod
    def get_platform_stats():
        """Stats globales de la plateforme"""
        
        total_orders = Order.objects.count()
        delivered_orders = Order.objects.filter(status='delivered').count()
        pending_orders = Order.objects.filter(
            status__in=['pending', 'processing', 'assigned']
        ).count()
        failed_orders = Order.objects.filter(status='failed_delivery').count()
        returned_orders = Order.objects.filter(status='returned').count()
        
        total_revenue = Order.objects.filter(
            status='delivered'
        ).aggregate(total=db_transaction.Sum('total_amount'))['total'] or Decimal('0')
        
        return {
            'total_orders': total_orders,
            'delivered': delivered_orders,
            'pending': pending_orders,
            'failed': failed_orders,
            'returned': returned_orders,
            'success_rate': (delivered_orders / total_orders * 100) if total_orders > 0 else 0,
            'total_revenue': total_revenue,
            'average_delivery_time': 'TBD',  # À calculer
        }
    
    @staticmethod
    def get_return_stats():
        """Stats des retours"""
        
        all_returns = ReturnRequest.objects.all()
        approved = all_returns.filter(status='approved').count()
        rejected = all_returns.filter(status='rejected').count()
        pending = all_returns.filter(status='pending').count()
        
        return {
            'total_requests': all_returns.count(),
            'approved': approved,
            'rejected': rejected,
            'pending': pending,
            'approval_rate': (approved / all_returns.count() * 100) if all_returns.count() > 0 else 0,
            'top_return_reasons': list(
                all_returns.values('reason').annotate(
                    count=Count('id')
                ).order_by('-count')[:5]
            ),
        }
