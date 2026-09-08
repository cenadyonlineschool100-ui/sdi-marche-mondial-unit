from django.shortcuts import render
import time
from django.utils import timezone
from django.db import OperationalError

from .models import SystemSettings, SecurityEvent, IPBlocklist


class SystemLockdownMiddleware:
    """Bloque l'accès aux utilisateurs non administrateurs lorsque le verrouillage d'urgence est activé."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        system_settings = None
        try:
            system_settings = SystemSettings.objects.get(pk=1)
        except (SystemSettings.DoesNotExist, OperationalError):
            # Table n'existe pas ou enregistrement n'existe pas
            system_settings = None

        # Vérifier si l'IP est bloquée
        client_ip = self._get_client_ip(request)
        try:
            blocked = IPBlocklist.objects.filter(
                ip_address=client_ip,
                is_active=True
            ).exclude(blocked_until__isnull=False, blocked_until__lt=timezone.now()).exists()
            if blocked:
                if request.path.startswith(('/login/', '/logout/', '/admin/', '/static/', '/media/', '/system-control/')):
                    # Autoriser les accès d'admin ou le login même si l'IP est dans la liste de blocage
                    pass
                elif request.user.is_authenticated and request.user.is_staff:
                    pass
                else:
                    return render(request, 'marketplace/ip_blocked.html', {
                        'client_ip': client_ip,
                        'system_settings': system_settings,
                    })
        except:
            pass

        if system_settings and system_settings.emergency_lockdown:
            allowed_paths = (
                '/login/',
                '/logout/',
                '/profile/',
                '/system-control/',
                '/admin/',
                '/static/',
                '/media/',
                '/api/security-dashboard/',
            )
            if request.path.startswith(allowed_paths):
                return self.get_response(request)

            if request.user.is_authenticated and request.user.is_staff:
                return self.get_response(request)

            # Autoriser l'affichage en lecture des pages publiques et du front-end
            # même si le mode verrouillage est activé, sans ouvrir l'administration.
            if request.method == 'GET' and not request.path.startswith(('/admin/', '/system-control/')):
                return self.get_response(request)

            return render(request, 'marketplace/system_locked.html', {
                'system_settings': system_settings,
            })

        return self.get_response(request)

    def _get_client_ip(self, request):
        """Récupère l'adresse IP du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class SecurityEventMiddleware:
    """Capture les événements de sécurité et d'activité pour le tableau de bord"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.start_time = time.time()
        response = self.get_response(request)
        
        try:
            self._log_security_event(request, response)
        except Exception as e:
            print(f"Erreur lors de l'enregistrement d'événement: {str(e)}")
        
        return response

    def _log_security_event(self, request, response):
        """Enregistre les événements importants"""
        from django.contrib.auth import authenticate
        from .models import User
        import json
        
        source_ip = self._get_client_ip(request)
        
        # Vérifier si l'IP est bloquée
        try:
            blocked = IPBlocklist.objects.filter(
                ip_address=source_ip,
                is_active=True
            ).exclude(blocked_until__isnull=False, blocked_until__lt=timezone.now()).exists()
            if blocked:
                return  # Ne pas enregistrer les IPs bloquées en excès
        except:
            pass
        
        # Ne pas logger les assets statiques et media
        if request.path.startswith(('/static/', '/media/', '/__debug__', '/api/security-dashboard')):
            return
        
        event_type = 'other'
        status_code = getattr(response, 'status_code', 200)
        response_time = int((time.time() - request.start_time) * 1000)  # en ms
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        user = request.user if request.user.is_authenticated else None
        
        # Déterminer le type d'événement
        if status_code >= 500:
            event_type = 'http_5xx'
        elif status_code >= 400:
            event_type = 'http_4xx'
        elif request.path.startswith('/admin/') or request.path.startswith('/system-control/'):
            event_type = 'admin_access'
        elif request.path.startswith('/api/'):
            event_type = 'api_error' if status_code >= 400 else 'other'
        
        # Enregistrer l'événement
        try:
            SecurityEvent.objects.create(
                event_type=event_type,
                source_ip=source_ip,
                user=user,
                path=request.path[:255],
                method=request.method,
                status_code=status_code,
                response_time_ms=response_time,
                user_agent=user_agent,
                description=f"{request.method} {request.path} - {status_code}"
            )
        except Exception as e:
            print(f"Erreur création événement: {str(e)}")

    def _get_client_ip(self, request):
        """Récupère l'adresse IP du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
