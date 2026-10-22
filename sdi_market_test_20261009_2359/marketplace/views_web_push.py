import base64
import binascii
import json
from json import JSONDecodeError
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.cache import never_cache
from django.template.loader import get_template

from .models import PushSubscription


def _decode_subscription_key(value, expected_length):
    if not isinstance(value, str) or not value:
        return False
    try:
        decoded = base64.b64decode(
            value + '=' * (-len(value) % 4),
            altchars=b'-_',
            validate=True,
        )
        return len(decoded) == expected_length
    except (ValueError, TypeError, binascii.Error):
        return False


@login_required
@require_GET
def web_push_vapid_key(request):
    public_key = getattr(settings, 'WEB_PUSH_VAPID_PUBLIC_KEY', '')
    if not public_key:
        return JsonResponse({'available': False}, status=503)
    return JsonResponse({'available': True, 'public_key': public_key})


@login_required
@require_http_methods(['POST', 'DELETE'])
def web_push_subscriptions(request):
    if len(request.body) > 8192:
        return JsonResponse({'error': 'Charge utile trop volumineuse.'}, status=413)
    try:
        data = json.loads(request.body or '{}')
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'JSON invalide.'}, status=400)

    endpoint = data.get('endpoint') if isinstance(data, dict) else None
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        return JsonResponse({'error': 'Endpoint invalide.'}, status=400)

    parsed_endpoint = urlsplit(endpoint)
    try:
        endpoint_port = parsed_endpoint.port
    except ValueError:
        endpoint_port = -1
    hostname = (parsed_endpoint.hostname or '').lower()
    trusted_push_hosts = (
        'fcm.googleapis.com',
        'updates.push.services.mozilla.com',
        'push.services.mozilla.com',
        'web.push.apple.com',
    )
    if (
        parsed_endpoint.scheme != 'https'
        or not parsed_endpoint.netloc
        or parsed_endpoint.username
        or parsed_endpoint.password
        or endpoint_port not in (None, 443)
        or (
            hostname not in trusted_push_hosts
            and not hostname.endswith('.notify.windows.com')
            and not hostname.endswith('.push.services.mozilla.com')
        )
    ):
        return JsonResponse({'error': 'Endpoint Push invalide.'}, status=400)

    if request.method == 'DELETE':
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return JsonResponse({'success': True})

    keys = data.get('keys')
    if not isinstance(keys, dict):
        return JsonResponse({'error': 'Clés Push manquantes.'}, status=400)
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not _decode_subscription_key(p256dh, 65) or not _decode_subscription_key(auth, 16):
        return JsonResponse({'error': 'Clés Push invalides.'}, status=400)

    defaults = {
            'user': request.user,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:512],
            'is_active': True,
        }
    with transaction.atomic():
        subscription, created = PushSubscription.objects.get_or_create(endpoint=endpoint, defaults=defaults)
        if not created:
            if subscription.user_id != request.user.pk:
                return JsonResponse({'error': 'Cet abonnement est déjà associé à un autre compte.'}, status=409)
            for field, value in defaults.items():
                setattr(subscription, field, value)
            subscription.save(update_fields=list(defaults))
    return JsonResponse({'success': True, 'created': created, 'id': subscription.pk}, status=201 if created else 200)


@login_required
@require_GET
def web_push_csrf_token(request):
    return JsonResponse({'csrf_token': get_token(request)})


@require_GET
@never_cache
def service_worker(request):
    response = HttpResponse(
        get_template('marketplace/service-worker.js').render({}, request),
        content_type='application/javascript; charset=utf-8',
    )
    response['Service-Worker-Allowed'] = '/'
    return response