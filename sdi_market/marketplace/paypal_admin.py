import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import Order, PayPalPayment, PayPalWebhookEvent
from .paypal_gateway import PayPalAPIError, PayPalConfigurationError, paypal_api_request


logger = logging.getLogger(__name__)


@login_required
@require_http_methods(['GET', 'POST'])
def paypal_payment_admin(request):
    user = request.user
    if not (
        user.is_staff
        and (user.is_superuser or user.has_perm('marketplace.view_paypalpayment'))
    ):
        raise PermissionDenied

    connection_result = None
    remote_webhook = None
    if request.method == 'POST':
        if not settings.PAYPAL_CHECKOUT_ENABLED:
            connection_result = {
                'ok': False,
                'message': (
                    "Le paiement PayPal n'est pas activé : vérifiez la configuration "
                    "Sandbox côté serveur."
                ),
            }
        else:
            try:
                response = paypal_api_request('GET', '/v1/notifications/webhooks')
                webhooks = response.get('webhooks', [])
                remote_webhook = next(
                    (
                        webhook for webhook in webhooks
                        if webhook.get('id') == settings.PAYPAL_WEBHOOK_ID
                    ),
                    None,
                )
                if remote_webhook:
                    event_types = {
                        item.get('name')
                        for item in remote_webhook.get('event_types', [])
                    }
                    expected_events = {
                        'PAYMENT.CAPTURE.COMPLETED',
                        'PAYMENT.CAPTURE.DENIED',
                    }
                    missing_events = sorted(expected_events - event_types)
                    if missing_events:
                        connection_result = {
                            'ok': False,
                            'message': (
                                'Connexion PayPal établie, mais des événements requis '
                                'ne sont pas abonnés : ' + ', '.join(missing_events)
                            ),
                        }
                    else:
                        connection_result = {
                            'ok': True,
                            'message': (
                                'Connexion PayPal établie et webhook configuré trouvé '
                                'avec les événements requis.'
                            ),
                        }
                else:
                    connection_result = {
                        'ok': False,
                        'message': (
                            'Connexion PayPal établie, mais le webhook configuré '
                            "n'a pas été trouvé dans cette application."
                        ),
                    }
            except (PayPalAPIError, PayPalConfigurationError) as exc:
                logger.warning(
                    'PayPal admin connection check failed (%s).',
                    type(exc).__name__,
                )
                connection_result = {
                    'ok': False,
                    'message': (
                        'Vérification PayPal impossible. Vérifiez la configuration '
                        'serveur et les journaux protégés.'
                    ),
                }

    payments = (
        PayPalPayment.objects.select_related('order', 'order__buyer')
        .order_by('-created_at')[:30]
    )
    webhook_events = PayPalWebhookEvent.objects.order_by('-received_at')[:20]
    card_orders = (
        Order.objects.filter(payment_method__in=['int_card', 'eur_card'])
        .select_related('buyer')
        .order_by('-created_at')[:20]
    )
    context = {
        'paypal_mode': settings.PAYPAL_MODE,
        'paypal_checkout_enabled': settings.PAYPAL_CHECKOUT_ENABLED,
        'client_id_configured': bool(settings.PAYPAL_CLIENT_ID),
        'client_secret_configured': bool(settings.PAYPAL_CLIENT_SECRET),
        'webhook_id_configured': bool(settings.PAYPAL_WEBHOOK_ID),
        'webhook_configured': bool(settings.PAYPAL_WEBHOOK_ID),
        'connection_result': connection_result,
        'remote_webhook': remote_webhook,
        'payments': payments,
        'webhook_events': webhook_events,
        'card_orders': card_orders,
    }
    return render(request, 'marketplace/paypal_payment_admin.html', context)
