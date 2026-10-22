# Guide de Déploiement - MicroSDICash

## 📊 État du Déploiement

✅ **GitHub**: Code poussé avec succès
- Repository: `https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git`
- Branch: `feature/ma-modif`
- Commit: "Finalisation du site - prêt pour production"

🚀 **PythonAnywhere**: Instructions de déploiement

## 🔧 Configuration PythonAnywhere

### Accès Console
- Username: `chouchoum`
- Domain: `chouchoum.pythonanywhere.com`

### Variables d'Environnement
```
DJANGO_SETTINGS_MODULE=sdi_market.settings
DEBUG=False
ALLOWED_HOSTS=chouchoum.pythonanywhere.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## 📋 Étapes de Déploiement

### 1. Cloner le Dépôt
```bash
cd /home/chouchoum
git clone https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50.git sdi-market
cd sdi-market
git checkout feature/ma-modif
```

### 2. Créer l'Environnement Virtuel
```bash
mkvirtualenv --python=/usr/bin/python3.11 sdi-market
```

### 3. Installer les Dépendances
```bash
pip install -r requirements.txt
```

### 4. Initialiser la Base de Données
```bash
python manage.py migrate --noinput
```

### 5. Collecter les Fichiers Statiques
```bash
python manage.py collectstatic --noinput
```

### 6. Créer l'Application Web sur PythonAnywhere

1. Accédez à: `https://www.pythonanywhere.com/user/chouchoum/webapps/`
2. Cliquez sur "Add a new web app"
3. Sélectionnez "Manual configuration"
4. Sélectionnez Python 3.11
5. Configurez le WSGI:
   - Path: `/home/chouchoum/sdi-market/sdi_market/wsgi.py`

### 7. Configurer les Répertoires Statiques

1. Dans le dashboard PythonAnywhere, éditez la configuration web
2. Ajoutez les mappages statiques:
   - URL: `/static/` → Répertoire: `/home/chouchoum/sdi-market/staticfiles/`
   - URL: `/media/` → Répertoire: `/home/chouchoum/sdi-market/media/`

### 8. Recharger l'Application
- Cliquez sur le bouton "Reload" dans le dashboard

## 🌐 Accès au Site

Votre site sera accessible sur: **https://chouchoum.pythonanywhere.com**

## 📝 Notes Importantes

- ✅ SSL/HTTPS est activé automatiquement sur PythonAnywhere
- ✅ Les mises à jour futures : `git pull` dans le répertoire `/home/chouchoum/sdi-market/`
- ✅ Après chaque mise à jour, rechargez l'application dans le dashboard
- ⚠️ Utilisez une vrai base de données (PostgreSQL) pour la production

## 🔐 Sécurité

- Générez un nouveau SECRET_KEY pour la production
- Mettez à jour ALLOWED_HOSTS avec votre domaine réel
- Configurez une vraie base de données (pas SQLite en production)
- Activez SSL/HTTPS (par défaut sur PythonAnywhere)

## 📚 Ressources

- [Documentations Django](https://docs.djangoproject.com/)
- [Guide PythonAnywhere](https://www.pythonanywhere.com/user_support.html)
- [Repository GitHub](https://github.com/cenadyonlineschool100-ui/sdi-marche-mondial-unit-50)

---
Date: 2026-09-01
État: ✅ Prêt pour production
