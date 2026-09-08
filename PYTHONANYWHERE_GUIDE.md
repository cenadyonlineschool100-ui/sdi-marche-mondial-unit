# Guide de Déploiement Manuel - MicroSDICash sur PythonAnywhere

## 📝 Résumé du Déploiement

Votre code Django est prêt et synchronisé sur GitHub. Il ne reste que quelques étapes pour le déployer sur PythonAnywhere.

## ✅ Prérequis

1. **Compte PythonAnywhere** - Créez un compte sur https://www.pythonanywhere.com si vous n'en avez pas
2. **Token API** (optionnel) - Pour l'automatisation
3. **Accès à GitHub** - Votre dépôt est public et accessible

## 📋 GUIDE ÉTAPE PAR ÉTAPE

### ÉTAPE 1: Créer un Compte PythonAnywhere

1. Allez sur https://www.pythonanywhere.com/
2. Cliquez sur "Pricing & signup" ou "Sign up"
3. Créez un compte avec:
   - Un **nom d'utilisateur** (exemple: `monsite`)
   - Une **adresse email**
   - Un **mot de passe sécurisé**
4. Sélectionnez le plan gratuit ou payant selon vos besoins

### ÉTAPE 2: Accéder au Dashboard

1. Connectez-vous à votre compte PythonAnywhere
2. Vous verrez le Dashboard avec vos applications web

### ÉTAPE 3: Créer une Application Web Django

1. Dans le Dashboard, cliquez sur **"Web"** (menu principal)
2. Cliquez sur **"Add a new web app"**
3. Sélectionnez:
   - **Domaine**: `votrenom.pythonanywhere.com` (exemple: `monsite.pythonanywhere.com`)
   - ⚠️ Si le domaine est pris, choisissez un autre nom d'utilisateur
4. Cliquez **"Next"**
5. Sélectionnez **"Manual configuration"** (pas Django wizard)
6. Sélectionnez **"Python 3.11"** (ou la version appropriée)
7. Cliquez **"Next"**

### ÉTAPE 4: Configurer la Console Bash

Vous devez d'abord cloner votre projet et installer les dépendances.

1. Dans le Dashboard, allez à **"Consoles"**
2. Cliquez sur **"Bash"** pour ouvrir une console interactive
3. Exécutez ces commandes une par une:

```bash
# Aller au répertoire home
cd ~

# Cloner votre dépôt GitHub
git clone https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git sdi-market

# Aller dans le répertoire
cd sdi-market

# Vérifier la branche correcte
git checkout feature/ma-modif

# Créer un environnement virtuel
mkvirtualenv --python=/usr/bin/python3.11 sdi-market

# Installer les dépendances
pip install -r requirements.txt

# Exécuter les migrations
python manage.py migrate --noinput

# Collecter les fichiers statiques
python manage.py collectstatic --noinput

# Quitter l'environnement virtuel
deactivate
```

### ÉTAPE 5: Configurer le Fichier WSGI

1. Dans le Dashboard, allez à **"Web"**
2. Cliquez sur votre domaine (`votrenom.pythonanywhere.com`)
3. Faites défiler jusqu'à **"Code"**
4. À côté de "WSGI configuration file", cliquez sur le lien
   - Par défaut: `/var/www/votrenom_pythonanywhere_com_wsgi.py`
5. Remplacez le contenu par ceci:

```python
import os
import sys

# Ajouter votre projet au chemin Python
path = '/home/votrenom/sdi-market'
if path not in sys.path:
    sys.path.append(path)

# Définir les paramètres Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'sdi_market.settings'
os.environ['DJANGO_SECRET_KEY'] = 'change-this-to-a-secure-key'

# Obtenir l'application WSGI
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

⚠️ **Important**: Remplacez `votrenom` par votre nom d'utilisateur PythonAnywhere

6. Sauvegardez le fichier

### ÉTAPE 6: Configurer les Fichiers Statiques

1. Dans la page Web (étape précédente), faites défiler jusqu'à **"Static files"**
2. Cliquez sur **"Add a new static files mapping"**
3. Ajoutez les deux mappings suivants:

**Mapping 1: Static files**
- URL: `/static/`
- Répertoire: `/home/votrenom/sdi-market/staticfiles/`

**Mapping 2: Media files**
- URL: `/media/`
- Répertoire: `/home/votrenom/sdi-market/media/`

3. Sauvegardez les modifications

### ÉTAPE 7: Configurer les Variables d'Environnement

1. Dans la page Web, faites défiler jusqu'à **"Web app settings"**
2. Cliquez sur **"Environment variables"**
3. Ajoutez ces variables:

```
DJANGO_SETTINGS_MODULE=sdi_market.settings
DEBUG=False
ALLOWED_HOSTS=votrenom.pythonanywhere.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

Appuyez sur **"Save"**

### ÉTAPE 8: Recharger l'Application

1. Retournez à la page Web
2. En haut, trouvez le bouton **"Reload"** (⟲)
3. Cliquez sur **"Reload"**
4. Attendez que le statut change à **"running"** (vert)

### ÉTAPE 9: Vérifier la Configuration

Allez à votre domaine: `https://votrenom.pythonanywhere.com/`

Si vous voyez des erreurs:
- Cliquez sur le lien **"Error log"** dans le Dashboard
- Lisez les messages d'erreur pour diagnostiquer les problèmes

## 🔧 Dépannage Courant

### Erreur 500 - Internal Server Error
- Vérifiez le fichier WSGI
- Assurez-vous que le chemin vers le projet est correct
- Consultez l'error log

### Erreur 404 - Page Not Found
- Assurez-vous que le fichier WSGI existe
- Vérifiez que la configuration Django est correcte

### Problèmes de fichiers statiques (CSS/JS manquants)
- Réexécutez: `python manage.py collectstatic --noinput`
- Vérifiez les mappings de fichiers statiques

### Erreur de base de données
- Réexécutez: `python manage.py migrate --noinput`
- Vérifiez les permissions du fichier db.sqlite3

## 📚 Ressources Utiles

- [Documentation PythonAnywhere](https://help.pythonanywhere.com/)
- [Documentation Django](https://docs.djangoproject.com/)
- [GitHub Repository](https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50)

## 🔑 Conseils de Sécurité pour la Production

1. **Générez une vraie SECRET_KEY**: https://djecrety.ir/
2. **Utilisez une vraie base de données**: PostgreSQL plutôt que SQLite
3. **Utilisez HTTPS**: Activez SSL (gratuit sur PythonAnywhere)
4. **Mettez à jour ALLOWED_HOSTS**: Avec votre domaine réel
5. **Désactivez DEBUG**: Mettez DEBUG=False en production

## ✅ Résumé

```
✓ Code sur GitHub: feature/ma-modif
✓ Prêt pour production
✓ Configuration PythonAnywhere créée
✓ Instructions détaillées fournies

Prochaine étape: Créer un compte PythonAnywhere et suivre ce guide!
```

---

**Questions?** Consultez les Forums ou Help PythonAnywhere: https://help.pythonanywhere.com/
