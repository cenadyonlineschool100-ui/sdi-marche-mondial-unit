# AI Cybersecurity System - Advanced Intelligence for SOC
import json
import socket
import subprocess
import re
import psutil
import datetime
import uuid
from typing import Dict, List, Any, Tuple
import threading
import platform
import hashlib

class AICybersecurityEngine:
    """
    Moteur IA avancé pour la cybersécurité
    Analyseur de menaces, Scanner de ports, Détecteur d'anomalies
    """
    
    def __init__(self):
        self.threat_score = 0.0
        self.threat_history = []
        self.active_ports = {}
        self.system_metrics = {}
        self.detected_anomalies = []
        self.blocked_ips = set()
        self.honeypot_events = []
        self.security_events_log = []
        self.ai_confidence = 0.0
        self.threat_level = "SÛRE"  # SÛRE, BASSE, MOYEN, HAUTE, CRITIQUE
        
    def analyze_system_security(self) -> Dict[str, Any]:
        """Analyse complète de la sécurité du système"""
        analysis = {
            "timestamp": datetime.datetime.now().isoformat(),
            "threat_score": 0.0,
            "threat_level": "SÛRE",
            "ai_confidence": 0.0,
            "system_health": self.get_system_health(),
            "network_status": self.get_network_status(),
            "port_status": self.analyze_ports(),
            "active_connections": self.get_active_connections(),
            "anomalies": self.detect_anomalies(),
            "recommendations": [],
            "critical_alerts": []
        }
        
        # Calcul du score de menace
        analysis["threat_score"] = self.calculate_threat_score(analysis)
        analysis["threat_level"] = self.get_threat_level(analysis["threat_score"])
        analysis["ai_confidence"] = self.calculate_ai_confidence()
        
        # Générer des recommandations
        analysis["recommendations"] = self.generate_recommendations(analysis)
        analysis["critical_alerts"] = self.get_critical_alerts(analysis)
        
        self.threat_score = analysis["threat_score"]
        self.threat_level = analysis["threat_level"]
        self.ai_confidence = analysis["ai_confidence"]
        
        return analysis
    
    def get_system_health(self) -> Dict[str, Any]:
        """Récupère l'état de santé du système"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                "cpu_usage": cpu_percent,
                "memory_usage": memory.percent,
                "memory_available": memory.available / (1024**3),  # GB
                "disk_usage": disk.percent,
                "uptime": self.get_system_uptime(),
                "status": "NORMAL" if cpu_percent < 80 and memory.percent < 85 else "ALERTER"
            }
        except Exception as e:
            return {"error": str(e), "status": "INCONNU"}
    
    def get_system_uptime(self) -> str:
        """Récupère le temps de fonctionnement du système"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(['powershell', '-c', '$uptime = (Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime; $uptime.Days, $uptime.Hours, $uptime.Minutes'], 
                                      capture_output=True, text=True, timeout=5)
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    return f"{parts[0]} j {parts[1]} h {parts[2]} m"
            else:
                result = subprocess.run(['uptime', '-p'], capture_output=True, text=True, timeout=5)
                return result.stdout.strip()
        except:
            return "Indéterminé"
    
    def get_network_status(self) -> Dict[str, Any]:
        """Analyse l'état du réseau"""
        try:
            net_io = psutil.net_io_counters()
            connections = psutil.net_connections()
            
            established = len([c for c in connections if c.status == 'ESTABLISHED'])
            listening = len([c for c in connections if c.status == 'LISTEN'])
            
            return {
                "bytes_sent": net_io.bytes_sent / (1024**2),  # MB
                "bytes_received": net_io.bytes_received / (1024**2),  # MB
                "packets_sent": net_io.packets_sent,
                "packets_received": net_io.packets_received,
                "errors": net_io.errin + net_io.errout,
                "dropped": net_io.dropin + net_io.dropout,
                "established_connections": established,
                "listening_ports": listening,
                "network_status": "NORMAL" if net_io.errin + net_io.errout < 100 else "ANORMAL"
            }
        except Exception as e:
            return {"error": str(e), "network_status": "INCONNU"}
    
    def analyze_ports(self) -> Dict[str, Any]:
        """Analyse les ports ouverts et en écoute"""
        ports_info = {
            "total_listening": 0,
            "dangerous_ports": [],
            "ports_list": [],
            "risk_level": "BAS"
        }
        
        try:
            connections = psutil.net_connections()
            
            dangerous_port_numbers = {
                22: "SSH (Accès distant)",
                23: "Telnet (Non sécurisé)",
                3389: "RDP",
                445: "SMB (Partage fichiers)",
                3306: "MySQL",
                5432: "PostgreSQL",
                27017: "MongoDB",
                6379: "Redis"
            }
            
            port_map = {}
            
            for conn in connections:
                if conn.status == 'LISTEN' and conn.laddr.port:
                    port = conn.laddr.port
                    if port not in port_map:
                        port_map[port] = {
                            "port": port,
                            "state": "OUVERT",
                            "service": dangerous_port_numbers.get(port, "Service inconnu"),
                            "risk": "CRITIQUE" if port in dangerous_port_numbers else "BAS",
                            "activity": "Actif" if conn.pid else "Inactif"
                        }
                        ports_info["total_listening"] += 1
                        
                        if port in dangerous_port_numbers:
                            ports_info["dangerous_ports"].append(port)
            
            ports_info["ports_list"] = list(port_map.values())
            
            if len(ports_info["dangerous_ports"]) > 3:
                ports_info["risk_level"] = "CRITIQUE"
            elif len(ports_info["dangerous_ports"]) > 1:
                ports_info["risk_level"] = "MOYEN"
            else:
                ports_info["risk_level"] = "BAS"
        
        except Exception as e:
            ports_info["error"] = str(e)
        
        return ports_info
    
    def get_active_connections(self) -> List[Dict[str, Any]]:
        """Récupère les connexions réseau actives"""
        connections = []
        try:
            conns = psutil.net_connections()
            established = [c for c in conns if c.status == 'ESTABLISHED']
            
            for conn in established[:10]:  # Limiter à 10
                try:
                    conn_info = {
                        "laddr": f"{conn.laddr.ip}:{conn.laddr.port}",
                        "raddr": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                        "status": conn.status,
                        "type": conn.type
                    }
                    connections.append(conn_info)
                except:
                    pass
        except Exception as e:
            pass
        
        return connections
    
    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Détecte les anomalies de sécurité"""
        anomalies = []
        
        try:
            system_health = self.get_system_health()
            network_status = self.get_network_status()
            ports = self.analyze_ports()
            
            # Anomalie 1: CPU élevé
            if system_health.get("cpu_usage", 0) > 80:
                anomalies.append({
                    "type": "CPU_ÉLEVÉ",
                    "severity": "HAUTE",
                    "description": f"Usage CPU anormal: {system_health['cpu_usage']:.1f}%",
                    "recommendation": "Vérifier les processus en arrière-plan"
                })
            
            # Anomalie 2: Mémoire critique
            if system_health.get("memory_usage", 0) > 85:
                anomalies.append({
                    "type": "MÉMOIRE_CRITIQUE",
                    "severity": "HAUTE",
                    "description": f"Mémoire critique: {system_health['memory_usage']:.1f}%",
                    "recommendation": "Redémarrer les services non essentiels"
                })
            
            # Anomalie 3: Erreurs réseau anormales
            if network_status.get("errors", 0) > 50:
                anomalies.append({
                    "type": "ERREURS_RÉSEAU",
                    "severity": "MOYEN",
                    "description": f"Erreurs réseau détectées: {network_status['errors']}",
                    "recommendation": "Vérifier la stabilité de la connexion"
                })
            
            # Anomalie 4: Trop de ports ouverts
            if ports.get("risk_level") == "CRITIQUE":
                anomalies.append({
                    "type": "PORTS_OUVERTS_EXCESSIFS",
                    "severity": "CRITIQUE",
                    "description": f"Ports dangereux détectés: {ports['dangerous_ports']}",
                    "recommendation": "Fermer les ports non essentiels"
                })
        
        except Exception as e:
            pass
        
        self.detected_anomalies = anomalies
        return anomalies
    
    def calculate_threat_score(self, analysis: Dict) -> float:
        """Calcule le score de menace global"""
        score = 0.0
        max_score = 100.0
        
        # Score basé sur les anomalies
        anomalies_weight = len(analysis.get("anomalies", [])) * 15
        score += min(anomalies_weight, 40)
        
        # Score basé sur les ports dangereux
        ports = analysis.get("port_status", {})
        if ports.get("risk_level") == "CRITIQUE":
            score += 30
        elif ports.get("risk_level") == "MOYEN":
            score += 15
        
        # Score basé sur la santé du système
        health = analysis.get("system_health", {})
        if health.get("status") == "ALERTER":
            score += 10
        
        # Score basé sur les erreurs réseau
        network = analysis.get("network_status", {})
        if network.get("network_status") == "ANORMAL":
            score += 15
        
        return min(score, max_score)
    
    def get_threat_level(self, score: float) -> str:
        """Détermine le niveau de menace"""
        if score < 20:
            return "SÛRE"
        elif score < 40:
            return "BASSE"
        elif score < 60:
            return "MOYEN"
        elif score < 80:
            return "HAUTE"
        else:
            return "CRITIQUE"
    
    def calculate_ai_confidence(self) -> float:
        """Calcule la confiance de l'IA"""
        # Base de 90% de confiance + ajustements
        base_confidence = 90.0
        
        # Diminuer la confiance en fonction du nombre d'anomalies
        anomaly_penalty = len(self.detected_anomalies) * 5
        
        confidence = base_confidence - anomaly_penalty
        return max(min(confidence, 99.0), 50.0)
    
    def generate_recommendations(self, analysis: Dict) -> List[Dict[str, Any]]:
        """Génère des recommandations de sécurité"""
        recommendations = []
        
        # Recommandations basées sur les anomalies
        for anomaly in analysis.get("anomalies", []):
            recommendations.append({
                "priority": "HAUTE" if anomaly["severity"] in ["HAUTE", "CRITIQUE"] else "MOYEN",
                "action": anomaly.get("recommendation", "Vérifier"),
                "type": anomaly["type"]
            })
        
        # Recommandations générales
        if analysis["threat_score"] > 60:
            recommendations.append({
                "priority": "CRITIQUE",
                "action": "Vérifier immédiatement la sécurité du système",
                "type": "ALERTE_GÉNÉRALE"
            })
        
        recommendations.append({
            "priority": "BAS",
            "action": "Mettre à jour régulièrement les firewall et IDS",
            "type": "MAINTENANCE"
        })
        
        return recommendations[:5]  # Limiter à 5 recommandations
    
    def get_critical_alerts(self, analysis: Dict) -> List[Dict[str, Any]]:
        """Récupère les alertes critiques"""
        alerts = []
        
        for anomaly in analysis.get("anomalies", []):
            if anomaly["severity"] in ["HAUTE", "CRITIQUE"]:
                alerts.append({
                    "type": anomaly["type"],
                    "severity": anomaly["severity"],
                    "message": anomaly["description"],
                    "timestamp": datetime.datetime.now().isoformat(),
                    "status": "NOUVEAU"
                })
        
        return alerts
    
    def think_and_analyze(self, command: str, analysis: Dict = None) -> Dict[str, Any]:
        """Réfléchit au système et construit une analyse détaillée avant de répondre."""
        analysis = analysis or self.analyze_system_security()
        command = command.lower().strip()
        insights = []

        insights.append("J'analyse en profondeur l'état du système et cherche les axes d'amélioration.")
        if analysis["threat_score"] >= 80:
            insights.append("Le score de menace est élevé : je identifie les principaux vecteurs de risque.")
        elif analysis["threat_score"] >= 40:
            insights.append("Le taux de menace est moyen : je vérifie les ports et le trafic réseau.")
        else:
            insights.append("Le système est globalement stable, mais je conserve une vigilance sur les alertes et les ports ouverts.")

        if analysis["system_health"].get("status") != "NORMAL":
            insights.append("La santé du système est dégradée, je recommande une action prioritaire.")

        if analysis["port_status"].get("risk_level") in ["MOYEN", "CRITIQUE"]:
            insights.append("Les ports à risque sont ouverts et doivent être revus.")

        if analysis["network_status"].get("network_status") == "ANORMAL":
            insights.append("Le réseau montre des erreurs : je conseille une vérification plus approfondie.")

        response_text = (
            "Je réfléchis au système avant de répondre. "
            f"Score menace {analysis['threat_score']:.1f}, niveau {analysis['threat_level']}. "
            "Voici mes conclusions préliminaires."
        )

        return {
            "command": command,
            "type": "ANALYTICAL_RESPONSE",
            "message": response_text,
            "data": {
                "insights": insights,
                "analysis_summary": {
                    "threat_score": analysis.get("threat_score", 0.0),
                    "threat_level": analysis.get("threat_level", "SÛRE"),
                    "ai_confidence": analysis.get("ai_confidence", 0.0)
                }
            },
            "timestamp": datetime.datetime.now().isoformat(),
            "confidence": 0.85
        }

    def execute_task(self, command: str, user: Any = None, simulate: bool = True) -> Dict[str, Any]:
        """Exécute une tâche SOC sécurisée basée sur une commande utilisateur."""
        command = command.lower().strip()
        task = self.parse_task(command)
        response = {
            "command": command,
            "type": "TASK_EXECUTION",
            "message": "Tâche traitée.",
            "data": {},
            "timestamp": datetime.datetime.now().isoformat(),
            "confidence": 0.8
        }

        if task["task"] == "close_port":
            port = task.get("port")
            if port:
                response["message"] = f"Je simule la fermeture du port {port}. Vérifiez le pare-feu pour appliquer le changement en production."
                response["data"] = {"task": "close_port", "port": port, "status": "SIMULÉ"}
            else:
                response["message"] = "Je peux fermer un port, mais je n'ai pas trouvé de numéro de port valide."
                response["data"] = {"task": "close_port", "status": "FAILED"}

        elif task["task"] == "block_ip":
            ip = task.get("ip")
            if ip:
                if not simulate:
                    self.blocked_ips.add(ip)
                self.security_events_log.append({
                    "event": "IP_BLOCKED",
                    "ip": ip,
                    "timestamp": datetime.datetime.now().isoformat()
                })
                response["message"] = f"IP {ip} ajoutée à la liste de blocage simulée."
                response["data"] = {"task": "block_ip", "ip": ip, "status": "SIMULÉ" if simulate else "APPLIQUÉ"}
            else:
                response["message"] = "Je peux bloquer une IP, mais je n'ai pas identifié d'adresse valide."
                response["data"] = {"task": "block_ip", "status": "FAILED"}

        elif task["task"] == "restart_service":
            service_name = task.get("service", "service")
            response["message"] = f"Je simule le redémarrage du service {service_name}. Confirmez l'action sur le système réel."
            response["data"] = {"task": "restart_service", "service": service_name, "status": "SIMULÉ" if simulate else "APPLIQUÉ"}

        elif task["task"] == "theme_apply":
            theme_name = task.get("theme_name")
            if not theme_name:
                response["message"] = "Je peux appliquer un thème, mais je n'ai pas identifié le nom du thème."
                response["data"] = {"task": "theme_apply", "status": "FAILED"}
            elif user and hasattr(user, 'profile'):
                try:
                    if not simulate:
                        user.profile.theme_name = theme_name
                        user.profile.save()
                    response["message"] = f"Je simule l'application du thème '{theme_name}'." if simulate else f"Thème '{theme_name}' appliqué au profil utilisateur."
                    response["data"] = {"task": "theme_apply", "theme_name": theme_name, "status": "SIMULÉ" if simulate else "APPLIQUÉ"}
                except Exception:
                    response["message"] = "Impossible d'appliquer le thème sur le profil utilisateur."
                    response["data"] = {"task": "theme_apply", "status": "FAILED"}
            else:
                response["message"] = "Je peux appliquer un thème mais je ne peux pas accéder au profil utilisateur."
                response["data"] = {"task": "theme_apply", "status": "FAILED"}

        elif task["task"] == "theme_color_change":
            color = task.get("color")
            if color and user and hasattr(user, 'profile'):
                try:
                    settings = user.profile.theme_settings or {}
                    settings["primary_color"] = color
                    user.profile.theme_settings = settings
                    if not simulate:
                        user.profile.save()
                    response["message"] = f"Je simule le changement de couleur principale en {color}." if simulate else f"Couleur principale changée en {color}."
                    response["data"] = {"task": "theme_color_change", "color": color, "status": "SIMULÉ" if simulate else "APPLIQUÉ"}
                except Exception:
                    response["message"] = "Impossible de changer la couleur principale."
                    response["data"] = {"task": "theme_color_change", "status": "FAILED"}
            else:
                response["message"] = "Je peux changer une couleur, mais je n'ai pas identifié une couleur valide."
                response["data"] = {"task": "theme_color_change", "status": "FAILED"}

        elif task["task"] == "analysis_request":
            return self.think_and_analyze(command)

        else:
            response["message"] = (
                "Je comprends que vous souhaitez exécuter une tâche, mais je ne reconnais pas celle-ci. "
                "Essayez : 'Fermer port 3389', 'Bloquer IP 192.168.0.10', 'Redémarrer service apache', "
                "ou demandez une analyse détaillée."
            )
            response["confidence"] = 0.65
            response["data"] = {"task": "unknown"}

        return response

    def parse_task(self, command: str) -> Dict[str, Any]:
        """Analyse la commande pour détecter l'intention de tâche."""
        command = command.lower().strip()
        if any(word in command for word in ["fermer port", "bloquer port", "close port", "shut port"]):
            port_match = re.search(r"(\d{2,5})", command)
            return {"task": "close_port", "port": int(port_match.group(1)) if port_match else None}
        if any(word in command for word in ["bloquer ip", "block ip", "interdire ip"]):
            ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", command)
            return {"task": "block_ip", "ip": ip_match.group(1) if ip_match else None}
        if any(word in command for word in ["redémarrer service", "restart service", "reboot service"]):
            service_match = re.search(r"service\s+(\w+)", command)
            return {"task": "restart_service", "service": service_match.group(1) if service_match else "service"}
        color_match = re.search(r"#([0-9a-fA-F]{6})", command)
        if color_match:
            return {"task": "theme_color_change", "color": f"#{color_match.group(1)}"}
        if any(word in command for word in ["appliquer thème", "appliquer le thème", "theme", "thème", "ui design", "design ui", "interface", "couleur"]):
            theme_match = re.search(r"th[eè]me(?:\s+(?:de\s+)?)?([\w\-]+)", command)
            if theme_match:
                return {"task": "theme_apply", "theme_name": theme_match.group(1)}
            return {"task": "theme_apply", "theme_name": None}
        if any(word in command for word in ["analyse approfondie", "réfléchir", "analyse détaillée", "explique-moi", "explique"]):
            return {"task": "analysis_request"}
        return {"task": "unknown"}

    def create_pending_task(self, command: str) -> Dict[str, Any]:
        """Prépare une tâche et demande confirmation avant exécution."""
        task = self.parse_task(command)
        task_id = str(uuid.uuid4())
        response = {
            "command": command,
            "type": "TASK_PENDING",
            "message": "Je peux préparer cette tâche pour vous. Confirmez-vous l’exécution ? (oui/non)",
            "data": {
                "task_id": task_id,
                "task": task,
                "status": "pending"
            },
            "timestamp": datetime.datetime.now().isoformat(),
            "confidence": 0.78
        }

        if task["task"] == "unknown":
            response["type"] = "TASK_UNKNOWN"
            response["message"] = (
                "Je n’ai pas reconnu la tâche demandée. Essayez une commande comme 'Fermer port 3389', "
                "'Bloquer IP 192.168.0.10', 'Redémarrer service apache', ou 'Appliquer thème cyber-ice'."
            )
            response["data"]["status"] = "failed"

        return response

    def is_confirmation(self, command: str) -> bool:
        return any(word in command.lower() for word in ["oui", "yes", "confirme", "confirm", "d'accord", "ok"])

    def is_cancellation(self, command: str) -> bool:
        return any(word in command.lower() for word in ["non", "cancel", "annule", "stop", "abandonne"])

    def is_rollback(self, command: str) -> bool:
        return any(word in command.lower() for word in ["annule", "rollback", "retourne", "revenir", "undo"])

    def get_general_response(self, command: str, analysis: Dict = None) -> Dict[str, Any]:
        """Produit une réponse conversationnelle aux questions ouvertes."""
        analysis = analysis or self.analyze_system_security()
        command = command.lower().strip()
        response_text = ""
        response_type = "CONVERSATION"
        confidence = 0.75

        if any(word in command for word in ["qui", "quoi", "où", "quand", "comment", "pourquoi", "est-ce que", "peux", "puis-je"]):
            if "comment" in command and "fonctionne" in command:
                response_text = "Le système surveille en continu la santé, le trafic réseau et les ports ouverts. Je peux vous expliquer chaque module si vous le souhaitez."
            elif "pourquoi" in command or "raison" in command:
                response_text = "Je réponds aux questions sur l'état du système et les risques. Si une information n'est pas précise, je peux analyser davantage ou proposer des recommandations."
            elif "qui" in command or "quoi" in command:
                response_text = "Je suis l'assistant IA du SOC. Je peux discuter des analyses, des ports, des menaces et des recommandations de sécurité."
            else:
                response_text = "Je peux discuter du système, des risques et des recommandations. Posez-moi une question précise ou demandez une analyse générale."
        elif any(word in command for word in ["système", "statut", "état", "performance"]):
            health = analysis.get("system_health", {})
            response_text = f"L'état actuel montre CPU {health.get('cpu_usage', 0):.1f}% et mémoire {health.get('memory_usage', 0):.1f}%. Le score de menace est {analysis['threat_score']:.1f}."
            confidence = 0.85
        elif any(word in command for word in ["risque", "danger", "menace", "vulnérabilité", "vulnerabilite"]):
            response_text = f"Actuellement, le score de menace est {analysis['threat_score']:.1f} et le niveau est {analysis['threat_level']}. Je recommande de vérifier les ports ouverts et de renforcer le pare-feu si nécessaire."
            confidence = 0.85
        else:
            response_text = "Je suis prêt à discuter de votre système. Posez-moi une question sur la sécurité, les performances, les ports, ou demandez une aide générale."
            confidence = 0.7

        return {
            "command": command,
            "type": response_type,
            "message": response_text,
            "data": {
                "analysis_summary": {
                    "threat_score": analysis.get("threat_score", 0.0),
                    "threat_level": analysis.get("threat_level", "SÛRE"),
                    "ai_confidence": analysis.get("ai_confidence", 0.0)
                }
            },
            "timestamp": datetime.datetime.now().isoformat(),
            "confidence": confidence
        }

    def ai_process_command(self, command: str, context: Dict = None) -> Dict[str, Any]:
        """
        Traite les commandes de l'utilisateur avec intelligence IA
        """
        command = command.lower().strip()
        
        response = {
            "command": command,
            "type": "INFO",
            "message": "",
            "data": {},
            "timestamp": datetime.datetime.now().isoformat(),
            "confidence": 0.9
        }
        
        # Réponses de salutation
        if any(word in command for word in ["bonjour", "bonsoir", "salut", "coucou", "hey"]):
            greeting = "Bonjour"
            if "bonsoir" in command:
                greeting = "Bonsoir"
            elif "salut" in command or "coucou" in command or "hey" in command:
                greeting = "Salut"
            response["type"] = "GREETING"
            response["message"] = f"{greeting} ! Comment puis-je vous aider aujourd'hui ?"
            response["confidence"] = 0.95
            return response
        
        # Analyse de sécurité
        if any(word in command for word in ["analyse", "sécurité", "check", "analyser"]):
            analysis = self.analyze_system_security()
            response["type"] = "ANALYSIS"
            response["message"] = f"Analyse complète: Score menace {analysis['threat_score']:.1f}, Niveau: {analysis['threat_level']}"
            response["data"] = analysis
        
        # Exécuter une tâche
        elif any(word in command for word in ["exécute", "execute", "fais", "effectue", "réalise", "lance"]):
            response = self.execute_task(command)

        # Réflexion et analyse avancée
        elif any(word in command for word in ["réfléchir", "penser", "analyse approfondie", "analyse détaillée", "explique-moi", "explique"]):
            response = self.think_and_analyze(command)

        # Scan ports
        elif any(word in command for word in ["scan", "ports", "port", "ouvert"]):
            ports = self.analyze_ports()
            response["type"] = "PORT_SCAN"
            response["message"] = f"Scan ports: {ports['total_listening']} ports en écoute, Risque: {ports['risk_level']}"
            response["data"] = ports
        
        # Vérifier firewall
        elif any(word in command for word in ["firewall", "feu", "pare-feu"]):
            response["type"] = "FIREWALL_CHECK"
            response["message"] = "Firewall: Actif et opérationnel ✓"
            response["data"] = {"firewall_status": "ACTIF", "rules": 150, "blocked_ips": len(self.blocked_ips)}
        
        # Analyse trafic réseau
        elif any(word in command for word in ["trafic", "réseau", "network", "traffic"]):
            network = self.get_network_status()
            response["type"] = "NETWORK_ANALYSIS"
            response["message"] = f"Trafic réseau: {network.get('bytes_sent', 0):.2f}MB envoyés, {network.get('bytes_received', 0):.2f}MB reçus"
            response["data"] = network
        
        # État serveur
        elif any(word in command for word in ["serveur", "server", "état", "status"]):
            health = self.get_system_health()
            response["type"] = "SERVER_STATUS"
            response["message"] = f"Serveur: CPU {health.get('cpu_usage', 0):.1f}%, Mémoire {health.get('memory_usage', 0):.1f}%"
            response["data"] = health
        
        # Détection de menaces
        elif any(word in command for word in ["menace", "threat", "détecte", "détection"]):
            analysis = self.analyze_system_security()
            response["type"] = "THREAT_DETECTION"
            response["message"] = f"Menaces détectées: {len(analysis.get('anomalies', []))} anomalies, Score: {analysis['threat_score']:.1f}"
            response["data"] = {"anomalies": analysis.get("anomalies", []), "threat_score": analysis["threat_score"]}
        
        # Vérifier vulnérabilités
        elif any(word in command for word in ["vulnérabilité", "vuln", "vulnerability", "faiblesse"]):
            response["type"] = "VULNERABILITY_CHECK"
            response["message"] = "Scan vulnérabilités: Recherche en cours..."
            response["data"] = {"vulnerabilities": []}
        
        # Analyser logs
        elif any(word in command for word in ["log", "logs", "journal", "événements"]):
            response["type"] = "LOG_ANALYSIS"
            response["message"] = f"Logs analysés: {len(self.security_events_log)} événements importants"
            response["data"] = {"log_count": len(self.security_events_log), "recent_logs": self.security_events_log[-5:]}
        
        # Recommandations
        elif any(word in command for word in ["conseil", "recommandation", "recommande", "aide"]):
            analysis = self.analyze_system_security()
            response["type"] = "RECOMMENDATIONS"
            response["message"] = f"{len(analysis['recommendations'])} recommandations disponibles"
            response["data"] = {"recommendations": analysis["recommendations"]}

        # Exécuter une tâche
        elif any(word in command for word in ["exécute", "execute", "fais", "effectue", "réalise", "lance"]):
            response = self.execute_task(command)

        # Réflexion et analyse avancée
        elif any(word in command for word in ["réfléchir", "penser", "analyse approfondie", "analyse détaillée", "explique-moi", "explique"]):
            response = self.think_and_analyze(command)

        # Conversation ouverte et questions non définies
        else:
            analysis = self.analyze_system_security()
            general = self.get_general_response(command, analysis)
            response = general
        
        return response


class SOCPermissions:
    """Gestion des permissions pour le SOC"""
    
    ROLES = {
        "super_admin": {
            "level": 100,
            "permissions": ["view_all", "manage_all", "edit_ai", "generate_reports"],
            "description": "Super administrateur"
        },
        "ai_admin": {
            "level": 95,
            "permissions": ["view_all", "manage_all", "edit_ai", "generate_reports", "apply_theme", "execute_tasks"],
            "description": "Administrateur IA"
        },
        "security_admin": {
            "level": 80,
            "permissions": ["view_all", "manage_security", "edit_alerts", "generate_reports"],
            "description": "Admin sécurité"
        },
        "soc_analyst": {
            "level": 60,
            "permissions": ["view_all", "manage_alerts", "view_reports"],
            "description": "Analyste SOC"
        },
        "read_only": {
            "level": 20,
            "permissions": ["view_dashboard"],
            "description": "Lecture seule"
        }
    }
    
    @staticmethod
    def check_permission(user_role: str, required_permission: str) -> bool:
        """Vérifie si l'utilisateur a la permission"""
        role = SOCPermissions.ROLES.get(user_role.lower())
        if not role:
            return False
        return required_permission in role["permissions"]
    
    @staticmethod
    def get_role_level(user_role: str) -> int:
        """Récupère le niveau d'accès du rôle"""
        role = SOCPermissions.ROLES.get(user_role.lower())
        return role["level"] if role else 0
