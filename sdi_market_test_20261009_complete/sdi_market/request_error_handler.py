import logging

from django.shortcuts import render


logger = logging.getLogger('django.request')


def handler500(request, template_name='500.html'):
    user = getattr(request, 'user', None)
    username = getattr(user, 'get_username', lambda: '')() if user and user.is_authenticated else 'anonymous'
    logger.error(
        'Unhandled HTTP 500: method=%s path=%s user=%s',
        request.method,
        request.get_full_path(),
        username,
        exc_info=True,
        extra={'status_code': 500, 'request': request},
    )
    return render(request, template_name, status=500)
