import logging

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


class PayPalConfigurationError(Exception):
    pass


class PayPalAPIError(Exception):
    pass


def _paypal_configuration():
    mode = getattr(settings, 'PAYPAL_MODE', 'sandbox')
    if mode == 'sandbox':
        base_url = 'https://api-m.sandbox.paypal.com'
    elif mode == 'live':
        if not getattr(settings, 'PAYPAL_LIVE_ENABLED', False):
            raise PayPalConfigurationError('PayPal Live mode is disabled pending approval.')
        base_url = 'https://api-m.paypal.com'
    else:
        raise PayPalConfigurationError('PAYPAL_MODE must be sandbox or live.')

    client_id = getattr(settings, 'PAYPAL_CLIENT_ID', '')
    client_secret = getattr(settings, 'PAYPAL_CLIENT_SECRET', '')
    if not client_id or not client_secret:
        raise PayPalConfigurationError('PayPal credentials are not configured.')
    return base_url, client_id, client_secret


def paypal_api_request(method, path, payload=None, request_id=None):
    base_url, client_id, client_secret = _paypal_configuration()
    try:
        token_response = requests.post(
            f'{base_url}/v1/oauth2/token',
            auth=(client_id, client_secret),
            data={'grant_type': 'client_credentials'},
            headers={'Accept': 'application/json'},
            timeout=(5, 20),
        )
        token_response.raise_for_status()
        access_token = token_response.json().get('access_token')
        if not access_token:
            raise PayPalAPIError('PayPal did not return an access token.')

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if request_id:
            headers['PayPal-Request-Id'] = request_id

        response = requests.request(
            method,
            f'{base_url}{path}',
            headers=headers,
            json=payload,
            timeout=(5, 30),
        )
        response.raise_for_status()
        return response.json() if response.content else {}
    except requests.RequestException as exc:
        logger.warning('PayPal API request failed for %s (%s).', path, type(exc).__name__)
        raise PayPalAPIError('PayPal is temporarily unavailable.') from exc
    except (ValueError, KeyError) as exc:
        logger.warning('PayPal returned an invalid response for %s.', path)
        raise PayPalAPIError('PayPal returned an invalid response.') from exc


def verify_webhook_signature(request, event):
    webhook_id = getattr(settings, 'PAYPAL_WEBHOOK_ID', '')
    if not webhook_id:
        raise PayPalConfigurationError('PayPal webhook is not configured.')

    headers = request.headers
    transmission_id = headers.get('PAYPAL-TRANSMISSION-ID')
    transmission_time = headers.get('PAYPAL-TRANSMISSION-TIME')
    cert_url = headers.get('PAYPAL-CERT-URL')
    auth_algo = headers.get('PAYPAL-AUTH-ALGO')
    transmission_sig = headers.get('PAYPAL-TRANSMISSION-SIG')
    if not all((transmission_id, transmission_time, cert_url, auth_algo, transmission_sig)):
        return False

    result = paypal_api_request(
        'POST',
        '/v1/notifications/verify-webhook-signature',
        payload={
            'auth_algo': auth_algo,
            'cert_url': cert_url,
            'transmission_id': transmission_id,
            'transmission_sig': transmission_sig,
            'transmission_time': transmission_time,
            'webhook_id': webhook_id,
            'webhook_event': event,
        },
    )
    return result.get('verification_status') == 'SUCCESS'
