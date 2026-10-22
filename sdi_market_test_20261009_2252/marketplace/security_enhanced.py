# ==========================================
# SÉCURITÉ AVANCÉE - RATE LIMITING, PROTECTION, FIREWALL LOGIQUE
# ==========================================

import time
import hashlib
import secrets
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.http import HttpResponse
from .models import (
    IPBlocklist, SecurityEvent, AntiBotDetection, AntiBotField,
    SecurityAlert, SecurityLog, HoneypotEvent
)


class RateLimiter:
    """Limiteur de débit pour prévenir les attaques brute force"""
    
    @staticmethod
    def check_rate_limit(ip: str, endpoint: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
        """
        Vérifie si une IP dépasse la limite de débit
        
        Args:
            ip: Adresse IP du client
            endpoint: Endpoint accédé (ex: /api/login/)
            max_requests: Nombre maximum de requêtes
            window_seconds: Fenêtre de temps en secondes
        
        Returns:
            True si autorisé, False si dépassement de limite
        """
        cache_key = f"rate_limit:{ip}:{endpoint}"
        current_count = cache.get(cache_key, 0)
        
        if current_count >= max_requests:
            # Bloquer l'IP temporairement
            RateLimiter.block_suspicious_ip(ip, "Rate limit exceeded", duration_hours=1)
            return False
        
        # Incrémenter le compteur
        cache.set(cache_key, current_count + 1, window_seconds)
        return True
    
    @staticmethod
    def block_suspicious_ip(ip: str, reason: str, duration_hours: int = 1):
        """Bloquer une IP suspecte"""
        try:
            blocklist, created = IPBlocklist.objects.get_or_create(
                ip_address=ip,
                defaults={
                    'reason': reason,
                    'is_active': True,
                }
            )
            if not created:
                blocklist.reason = reason
                blocklist.is_active = True
                blocklist.blocked_until = timezone.now() + timedelta(hours=duration_hours)
                blocklist.save()
            
            # Créer une alerte
            SecurityAlert.objects.create(
                alert_type='suspicious_ip',
                priority='high',
                title=f'IP Suspecte Bloquée: {ip}',
                description=f'Raison: {reason}',
                source_ip=ip,
            )
            
            # Log
            SecurityLog.objects.create(
                level='warning',
                component='firewall',
                message=f'IP {ip} bloquée pour {duration_hours}h: {reason}',
            )
        except Exception as e:
            print(f"Erreur blocage IP: {str(e)}")


class AnomalyDetector:
    """Détecte les comportements anormaux"""
    
    @staticmethod
    def check_brute_force(ip: str, endpoint: str, max_failures: int = 5) -> bool:
        """
        Détecte les tentatives de brute force
        
        Returns:
            True si normal, False si comportement suspect
        """
        cache_key = f"brute_force:{ip}:{endpoint}"
        failures = cache.get(cache_key, 0)
        
        if failures >= max_failures:
            RateLimiter.block_suspicious_ip(ip, "Brute force attempt", duration_hours=2)
            return False
        
        return True
    
    @staticmethod
    def record_failed_login(ip: str, username: str = ""):
        """Enregistre une tentative de connexion échouée"""
        cache_key = f"failed_login:{ip}:{username}"
        attempts = cache.get(cache_key, 0)
        cache.set(cache_key, attempts + 1, 3600)  # 1 heure
        
        # Si trop de tentatives
        if attempts + 1 >= 5:
            AnomalyDetector.check_brute_force(ip, '/login/', 5)
    
    @staticmethod
    def check_sql_injection(user_input: str) -> bool:
        """
        Vérifie la présence de patterns SQL injection
        
        Returns:
            True si suspect, False si normal
        """
        sql_patterns = [
            'union', 'select', 'insert', 'delete', 'update', 'drop',
            'script', 'javascript', 'onerror', 'onclick', 'onload'
        ]
        
        input_lower = user_input.lower()
        for pattern in sql_patterns:
            if pattern in input_lower and ('--' in user_input or ';' in user_input):
                return True
        
        return False
    
    @staticmethod
    def check_xss_injection(user_input: str) -> bool:
        """
        Vérifie la présence de patterns XSS
        
        Returns:
            True si suspect, False si normal
        """
        xss_patterns = [
            '<script', '</script>', 'onerror=', 'onclick=', 'onload=',
            'javascript:', 'eval(', 'alert(', 'confirm(', 'prompt('
        ]
        
        input_lower = user_input.lower()
        for pattern in xss_patterns:
            if pattern in input_lower:
                return True
        
        return False


class AntiBot:
    """Systèmes anti-bot: honeypot et détection"""
    
    @staticmethod
    def check_honeypot_field(form_name: str, form_data: dict, ip: str) -> bool:
        """
        Vérifie si un champ honeypot a été rempli
        
        Returns:
            True si un bot est détecté, False si normal
        """
        try:
            field = AntiBotField.objects.get(form_name=form_name)
            
            # Si le champ caché contient une valeur, c'est un bot
            if form_data.get(field.field_name):
                # Enregistrer l'événement honeypot
                HoneypotEvent.objects.create(
                    event_type='honeypot',
                    source_ip=ip,
                    user_agent=form_data.get('user_agent', ''),
                    payload=str(form_data),
                    alerted=True,
                )
                
                # Bloquer l'IP
                RateLimiter.block_suspicious_ip(ip, "Honeypot field filled", duration_hours=24)
                
                # Incrémenter le compteur
                field.blocked_submissions += 1
                field.save()
                
                return True
        except AntiBotField.DoesNotExist:
            pass
        
        return False
    
    @staticmethod
    def create_honeypot_field(form_name: str) -> dict:
        """Crée un champ honeypot invisible"""
        try:
            field, created = AntiBotField.objects.get_or_create(
                form_name=form_name,
                field_name='website_url',
                defaults={
                    'field_label': 'Site web (laisser vide)',
                    'is_visible': False,
                    'css_classes': 'display:none;'
                }
            )
            
            return {
                'field_name': field.field_name,
                'field_label': field.field_label,
                'is_visible': field.is_visible,
                'css_classes': field.css_classes,
            }
        except Exception as e:
            print(f"Erreur création honeypot: {str(e)}")
            return {}


class JWTSecurity:
    """Sécurité JWT avancée"""
    
    @staticmethod
    def generate_secure_token(user_id: int, expires_in_hours: int = 24) -> str:
        """Génère un token JWT sécurisé"""
        import jwt
        from datetime import datetime
        
        payload = {
            'user_id': user_id,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=expires_in_hours),
            'nonce': secrets.token_urlsafe(16),
        }
        
        # TODO: Implémenter avec une clé secrète appropriée
        # token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        # return token
        
        return None
    
    @staticmethod
    def verify_token(token: str) -> dict or None:
        """Vérifie et décode un token JWT"""
        import jwt
        
        try:
            # TODO: Décoder avec la clé secrète
            # payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            # return payload
            return None
        except:
            return None


class DataValidator:
    """Validation des données pour prévenir les injections"""
    
    @staticmethod
    def sanitize_input(user_input: str, max_length: int = 255) -> str:
        """Nettoie et valide une entrée utilisateur"""
        if not isinstance(user_input, str):
            return ""
        
        # Limiter la longueur
        user_input = user_input[:max_length]
        
        # Supprimer les caractères dangereux
        dangerous_chars = ['<', '>', '{', '}', '|', '\\', '^', '~']
        for char in dangerous_chars:
            user_input = user_input.replace(char, '')
        
        return user_input.strip()
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Valide une adresse email"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def validate_username(username: str) -> bool:
        """Valide un nom d'utilisateur"""
        import re
        # Alphanumériques, tirets, underscores. Longueur 3-32
        pattern = r'^[a-zA-Z0-9_-]{3,32}$'
        return re.match(pattern, username) is not None


class TwoFactorAuth:
    """Authentification à deux facteurs"""
    
    @staticmethod
    def generate_2fa_code() -> str:
        """Génère un code 2FA (TOTP)"""
        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        return totp.now()
    
    @staticmethod
    def verify_2fa_code(secret: str, code: str) -> bool:
        """Vérifie un code 2FA"""
        import pyotp
        try:
            totp = pyotp.TOTP(secret)
            return totp.verify(code, valid_window=1)
        except:
            return False


class CORSProtection:
    """Protection contre les attaques CORS"""
    
    @staticmethod
    def validate_origin(request, allowed_origins: list) -> bool:
        """Valide l'origine d'une requête"""
        origin = request.META.get('HTTP_ORIGIN', '')
        return origin in allowed_origins


# ==========================================
# MIDDLEWARE SÉCURITÉ AVANCÉE
# ==========================================

class AdvancedSecurityMiddleware:
    """Middleware de sécurité avancée"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.protected_endpoints = [
            '/api/',
            '/admin/',
            '/system-control/',
            '/withdraw/',
        ]
    
    def __call__(self, request):
        # Vérifier le rate limiting
        if self._should_check_rate_limit(request):
            ip = self._get_client_ip(request)
            if not RateLimiter.check_rate_limit(ip, request.path, max_requests=100, window_seconds=60):
                return HttpResponse('Rate limit exceeded', status=429)
        
        # Vérifier les anomalies
        if request.method in ['POST', 'PUT']:
            if not self._check_anomalies(request):
                return HttpResponse('Request blocked: Suspicious activity', status=403)
        
        response = self.get_response(request)
        return response
    
    def _should_check_rate_limit(self, request) -> bool:
        """Vérifie si on doit contrôler le rate limit"""
        for endpoint in self.protected_endpoints:
            if request.path.startswith(endpoint):
                return True
        return False
    
    def _check_anomalies(self, request) -> bool:
        """Vérifie les anomalies"""
        try:
            # Checker l'injection SQL
            for key, value in request.POST.items():
                if isinstance(value, str) and AnomalyDetector.check_sql_injection(value):
                    return False
                if isinstance(value, str) and AnomalyDetector.check_xss_injection(value):
                    return False
        except:
            pass
        
        return True
    
    def _get_client_ip(self, request) -> str:
        """Récupère l'IP du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')
