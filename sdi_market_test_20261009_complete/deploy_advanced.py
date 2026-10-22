#!/usr/bin/env python
"""
Script de déploiement avancé PythonAnywhere - avec gestion du nettoyage de disque
"""

import requests
import json
import time
import sys
import os
from pathlib import Path

class AdvancedPythonAnywhereDeployer:
    def __init__(self, username, token, repo_url, branch="feature/ma-modif", python_version="3.11"):
        self.username = username
        self.token = token
        self.repo_url = repo_url
        self.branch = branch
        self.python_version = python_version
        self.api_url = f"https://www.pythonanywhere.com/api/v0/user/{username}"
        self.headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json"
        }
        self.domain = f"{username}.pythonanywhere.com"
        
    def test_connection(self):
        """Test la connexion à l'API"""
        print("🔗 Test de connexion...")
        try:
            response = requests.get(f"{self.api_url}/", headers=self.headers, timeout=10)
            return response.status_code == 200
        except:
            return False
    
    def check_disk_space(self):
        """Affiche un rapport sur l'espace disque"""
        print("\n📊 Vérification de l'espace disque sur PythonAnywhere:")
        print("   Note: Vous devez manuellement supprimer les fichiers inutiles")
        print("   Allez à: https://www.pythonanywhere.com/user/{}/files/".format(self.username))
        print("   Et supprimez les dossiers/fichiers anciens")
        return True
    
    def get_web_apps(self):
        """Récupère la liste des applications web"""
        try:
            response = requests.get(f"{self.api_url}/webapps/", headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except:
            return []
    
    def create_web_app(self):
        """Crée une nouvelle application web Django"""
        print(f"\n🚀 Création de l'application web: {self.domain}")
        
        # Vérifier si elle existe déjà
        apps = self.get_web_apps()
        if any(app.get('domain_name') == self.domain for app in apps):
            print(f"✅ Application déjà créée: {self.domain}")
            return True
        
        try:
            data = {
                "domain_name": self.domain,
                "python_version": self.python_version
            }
            response = requests.post(
                f"{self.api_url}/webapps/",
                headers=self.headers,
                json=data,
                timeout=10
            )
            return response.status_code in [200, 201]
        except:
            return False
    
    def get_wsgi_file(self):
        """Retourne le chemin du fichier WSGI"""
        wsgi_path = f"/var/www/{self.domain.replace('.', '_')}_wsgi.py"
        return wsgi_path
    
    def get_wsgi_content(self):
        """Retourne le contenu du fichier WSGI Django"""
        wsgi_content = f"""import os
import sys

# Ajouter le projet au chemin Python
path = '/home/{self.username}/sdi-market'
if path not in sys.path:
    sys.path.append(path)

# Configurer Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
os.environ['DJANGO_SECRET_KEY'] = 'django-insecure-change-me'
os.environ['DEBUG'] = 'False'
os.environ['ALLOWED_HOSTS'] = '{self.domain}'

# Initialiser Django
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
"""
        return wsgi_content
    
    def generate_deployment_plan(self):
        """Génère un plan de déploiement détaillé"""
        print("\n" + "=" * 80)
        print("📋 PLAN DE DÉPLOIEMENT COMPLET")
        print("=" * 80)
        
        print(f"""
🔧 Configuration Required:

1. NETTOYAGE DE DISQUE (IMPORTANT!)
   ================================
   ⚠️  Votre disque PythonAnywhere est PLEIN (512MB/512MB)
   
   Actions à faire manuellement:
   a) Allez sur: https://www.pythonanywhere.com/user/{self.username}/files/
   b) Supprimez les dossiers/fichiers inutiles:
      - sdi_site (ancienne version)
      - sdi_site_new (ancienne version)
      - mysite (ancien projet)
      - db.sqlite3.production.backup (ancienne base de données)
      - Autres fichiers inutiles
   c) Cela devrait libérer ~150-200MB


2. CONFIGURER LE PROJET SUR PythonAnywhere
   =======================================
   
   a) Via la Console Bash (https://www.pythonanywhere.com/user/{self.username}/consoles/):
      
      cd ~
      git clone {self.repo_url} sdi-market
      cd sdi-market
      git checkout {self.branch}
      mkvirtualenv --python=/usr/bin/python{self.python_version} sdi-market
      pip install -r requirements.txt
      python manage.py migrate --noinput
      python manage.py collectstatic --noinput
      deactivate


3. CONFIGURER L'APPLICATION WEB
   ============================
   
   a) Allez sur: https://www.pythonanywhere.com/user/{self.username}/webapps/
   
   b) Cliquez sur: {self.domain}
   
   c) Configurez le WSGI:
      - Source directory: /home/{self.username}/sdi-market
      - WSGI configuration file: /var/www/{self.domain.replace('.', '_')}_wsgi.py
      
   d) Remplacez le contenu du fichier WSGI par:
{self.get_wsgi_content()}
      
   e) Configurez les fichiers statiques:
      - URL: /static/  → Directory: /home/{self.username}/sdi-market/staticfiles/
      - URL: /media/   → Directory: /home/{self.username}/sdi-market/media/
      
   f) Configurez les variables d'environnement:
      - DJANGO_SETTINGS_MODULE=sdi_market.settings
      - DEBUG=False
      - ALLOWED_HOSTS={self.domain}
      - SECURE_SSL_REDIRECT=True
      - SESSION_COOKIE_SECURE=True
      - CSRF_COOKIE_SECURE=True


4. ACTIVER L'APPLICATION
   ====================
   
   a) Retournez à la page Web apps
   
   b) Cliquez sur le bouton "Reload" (🔄)
   
   c) Attendez que le statut change à "running" (vert)
   
   d) Visitez: https://{self.domain}


5. DÉPANNAGE (SI ERREURS)
   =====================
   
   - Consultez l'error log: https://www.pythonanywhere.com/user/{self.username}/webapps/#tab_id_{self.domain.replace('.', '_')}
   - Vérifiez les permissions des fichiers
   - Vérifiez la syntaxe du fichier WSGI


📍 Votre site sera bientôt sur: https://{self.domain}/

========================================================
✅ PLAN PRÊT - Suivez les étapes ci-dessus manuellement
========================================================
""")
        return True
    
    def deploy(self):
        """Lance le déploiement"""
        print("\n" + "=" * 80)
        print(f"🚀 DÉPLOIEMENT ADVANCED - {self.domain}")
        print("=" * 80)
        
        # Test connexion
        if not self.test_connection():
            print("\n❌ Impossible de se connecter à l'API PythonAnywhere")
            print("   Vérifiez le username et token")
            return False
        
        print("✅ Connexion réussie!")
        
        # Vérifier l'espace disque
        self.check_disk_space()
        
        # Générer le plan
        self.generate_deployment_plan()
        
        return True


def main():
    # Configuration
    username = os.getenv('PYTHONANYWHERE_USERNAME') or input("Entrez votre username PythonAnywhere: ").strip()
    token = os.getenv('PYTHONANYWHERE_TOKEN') or input("Entrez votre token API PythonAnywhere (laissez vide si pas de token): ").strip()
    
    if not username:
        print("❌ Username requis!")
        sys.exit(1)
    
    repo_url = "https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git"
    branch = "feature/ma-modif"
    
    deployer = AdvancedPythonAnywhereDeployer(username, token, repo_url, branch)
    success = deployer.deploy()
    
    if not success and not token:
        print("\n💡 Conseil: Obtenir un token API:")
        print(f"   1. Allez sur: https://www.pythonanywhere.com/user/{username}/account/")
        print("   2. Cliquez sur 'API token'")
        print("   3. Générez un nouveau token et utilisez-le")
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
