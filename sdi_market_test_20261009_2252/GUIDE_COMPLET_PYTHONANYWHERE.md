# GUIDE DE DÉPLOIEMENT COMPLET - CHOUCHOUM.PYTHONANYWHERE.COM

## ⚠️ SITUATION ACTUELLE
- ✅ Compte PythonAnywhere: `chouchoum`
- ✅ Domaine: `chouchoum.pythonanywhere.com`
- ✅ Application web créée et prête
- ❌ Problème: Disque PLEIN (512MB utilisés sur 512MB)

---

## ÉTAPE 1: LIBÉRER L'ESPACE DISQUE (OBLIGATOIRE)

### 1.1 Accédez au gestionnaire de fichiers
1. Allez sur: **https://www.pythonanywhere.com/user/chouchoum/files/**
2. Vous verrez une liste de tous vos fichiers et dossiers

### 1.2 Supprimez les fichiers inutiles
Supprimez ces dossiers/fichiers (par ordre de taille):
- `sdi_site/` (85MB) - ancien dossier du projet
- `sdi_site_new/` (26MB) - autre ancienne version
- `db.sqlite3.production.backup` (31MB) - ancienne base de données
- `mysite/` (1.9MB) - ancien projet Django
- `sdi_code_changes_before_sync.patch` (60KB) - fichier de patch

Cliquez sur chaque dossier/fichier → bouton "Delete" → "Yes"

**Cela libérera environ 143MB, ce qui vous permettra de cloner le nouveau projet**

---

## ÉTAPE 2: CLONE DU PROJET GITHUB

### 2.1 Ouvrez la console Bash
1. Allez sur: **https://www.pythonanywhere.com/user/chouchoum/consoles/**
2. Cliquez sur **"$ Bash"** ou trouvez une console existante

### 2.2 Exécutez ces commandes (une à la fois):

```bash
# Aller dans le répertoire home
cd ~

# Cloner votre dépôt
git clone https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git sdi-market

# Aller dans le dossier
cd sdi-market

# Vérifier la branche correcte
git checkout feature/ma-modif

# Afficher la branche actuelle (devrait être "feature/ma-modif")
git branch
```

### 2.3 Attendez la fin du clonage
Vous verrez un message comme:
```
Cloning into 'sdi-market'...
remote: Counting objects: ...
Receiving objects: 100% (...), done.
```

---

## ÉTAPE 3: CRÉER L'ENVIRONNEMENT VIRTUEL

Dans la même console Bash, exécutez:

```bash
# Créer un environnement virtuel Python 3.11
mkvirtualenv --python=/usr/bin/python3.11 sdi-market

# Note: vous verrez "(sdi-market)" avant le prompt si c'est activé
```

---

## ÉTAPE 4: INSTALLER LES DÉPENDANCES

```bash
# S'assurer qu'on est dans le dossier du projet
cd ~/sdi-market

# Installer les dépendances
pip install -r requirements.txt

# Cela peut prendre 2-5 minutes
```

---

## ÉTAPE 5: INITIALISER LA BASE DE DONNÉES

```bash
# Faire les migrations
python manage.py migrate --noinput

# Collecter les fichiers statiques
python manage.py collectstatic --noinput

# Désactiver l'environnement virtuel
deactivate
```

---

## ÉTAPE 6: CONFIGURER LE FICHIER WSGI

### 6.1 Allez à la page Web
1. Allez sur: **https://www.pythonanywhere.com/user/chouchoum/webapps/**
2. Cliquez sur le domaine **`chouchoum.pythonanywhere.com`**

### 6.2 Configurez le répertoire source
Dans la section "Code":
- **Source directory**: `/home/chouchoum/sdi-market`

### 6.3 Configurez le fichier WSGI
Dans la section "Code":
- Trouvez **"WSGI configuration file"**
- Cliquez sur le lien (par défaut: `/var/www/chouchoum_pythonanywhere_com_wsgi.py`)
- Remplacez **TOUT** le contenu par ceci:

```python
import os
import sys

# Ajouter le dossier du projet
path = '/home/chouchoum/sdi-market'
if path not in sys.path:
    sys.path.append(path)

# Configurer Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
os.environ['DEBUG'] = 'False'
os.environ['ALLOWED_HOSTS'] = 'chouchoum.pythonanywhere.com'
os.environ['SECURE_SSL_REDIRECT'] = 'True'
os.environ['SESSION_COOKIE_SECURE'] = 'True'
os.environ['CSRF_COOKIE_SECURE'] = 'True'

# Initialiser Django
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Cliquez sur **"Save"**

---

## ÉTAPE 7: CONFIGURER LES FICHIERS STATIQUES

### 7.1 Retournez à la page Web apps
1. URL: **https://www.pythonanywhere.com/user/chouchoum/webapps/**
2. Cliquez sur **`chouchoum.pythonanywhere.com`**

### 7.2 Scroll down jusqu'à "Static files"

### 7.3 Ajoutez deux mappings

**Mapping 1:**
- URL: `/static/`
- Directory: `/home/chouchoum/sdi-market/staticfiles/`
- Cliquez **"Add"**

**Mapping 2:**
- URL: `/media/`
- Directory: `/home/chouchoum/sdi-market/media/`
- Cliquez **"Add"**

---

## ÉTAPE 8: RECHARGER L'APPLICATION

### 8.1 Retournez à la page Web apps

### 8.2 Cherchez le bouton "Reload" (🔄)
- C'est un bouton vert en haut à droite
- Cliquez sur "Reload"

### 8.3 Attendez que l'application redémarre
- Le statut devrait passer à "running" (vert)
- Cela peut prendre 30 secondes

---

## ✅ VÉRIFIER QUE LE SITE FONCTIONNE

1. Allez sur: **https://chouchoum.pythonanywhere.com/**
2. Vous devriez voir votre site MicroSDICash!

---

## ❌ DÉPANNAGE

### Si vous voyez une erreur 500
1. Allez sur la page Web apps
2. Trouvez le bouton **"Error log"**
3. Lisez les messages pour identifier le problème
4. Communs erreurs:
   - **ModuleNotFoundError**: Installez la dépendance manquante avec `pip install`
   - **Syntax error**: Vérifiez le fichier WSGI
   - **No such file**: Vérifiez les chemins dans la configuration

### Si vous voyez une erreur 404
1. Vérifiez que le fichier WSGI existe
2. Vérifiez que les mappings de fichiers statiques sont corrects

### Si vous voyez "Disk quota exceeded"
1. Vous avez besoin de plus d'espace
2. Supprimez d'autres fichiers inutiles
3. Ou payez pour un plan plus grand

---

## 📞 SUPPORT

- **PythonAnywhere Help**: https://help.pythonanywhere.com/
- **Django Docs**: https://docs.djangoproject.com/
- **GitHub**: https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50

---

## 📋 RÉSUMÉ DES COMMANDES BASH

```bash
# Étape 1: Libérer l'espace disque (via interface fichiers)

# Étape 2-5: Cloner et configurer
cd ~
git clone https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git sdi-market
cd sdi-market
git checkout feature/ma-modif
mkvirtualenv --python=/usr/bin/python3.11 sdi-market
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
deactivate

# Étapes 6-8: Configuration web (via interface web)
# Voir détails ci-dessus
```

---

**Statut: Prêt pour déploiement! 🚀**
**Date: 2026-09-01**
**Version: Production Ready**
