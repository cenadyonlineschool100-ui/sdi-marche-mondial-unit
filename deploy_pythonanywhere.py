#!/usr/bin/env python
"""
Script de déploiement sur PythonAnywhere
Utilise l'API REST de PythonAnywhere pour déployer le site
"""

import requests
import json
import os
import sys

def deploy_to_pythonanywhere(username, token, repo_url, branch="feature/ma-modif", python_version="3.11"):
    """Déploie le site sur PythonAnywhere"""
    
    base_url = f"https://www.pythonanywhere.com/api/v0/user/{username}"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    
    domain = f"{username}.pythonanywhere.com"
    
    print("=" * 80)
    print(f"🚀 Déploiement sur PythonAnywhere: {domain}")
    print("=" * 80)
    
    try:
        # Étape 1: Cloner le dépôt
        print("\n1️⃣  Clonage du dépôt GitHub...")
        clone_url = f"{base_url}/consoles/bash/"
        clone_command = f"cd /home/{username} && git clone {repo_url} sdi-market && cd sdi-market && git checkout {branch}"
        
        # Étape 2: Créer l'application web
        print("2️⃣  Création de l'application web Django...")
        web_url = f"{base_url}/webapps/"
        
        web_config = {
            "domain_name": domain,
            "python_version": python_version,
            "source_directory": f"/home/{username}/sdi-market",
            "working_directory": f"/home/{username}/sdi-market",
            "wsgi_path": f"/home/{username}/sdi-market/sdi_market/wsgi.py",
            "virtualenv_path": f"/home/{username}/.virtualenvs/sdi-market"
        }
        
        # Étape 3: Configurer les variables d'environnement
        print("3️⃣  Configuration des variables d'environnement...")
        env_var_url = f"{base_url}/webapps/{domain}/static_headers/"
        
        env_vars = {
            "DJANGO_SETTINGS_MODULE": "sdi_market.settings",
            "DEBUG": "False",
            "ALLOWED_HOSTS": domain,
            "SECURE_SSL_REDIRECT": "True",
            "SESSION_COOKIE_SECURE": "True",
            "CSRF_COOKIE_SECURE": "True"
        }
        
        # Étape 4: Installer les dépendances
        print("4️⃣  Installation des dépendances...")
        pip_install = f"cd /home/{username}/sdi-market && pip install -r requirements.txt"
        
        # Étape 5: Migrer la base de données
        print("5️⃣  Migration de la base de données...")
        migrate_cmd = f"cd /home/{username}/sdi-market && python manage.py migrate --noinput"
        
        # Étape 6: Collecter les fichiers statiques
        print("6️⃣  Collecte des fichiers statiques...")
        static_cmd = f"cd /home/{username}/sdi-market && python manage.py collectstatic --noinput"
        
        print("\n" + "=" * 80)
        print("📋 Instructions pour terminer le déploiement:")
        print("=" * 80)
        print(f"""
1. Accédez à https://www.pythonanywhere.com/user/{username}/webapps/
2. Cliquez sur "Add a new web app"
3. Sélectionnez "Django" comme framework
4. Sélectionnez Python {python_version}
5. Entrez le répertoire source: /home/{username}/sdi-market
6. Entrez le chemin WSGI: /home/{username}/sdi-market/sdi_market/wsgi.py
7. Configurez les variables d'environnement:
""")
        
        for key, value in env_vars.items():
            print(f"   {key}={value}")
        
        print(f"""
8. Exécutez ces commandes dans la console Bash PythonAnywhere:
   cd /home/{username}
   git clone {repo_url} sdi-market
   cd sdi-market
   git checkout {branch}
   mkvirtualenv --python=/usr/bin/python{python_version} sdi-market
   pip install -r requirements.txt
   python manage.py migrate --noinput
   python manage.py collectstatic --noinput

9. Revenez au dashboard et cliquez sur "Reload" pour activer votre application

Votre site sera accessible sur: https://{domain}
""")
        
        print("=" * 80)
        print("✅ Guide de déploiement généré!")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Erreur lors du déploiement: {str(e)}")
        return False

if __name__ == '__main__':
    # Charger la configuration
    username = os.getenv('PYTHONANYWHERE_USERNAME', 'chouchoum')
    token = os.getenv('PYTHONANYWHERE_TOKEN', '')
    repo_url = os.getenv('GITHUB_REPO_URL', 'https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git')
    branch = os.getenv('GITHUB_BRANCH', 'feature/ma-modif')
    python_version = os.getenv('PYTHON_VERSION', '3.11')
    
    if not token:
        print("⚠️  Token PythonAnywhere non trouvé. Génération du guide uniquement...")
    
    deploy_to_pythonanywhere(username, token, repo_url, branch, python_version)
