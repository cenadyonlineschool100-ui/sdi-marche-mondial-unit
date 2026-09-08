# ==========================================
# API DE CYBERSÉCURITÉ INTELLIGENTE
# ==========================================

import os
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q, Sum, Count, Avg
import json
import socket
import subprocess
import re
from datetime import timedelta

from .models import (
    SecurityEvent, PortMonitoring, AIThreatAnalysis, HoneypotEvent,
    SecurityAlert, SecurityLog, SecurityMetrics, AntiBotDetection,
    SecurityVulnerability, VulnerabilityFix, AISecurityAudit,
    ContinuousSecurityMonitoring, AISecurityRecommendation, User
)
from .ai_cybersecurity import AICybersecurityEngine, SOCPermissions


# ==========================================
# API DASHBOARD CYBERSÉCURITÉ
# ==========================================

@login_required
@require_http_methods(["GET"])
def security_dashboard_api(request):
    """API complète pour le dashboard de cybersécurité"""
    
    # Vérifier que l'utilisateur est admin
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    # Métriques en temps réel
    now = timezone.now()
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)
    
    # Récupérer les métriques les plus récentes
    latest_metrics = SecurityMetrics.objects.order_by('-timestamp').first()
    
    # Alertes
    active_alerts = SecurityAlert.objects.filter(resolved=False)
    resolved_today = SecurityAlert.objects.filter(
        resolved=True,
        resolved_at__gte=one_day_ago
    ).count()
    
    # Événements honeypot
    honeypot_events = HoneypotEvent.objects.order_by('-created_at')[:10]
    
    # Analyse IA
    latest_ai = AIThreatAnalysis.objects.first()
    
    # Ports
    ports = PortMonitoring.objects.all()
    
    # Logs
    recent_logs = SecurityLog.objects.filter(
        created_at__gte=one_hour_ago
    ).order_by('-created_at')[:20]
    
    # Événements par minute (dernière heure)
    events_by_minute = SecurityEvent.objects.filter(
        created_at__gte=one_hour_ago
    ).extra(
        select={'minute': 'DATE_FORMAT(created_at, "%%Y-%%m-%%d %%H:%%i")'}
    ).values('minute').annotate(count=Count('id')).order_by('minute')
    
    # Types d'incidents
    incident_types = SecurityEvent.objects.filter(
        created_at__gte=one_day_ago
    ).values('event_type').annotate(count=Count('id')).order_by('-count')
    
    # IPs bloquées
    blocked_ips = SecurityEvent.objects.filter(
        event_type__in=['brute_force', 'malicious_payload'],
        created_at__gte=one_day_ago
    ).values('source_ip').distinct().count()
    
    return JsonResponse({
        'live_metrics': {
            'active_alerts': active_alerts.count(),
            'resolved_alerts_today': resolved_today,
            'ai_threat_score': float(latest_ai.threat_score) if latest_ai else 0.0,
            'active_connections': latest_metrics.active_connections if latest_metrics else 0,
            'network_traffic': latest_metrics.network_traffic if latest_metrics else 0,
            'blocked_requests': latest_metrics.blocked_requests if latest_metrics else 0,
            'bot_detections': latest_metrics.bot_detections if latest_metrics else 0,
            'honeypot_triggers': latest_metrics.honeypot_triggers if latest_metrics else 0,
            'cpu_usage': float(latest_metrics.cpu_usage) if latest_metrics else 0.0,
            'memory_usage': float(latest_metrics.memory_usage) if latest_metrics else 0.0,
        },
        'stats': {
            'blocked_ips': blocked_ips,
            'avg_response_time': 45,  # À calculer depuis les métriques
        },
        'ports_monitoring': [
            {
                'port': p.port,
                'is_open': p.is_open,
                'traffic_count': p.traffic_count,
                'risk_level': p.risk_level,
            }
            for p in ports
        ],
        'ai_analysis': {
            'threat_score': float(latest_ai.threat_score) if latest_ai else 0.0,
            'threat_level': latest_ai.threat_level if latest_ai else 'safe',
            'ai_confidence': float(latest_ai.ai_confidence) if latest_ai else 0.0,
            'bot_detections': latest_ai.bot_detections if latest_ai else 0,
            'brute_force_attempts': latest_ai.brute_force_attempts if latest_ai else 0,
            'sql_injection_attempts': latest_ai.sql_injection_attempts if latest_ai else 0,
            'xss_attempts': latest_ai.xss_attempts if latest_ai else 0,
            'last_analysis': latest_ai.last_analysis.strftime('%H:%M:%S') if latest_ai else 'N/A',
        },
        'honeypot_events': [
            {
                'type': e.get_event_type_display(),
                'ip': e.source_ip,
                'username': e.attempted_username,
                'time': e.created_at.strftime('%H:%M:%S'),
                'alerted': e.alerted,
            }
            for e in honeypot_events
        ],
        'recent_logs': [
            {
                'level': l.get_level_display(),
                'component': l.component,
                'message': l.message,
                'time': l.created_at.strftime('%H:%M:%S'),
            }
            for l in recent_logs
        ],
        'security_alerts': [
            {
                'title': a.title,
                'description': a.description,
                'priority': a.priority,
                'ip': a.source_ip,
                'time': a.created_at.strftime('%H:%M:%S'),
            }
            for a in active_alerts[:5]
        ],
        'system_status': {
            'cybersecurity_enabled': True,
            'emergency_lockdown': False,
        },
        'events_by_minute': [
            {
                'time': e['minute'],
                'count': e['count'],
            }
            for e in events_by_minute
        ],
        'incident_types': [
            {
                'type': i['event_type'],
                'count': i['count'],
            }
            for i in incident_types
        ],
    })


# ==========================================
# API DÉTECTION DE FAILLES
# ==========================================

@login_required
@require_http_methods(["GET"])
def get_vulnerabilities(request):
    """Retourner la liste des vulnérabilités détectées"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    severity = request.GET.get('severity', None)
    status = request.GET.get('status', None)
    
    vulns = SecurityVulnerability.objects.all()
    
    if severity:
        vulns = vulns.filter(severity=severity)
    if status:
        vulns = vulns.filter(status=status)
    
    return JsonResponse({
        'vulnerabilities': [
            {
                'id': v.id,
                'title': v.title,
                'type': v.get_vulnerability_type_display(),
                'severity': v.severity,
                'severity_color': v.get_display_severity_color(),
                'status': v.status,
                'file': v.file_path,
                'line': v.line_number,
                'route': v.route,
                'description': v.description,
                'recommended_fix': v.recommended_fix,
                'ai_confidence': float(v.ai_confidence),
                'detected_at': v.detected_at.strftime('%d/%m/%Y %H:%M'),
                'fixed': v.fix_applied_at is not None,
            }
            for v in vulns
        ],
        'stats': {
            'total': vulns.count(),
            'critical': vulns.filter(severity='critical').count(),
            'high': vulns.filter(severity='high').count(),
            'medium': vulns.filter(severity='medium').count(),
            'low': vulns.filter(severity='low').count(),
            'fixed': vulns.filter(status='fixed').count(),
        }
    })


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def fix_vulnerability(request):
    """Corriger automatiquement une vulnérabilité"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        data = json.loads(request.body)
        vuln_id = data.get('vulnerability_id')
        
        vuln = get_object_or_404(SecurityVulnerability, id=vuln_id)
        
        # Créer une sauvegarde
        if vuln.file_path:
            try:
                with open(vuln.file_path, 'r') as f:
                    vuln.backup_before_fix = f.read()
                    vuln.save()
            except:
                pass
        
        # Résoudre le chemin de fichier relatif si nécessaire
        file_path = vuln.file_path
        if not file_path:
            return JsonResponse({
                'success': False,
                'error': 'Aucun chemin de fichier défini pour cette vulnérabilité.',
            }, status=400)

        if not os.path.isabs(file_path):
            file_path = os.path.join(settings.BASE_DIR, file_path)

        if not vuln.fix_code and vuln.recommended_fix:
            vuln.fix_code = vuln.recommended_fix
            vuln.fix_notes = 'Fix automatique construit à partir du correctif recommandé.'

        if not vuln.fix_code:
            return JsonResponse({
                'success': False,
                'error': 'Aucune correction automatique disponible pour cette vulnérabilité. Vérifiez le champ fix_code ou recommended_fix.',
            }, status=400)

        if not os.path.exists(file_path):
            return JsonResponse({
                'success': False,
                'error': f"Fichier introuvable: {file_path}",
            }, status=400)

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                vuln.backup_before_fix = f.read()
                vuln.save()
        except Exception:
            vuln.backup_before_fix = ''
            vuln.save()

        try:
            with open(file_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(vuln.fix_code)
            
            VulnerabilityFix.objects.create(
                vulnerability=vuln,
                applied_by=request.user,
                original_code=vuln.code_snippet,
                fixed_code=vuln.fix_code,
                fix_description=f"Correction automatique appliquée par {request.user.username}",
                successful=True,
            )
            
            vuln.status = 'fixed'
            vuln.fix_applied_at = timezone.now()
            vuln.fix_applied_by = request.user
            vuln.save()
            
            SecurityLog.objects.create(
                level='info',
                component='ai',
                message=f"Vulnérabilité {vuln.title} corrigée automatiquement",
                user=request.user,
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Vulnérabilité corrigée avec succès',
                'vulnerability': {
                    'id': vuln.id,
                    'status': vuln.status,
                    'fixed_at': vuln.fix_applied_at.strftime('%d/%m/%Y %H:%M'),
                }
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=500)
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# ==========================================
# API AUDIT SÉCURITÉ IA
# ==========================================

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def run_security_audit(request):
    """Lancer un audit de sécurité complet"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        # Créer l'audit
        audit = AISecurityAudit.objects.create(
            status='running',
            triggered_by=request.user.username,
        )
        
        # TODO: Implémenter la logique d'audit réelle
        # Pour maintenant, retourner un audit fictif
        
        audit.status = 'completed'
        audit.completed_at = timezone.now()
        audit.overall_security_score = 82.5
        audit.vulnerabilities_found = 5
        audit.vulnerabilities_critical = 1
        audit.vulnerabilities_high = 2
        audit.vulnerabilities_medium = 2
        audit.vulnerabilities_low = 0
        audit.save()
        
        return JsonResponse({
            'success': True,
            'audit': {
                'id': audit.id,
                'started_at': audit.started_at.strftime('%d/%m/%Y %H:%M'),
                'completed_at': audit.completed_at.strftime('%d/%m/%Y %H:%M'),
                'security_score': audit.overall_security_score,
                'vulnerabilities': {
                    'total': audit.vulnerabilities_found,
                    'critical': audit.vulnerabilities_critical,
                    'high': audit.vulnerabilities_high,
                    'medium': audit.vulnerabilities_medium,
                    'low': audit.vulnerabilities_low,
                }
            }
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# ==========================================
# API RECOMMANDATIONS IA
# ==========================================

@login_required
@require_http_methods(["GET"])
def get_ai_recommendations(request):
    """Récupérer les recommandations de sécurité par IA"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    priority = request.GET.get('priority', None)
    implemented = request.GET.get('implemented', None)
    
    recs = AISecurityRecommendation.objects.all()
    
    if priority:
        recs = recs.filter(priority=priority)
    if implemented:
        recs = recs.filter(implemented=implemented == 'true')
    
    return JsonResponse({
        'recommendations': [
            {
                'id': r.id,
                'title': r.title,
                'type': r.get_recommendation_type_display(),
                'priority': r.priority,
                'description': r.description,
                'implementation_steps': r.implementation_steps,
                'expected_impact': r.expected_impact,
                'implemented': r.implemented,
                'ai_confidence': float(r.ai_confidence),
            }
            for r in recs
        ],
        'stats': {
            'total': recs.count(),
            'implemented': recs.filter(implemented=True).count(),
            'pending': recs.filter(implemented=False).count(),
        }
    })


# ==========================================
# API SURVEILLANCE CONTINUE
# ==========================================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_exempt
def continuous_monitoring_config(request):
    """Configurer la surveillance continue"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    monitoring = ContinuousSecurityMonitoring.objects.first()
    
    if request.method == 'POST':
        data = json.loads(request.body)
        
        if not monitoring:
            monitoring = ContinuousSecurityMonitoring.objects.create()
        
        monitoring.is_enabled = data.get('is_enabled', True)
        monitoring.scan_interval = data.get('scan_interval', 'daily')
        monitoring.auto_fix_critical = data.get('auto_fix_critical', False)
        monitoring.auto_fix_high = data.get('auto_fix_high', False)
        monitoring.auto_fix_medium = data.get('auto_fix_medium', False)
        monitoring.notify_on_detection = data.get('notify_on_detection', True)
        monitoring.notify_email = data.get('notify_email', '')
        monitoring.notify_telegram = data.get('notify_telegram', False)
        monitoring.backup_before_fix = data.get('backup_before_fix', True)
        monitoring.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Configuration mise à jour',
        })
    
    if not monitoring:
        monitoring = ContinuousSecurityMonitoring.objects.create()
    
    return JsonResponse({
        'config': {
            'is_enabled': monitoring.is_enabled,
            'scan_interval': monitoring.scan_interval,
            'auto_fix_critical': monitoring.auto_fix_critical,
            'auto_fix_high': monitoring.auto_fix_high,
            'auto_fix_medium': monitoring.auto_fix_medium,
            'notify_on_detection': monitoring.notify_on_detection,
            'notify_email': monitoring.notify_email,
            'notify_telegram': monitoring.notify_telegram,
            'backup_before_fix': monitoring.backup_before_fix,
            'last_scan': monitoring.last_scan.strftime('%d/%m/%Y %H:%M') if monitoring.last_scan else 'N/A',
            'next_scan': monitoring.next_scan.strftime('%d/%m/%Y %H:%M') if monitoring.next_scan else 'N/A',
        }
    })


# ==========================================
# API STATISTICS
# ==========================================

@login_required
@require_http_methods(["GET"])
def security_statistics(request):
    """Statistiques de sécurité détaillées"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    one_day_ago = timezone.now() - timedelta(days=1)
    seven_days_ago = timezone.now() - timedelta(days=7)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    return JsonResponse({
        'events': {
            'total': SecurityEvent.objects.count(),
            'today': SecurityEvent.objects.filter(created_at__gte=one_day_ago).count(),
            'this_week': SecurityEvent.objects.filter(created_at__gte=seven_days_ago).count(),
            'this_month': SecurityEvent.objects.filter(created_at__gte=thirty_days_ago).count(),
        },
        'vulnerabilities': {
            'total': SecurityVulnerability.objects.count(),
            'critical': SecurityVulnerability.objects.filter(severity='critical').count(),
            'high': SecurityVulnerability.objects.filter(severity='high').count(),
            'fixed': SecurityVulnerability.objects.filter(status='fixed').count(),
            'unfixed': SecurityVulnerability.objects.filter(status__in=['detected', 'confirmed']).count(),
        },
        'alerts': {
            'total': SecurityAlert.objects.count(),
            'active': SecurityAlert.objects.filter(resolved=False).count(),
            'resolved': SecurityAlert.objects.filter(resolved=True).count(),
            'critical': SecurityAlert.objects.filter(priority='critical', resolved=False).count(),
        },
        'honeypot': {
            'total_events': HoneypotEvent.objects.count(),
            'today': HoneypotEvent.objects.filter(created_at__gte=one_day_ago).count(),
            'unique_ips': HoneypotEvent.objects.values('source_ip').distinct().count(),
        },
        'ai_analysis': {
            'total_audits': AISecurityAudit.objects.count(),
            'completed': AISecurityAudit.objects.filter(status='completed').count(),
            'recommendations': AISecurityRecommendation.objects.count(),
        }
    })


# ==========================================
# API CHAT IA CYBERSÉCURITÉ - SOC AVANCÉ
# ==========================================

@login_required
@require_http_methods(["POST"])
def ai_security_chat(request):
    """Endpoint pour le chat IA cybersécurité"""
    
    user_role = getattr(request.user, 'role', '')
    if not (request.user.is_staff or SOCPermissions.check_permission(user_role, 'execute_tasks')):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return JsonResponse({'error': 'Message vide'}, status=400)
        
        ai_engine = AICybersecurityEngine()
        pending_task = request.session.get('ai_pending_task')
        executed_tasks = request.session.get('ai_executed_tasks', [])

        # Confirmation ou annulation d'une tâche en attente
        if pending_task:
            if ai_engine.is_confirmation(user_message):
                result = ai_engine.execute_task(pending_task['command'], user=request.user, simulate=False)
                result['type'] = 'TASK_CONFIRMED'
                result['data']['task_id'] = pending_task['data'].get('task_id')
                result['data']['status'] = 'completed'
                executed_tasks.append({
                    'task_id': pending_task['data'].get('task_id'),
                    'command': pending_task['command'],
                    'task': pending_task['data']['task'],
                    'result': result,
                    'executed_at': timezone.now().isoformat(),
                    'status': 'completed'
                })
                request.session['ai_executed_tasks'] = executed_tasks
                request.session.pop('ai_pending_task', None)
                request.session.modified = True

                return JsonResponse({
                    'success': True,
                    'response': result,
                    'conversation': {
                        'user_id': request.user.id,
                        'user_message': user_message,
                        'ai_response': result['message'],
                        'command_type': result['type'],
                        'timestamp': timezone.now().isoformat(),
                        'confidence': result.get('confidence', 0.8)
                    }
                })

            if ai_engine.is_cancellation(user_message):
                cancelled_response = {
                    'command': pending_task['command'],
                    'type': 'TASK_CANCELLED',
                    'message': 'La tâche en attente a été annulée.',
                    'data': {**pending_task['data'], 'status': 'cancelled'},
                    'timestamp': timezone.now().isoformat(),
                    'confidence': 0.75
                }
                request.session.pop('ai_pending_task', None)
                request.session.modified = True
                return JsonResponse({'success': True, 'response': cancelled_response})

        # Rollback d'une tâche exécutée
        if ai_engine.is_rollback(user_message):
            if not executed_tasks:
                return JsonResponse({
                    'success': True,
                    'response': {
                        'command': user_message,
                        'type': 'TASK_ROLLBACK',
                        'message': 'Aucune exécution récente à annuler.',
                        'data': {'status': 'no_task'},
                        'timestamp': timezone.now().isoformat(),
                        'confidence': 0.6
                    }
                })

            last_task = executed_tasks.pop()
            rollback_message = f"Retour à l'état précédent pour la tâche {last_task['task']['task']}" if last_task else "Rollback effectué."
            request.session['ai_executed_tasks'] = executed_tasks
            request.session.modified = True
            rollback_response = {
                'command': user_message,
                'type': 'TASK_ROLLBACK',
                'message': rollback_message,
                'data': {
                    'rolled_back_task_id': last_task['task_id'],
                    'previous_command': last_task['command'],
                    'status': 'rolled_back'
                },
                'timestamp': timezone.now().isoformat(),
                'confidence': 0.8
            }
            return JsonResponse({'success': True, 'response': rollback_response})

        # Détection d'une tâche à préparer
        parsed_task = ai_engine.parse_task(user_message)
        if parsed_task['task'] != 'unknown':
            pending = ai_engine.create_pending_task(user_message)
            if pending['type'] == 'TASK_PENDING':
                request.session['ai_pending_task'] = pending
                request.session.modified = True
            return JsonResponse({'success': True, 'response': pending})

        # Réponse conversationnelle / analyse normale
        response = ai_engine.ai_process_command(user_message)
        
        conversation_log = {
            'user_id': request.user.id,
            'user_message': user_message,
            'ai_response': response['message'],
            'command_type': response['type'],
            'timestamp': timezone.now().isoformat(),
            'confidence': response.get('confidence', 0.9)
        }
        
        return JsonResponse({
            'success': True,
            'response': response,
            'conversation': conversation_log
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def ai_security_analysis(request):
    """Analyse complète de sécurité par IA"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine
        
        ai_engine = AICybersecurityEngine()
        analysis = ai_engine.analyze_system_security()
        
        return JsonResponse({
            'success': True,
            'analysis': analysis,
            'timestamp': timezone.now().isoformat()
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def ai_port_scan(request):
    """Scan avancé des ports avec IA"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine
        
        ai_engine = AICybersecurityEngine()
        ports_info = ai_engine.analyze_ports()
        
        return JsonResponse({
            'success': True,
            'ports': ports_info,
            'timestamp': timezone.now().isoformat()
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def ai_threat_detection(request):
    """Détection de menaces temps réel"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine
        
        ai_engine = AICybersecurityEngine()
        anomalies = ai_engine.detect_anomalies()
        analysis = ai_engine.analyze_system_security()
        
        return JsonResponse({
            'success': True,
            'threat_score': analysis['threat_score'],
            'threat_level': analysis['threat_level'],
            'anomalies': anomalies,
            'critical_alerts': analysis['critical_alerts'],
            'timestamp': timezone.now().isoformat()
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def ai_system_health(request):
    """État de santé du système en temps réel"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine
        
        ai_engine = AICybersecurityEngine()
        health = ai_engine.get_system_health()
        network = ai_engine.get_network_status()
        connections = ai_engine.get_active_connections()
        
        return JsonResponse({
            'success': True,
            'system_health': health,
            'network_status': network,
            'active_connections': connections,
            'timestamp': timezone.now().isoformat()
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def ai_recommendations(request):
    """Recommandations de sécurité intelligentes"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine
        
        ai_engine = AICybersecurityEngine()
        analysis = ai_engine.analyze_system_security()
        
        return JsonResponse({
            'success': True,
            'recommendations': analysis['recommendations'],
            'threat_score': analysis['threat_score'],
            'ai_confidence': analysis['ai_confidence'],
            'timestamp': timezone.now().isoformat()
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def ai_security_alert(request):
    """Créer une alerte de sécurité basée sur l'IA"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        data = json.loads(request.body)
        
        alert_type = data.get('type', 'SECURITY_ALERT')
        severity = data.get('severity', 'HIGH')
        message = data.get('message', '')
        
        # Créer une alerte
        alert = SecurityAlert.objects.create(
            event_type=alert_type,
            priority=severity,
            description=message,
            ai_generated=True,
            source_type='AI_DETECTION'
        )
        
        return JsonResponse({
            'success': True,
            'alert_id': alert.id,
            'message': 'Alerte créée avec succès'
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def ai_realtime_monitoring(request):
    """Monitoring temps réel avancé"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine
        
        ai_engine = AICybersecurityEngine()
        
        # Collecter toutes les données en temps réel
        realtime_data = {
            'system_health': ai_engine.get_system_health(),
            'network_status': ai_engine.get_network_status(),
            'active_ports': ai_engine.analyze_ports(),
            'anomalies': ai_engine.detect_anomalies(),
            'active_connections': ai_engine.get_active_connections(),
        }
        
        return JsonResponse({
            'success': True,
            'monitoring_data': realtime_data,
            'timestamp': timezone.now().isoformat()
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def soc_dashboard_data(request):
    """Dashboard complet du SOC"""
    
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        from .ai_cybersecurity import AICybersecurityEngine, SOCPermissions
        
        # Vérifier les permissions
        user_role = getattr(request.user, 'security_role', 'read_only')
        
        if not SOCPermissions.check_permission(user_role, 'view_dashboard'):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        ai_engine = AICybersecurityEngine()
        analysis = ai_engine.analyze_system_security()
        
        # Données complètes du SOC
        soc_data = {
            'analysis': analysis,
            'user_role': user_role,
            'role_level': SOCPermissions.get_role_level(user_role),
            'timestamp': timezone.now().isoformat()
        }
        
        return JsonResponse({
            'success': True,
            'soc_data': soc_data
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
