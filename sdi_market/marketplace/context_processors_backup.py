"""
Marketplace context processors with graceful fallbacks
"""

def navigation_context(request):
    return {'marketplace_inactivity_timeout_seconds': 600}


def currency_context(request):
    return {
        'current_currency': 'USD',
        'current_currency_symbol': '$',
        'currency_choices': [('USD', 'USD'), ('EUR', 'EUR'), ('HTG', 'HTG'), ('DOP', 'DOP')],
        'price_conversion_note': 'Prix indicatif – paiement final selon la méthode choisie',
    }


def site_config_context(request):
    return {'site_configs': {}}


def activity_menu_context(request):
    return {'activity_menu_items': []}


def private_chat_context(request):
    return {'unread_message_count': 0}


def announcement_context(request):
    return {'admin_announcements': []}


def site_banner_context(request):
    return {'site_banner': None}
