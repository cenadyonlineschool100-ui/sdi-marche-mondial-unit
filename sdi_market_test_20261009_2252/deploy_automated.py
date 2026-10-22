#!/usr/bin/env python
"""
Script d'automatisation du déploiement sur PythonAnywhere
Utilise l'API REST de PythonAnywhere
"""

import requests
import os
import sys
import time
import json
from pathlib import Path

class PythonAnywhereDeployer:
    def __init__(self, username, token):
        self.username = username
        self.token = token
        self.api_url = f"https://www.pythonanywhere.com/api/v0/user/{username}"
        self.headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json"
        }
        self.domain = f"{username}.pythonanywhere.com"
        
    def test_connection(self):
        """Test la connexion à l'API PythonAnywhere"""
        print("🔗 Test de connexion à l'API PythonAnywhere...")
        try:
            response = requests.get(f"{self.api_url}/", headers=self.headers)
            if response.status_code == 200:
                print("✅ Connexion réussie!")
                return True
            else:
                print(f"❌ Erreur: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Erreur de connexion: {str(e)}")
            return False
    
    def list_web_apps(self):
        """Liste les applications web existantes"""
        print("\n📋 Récupération des applications web existantes...")
        try:
            response = requests.get(f"{self.api_url}/webapps/", headers=self.headers)
            if response.status_code == 200:
                apps = response.json()
                if not apps:
                    print("   Aucune application trouvée")
                    return []
                for app in apps:
                    print(f"   - {app.get('domain_name')} ({app.get('python_version')})")
                return apps
            else:
                print(f"❌ Erreur: {response.status_code}")
                return []
        except Exception as e:
            print(f"❌ Erreur: {str(e)}")
            return []
    
    def create_web_app(self, python_version="3.11"):
        """Crée une nouvelle application web Django"""
        print(f"\n🚀 Création de l'application web Django sur {self.domain}...")
        
        # Vérifier si l'app existe déjà
        apps = self.list_web_apps()
        if any(app.get('domain_name') == self.domain for app in apps):
            print(f"⚠️  L'application {self.domain} existe déjà")
            return True
        
        try:
            data = {
                "domain_name": self.domain,
                "python_version": python_version
            }
            response = requests.post(
                f"{self.api_url}/webapps/",
                headers=self.headers,
                json=data
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ Application créée: {self.domain}")
                return True
            else:
                print(f"❌ Erreur: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Erreur: {str(e)}")
            return False
    
    def configure_wsgi(self):
        """Configure le fichier WSGI"""
        print(f"\n⚙️  Configuration du WSGI...")
        
        wsgi_path = f"/home/{self.username}/sdi-market/sdi_market/wsgi.py"
        wsgi_source_path = f"/home/{self.username}/sdi-market/sdi_market/wsgi.py"
        
        wsgi_content = f"""
import os
import sys

path = '/home/{self.username}/sdi-market'
if path not in sys.path:
    sys.path.append(path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'sdi_market.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
"""
        
        try:
            # Créer/modifier le fichier WSGI via l'API
            response = requests.patch(
                f"{self.api_url}/webapps/{self.domain}/",
                headers=self.headers,
                json={"source_directory": f"/home/{self.username}/sdi-market"}
            )
            
            if response.status_code == 200:
                print(f"✅ WSGI configuré")
                return True
            else:
                print(f"⚠️  {response.status_code} - Configurez manuellement le WSGI")
                return False
        except Exception as e:
            print(f"⚠️  Erreur: {str(e)}")
            return False
    
    def set_environment_variables(self):
        """Configure les variables d'environnement"""
        print(f"\n🔧 Configuration des variables d'environnement...")
        
        env_vars = {
            "DJANGO_SETTINGS_MODULE": "sdi_market.settings",
            "DEBUG": "False",
            "ALLOWED_HOSTS": self.domain,
            "SECURE_SSL_REDIRECT": "True",
            "SESSION_COOKIE_SECURE": "True",
            "CSRF_COOKIE_SECURE": "True"
        }
        
        try:
            response = requests.patch(
                f"{self.api_url}/webapps/{self.domain}/",
                headers=self.headers,
                json={"environment_variables": env_vars}
            )
            
            if response.status_code == 200:
                print("✅ Variables d'environnement configurées")
                for key, value in env_vars.items():
                    print(f"   {key}={value}")
                return True
            else:
                print(f"⚠️  {response.status_code}")
                return False
        except Exception as e:
            print(f"⚠️  Erreur: {str(e)}")
            return False
    
    def reload_web_app(self):
        """Recharge l'application web"""
        print(f"\n🔄 Rechargement de l'application web...")
        
        try:
            response = requests.post(
                f"{self.api_url}/webapps/{self.domain}/reload/",
                headers=self.headers
            )
            
            if response.status_code == 200:
                print("✅ Application rechargée")
                return True
            else:
                print(f"⚠️  Erreur: {response.status_code}")
                return False
        except Exception as e:
            print(f"⚠️  Erreur: {str(e)}")
            return False
    
    def setup_static_files(self):
        """Configure les fichiers statiques"""
        print(f"\n📁 Configuration des fichiers statiques...")
        
        try:
            static_mappings = [
                {
                    "url": "/static/",
                    "path": f"/home/{self.username}/sdi-market/staticfiles/"
                },
                {
                    "url": "/media/",
                    "path": f"/home/{self.username}/sdi-market/media/"
                }
            ]
            
            response = requests.patch(
                f"{self.api_url}/webapps/{self.domain}/",
                headers=self.headers,
                json={"static_files": static_mappings}
            )
            
            if response.status_code == 200:
                print("✅ Fichiers statiques configurés")
                return True
            else:
                print(f"⚠️  Configuration statique: {response.status_code}")
                return False
        except Exception as e:
            print(f"⚠️  Erreur: {str(e)}")
            return False
    
    def deploy(self):
        """Exécute le déploiement complet"""
        print("\n" + "=" * 80)
        print(f"🚀 DÉPLOIEMENT AUTOMATISÉ - {self.domain}")
        print("=" * 80)
        
        # Test de connexion
        if not self.test_connection():
            print("\n❌ Impossible de se connecter à PythonAnywhere")
            print("   Vérifiez votre username et token API")
            return False
        
        # Créer l'app
        if not self.create_web_app():
            print("⚠️  Création de l'app échouée, continuons...")
        
        time.sleep(2)
        
        # Configurer WSGI
        if not self.configure_wsgi():
            print("⚠️  Configuration WSGI échouée")
        
        time.sleep(1)
        
        # Configurer les variables d'environnement
        self.set_environment_variables()
        
        time.sleep(1)
        
        # Configurer les fichiers statiques
        self.setup_static_files()
        
        time.sleep(1)
        
        # Recharger l'app
        self.reload_web_app()
        
        print("\n" + "=" * 80)
        print("✅ DÉPLOIEMENT TERMINÉ!")
        print("=" * 80)
        print(f"\n🌐 Votre site est accessible sur: https://{self.domain}/")
        print(f"\n📋 Prochaines étapes manuelles:")
        print(f"   1. Allez sur: https://www.pythonanywhere.com/user/{self.username}/webapps/")
        print(f"   2. Cliquez sur {self.domain}")
        print(f"   3. Configurez le chemin du WSGI: /home/{self.username}/sdi-market/sdi_market/wsgi.py")
        print(f"   4. Cliquez sur 'Reload'")
        print(f"\n💻 Pour cloner et configurer le code via Bash:")
        print(f"   cd /home/{self.username}")
        print(f"   git clone https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git sdi-market")
        print(f"   cd sdi-market")
        print(f"   git checkout feature/ma-modif")
        print(f"   mkvirtualenv --python=/usr/bin/python3.11 sdi-market")
        print(f"   pip install -r requirements.txt")
        print(f"   python manage.py migrate --noinput")
        print(f"   python manage.py collectstatic --noinput")
        
        return True


def main():
    # Configuration
    username = os.getenv('PYTHONANYWHERE_USERNAME') or input("Entrez votre username PythonAnywhere: ").strip()
    token = os.getenv('PYTHONANYWHERE_TOKEN') or input("Entrez votre token API PythonAnywhere: ").strip()
    
    if not username or not token:
        print("❌ Username et token sont requis!")
        sys.exit(1)
    
    # Déploiement
    deployer = PythonAnywhereDeployer(username, token)
    success = deployer.deploy()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
