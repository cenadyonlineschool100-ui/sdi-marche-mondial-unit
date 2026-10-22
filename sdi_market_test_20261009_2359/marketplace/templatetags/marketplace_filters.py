from decimal import Decimal, InvalidOperation

from django import template

from ..business_logic import CURRENCY_SYMBOLS, convert_currency, normalize_currency

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a key"""
    return dictionary.get(key)


@register.filter
def format_currency(amount, currency='USD'):
    """Convertit un montant USD vers la devise active et formate le résultat."""
    if amount is None:
        return ''
    try:
        amount = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        return amount

    currency = normalize_currency(currency)
    try:
        converted = convert_currency(amount, 'USD', currency)
    except Exception:
        converted = amount

    converted = converted.quantize(Decimal('0.01'))
    return f"{converted}"


@register.filter
def currency_symbol(currency):
    return CURRENCY_SYMBOLS.get(normalize_currency(currency), currency)


@register.filter
def format_product_price(product, currency='USD'):
    """Affiche le prix d'un produit en utilisant le prix original si la devise correspond."""
    if not product:
        return ''

    currency = normalize_currency(currency)
    original_currency = normalize_currency(getattr(product, 'price_original_currency', None) or '')
    original_amount = getattr(product, 'price_original', None)

    if original_amount is not None and original_currency == currency:
        try:
            return f"{Decimal(original_amount).quantize(Decimal('0.01'))}"
        except Exception:
            return original_amount

    return format_currency(getattr(product, 'price_ht', None), currency)