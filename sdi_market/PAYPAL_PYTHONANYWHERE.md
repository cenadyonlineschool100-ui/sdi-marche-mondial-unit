# PayPal Sandbox et préparation PythonAnywhere

Ce guide décrit la configuration à préparer. Aucune commande de production,
migration, recharge PythonAnywhere ou activation Live n'a été exécutée.

## Compatibilité Python requise

Le projet verrouille `Django==6.0.3` dans `requirements.txt`. Django 6 exige
Python 3.12 ou ultérieur. Les anciennes instructions de déploiement du projet
qui indiquent Python 3.11 ne sont donc pas compatibles avec les dépendances
actuelles. Vérifiez qu'une version Python 3.12+ est disponible dans votre
compte PythonAnywhere et configurez le web app et son virtualenv avec la même
version avant d'installer les dépendances.

Exemple à adapter à la version réellement proposée dans le compte :

```bash
mkvirtualenv --python=/usr/bin/python3.13 sdi-market-py313
workon sdi-market-py313
cd /home/chouchoum/sdi-market/sdi_market
pip install -r requirements.txt
python -V
python -m django --version
```

Ne remplacez pas un virtualenv de production existant avant d'avoir vérifié
le web app et son chemin de virtualenv dans le tableau de bord.

## Variables d'environnement

Configurer les variables dans l'environnement serveur privé du web app
PythonAnywhere. Ne pas les mettre dans Git, un template, une capture d'écran ou
un message.

| Variable | Valeur Sandbox |
|---|---|
| `PAYPAL_MODE` | `sandbox` |
| `PAYPAL_CLIENT_ID` | Client ID de l'application PayPal Sandbox |
| `PAYPAL_CLIENT_SECRET` | Secret de l'application PayPal Sandbox |
| `PAYPAL_WEBHOOK_ID` | ID du webhook Sandbox créé dans cette application |
| `PAYPAL_LIVE_ENABLED` | `False` |
| `PAYPAL_STOCK_RESERVATION_TTL_HOURS` | Durée de réservation des commandes PayPal impayées (défaut : `24`) |
| `DJANGO_SECRET_KEY` | Clé privée propre à l'environnement |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | Domaine(s) réellement utilisés, séparés par des virgules |

Le checkout PayPal ne s'active que si les identifiants client, secret et
webhook sont définis. Le mode Live est bloqué par défaut.
La commande `python manage.py expire_paypal_stock_reservations` libère les
réservations échues. Pour automatiser ce traitement, programmer cette commande
dans une tâche planifiée PythonAnywhere, par exemple une fois par heure.

## Webhook Sandbox

Créer dans l'application PayPal Sandbox un webhook avec cette URL :

```text
https://chouchoum.pythonanywhere.com/api/paypal/webhook/
```

Souscrire au minimum aux événements :

- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.DENIED`

Copier l'ID du webhook dans `PAYPAL_WEBHOOK_ID`. L'endpoint vérifie la
signature auprès de PayPal avant de traiter un événement; ne pas désactiver
cette vérification.

## Vérifications locales avant toute publication

Depuis le dossier qui contient `manage.py` :

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test marketplace.tests_paypal
```

Les migrations `0118` et `0119` ajoutent les statuts d'expiration, les
réservations de stock et leur journal. La migration `0119` recense les
commandes PayPal existantes : les commandes impayées encore en attente sont
considérées comme ayant déjà réservé leur stock, puisque le checkout
préexistant le décrémentait à la création. Les commandes déjà payées ou en
livraison sont enregistrées comme consommées et ne seront pas libérées.
Les migrations `0116` et `0117` font partie de l'intégration PayPal déjà
présente dans le dépôt. Leur état sur PythonAnywhere n'a pas été vérifié;
contrôler `showmigrations` avant toute opération et appliquer uniquement les
migrations encore en attente, dans l'ordre normal de Django.

## Préparation de déploiement — ne pas exécuter sans approbation

Les commandes suivantes ne sont qu'une procédure future. Elles n'ont pas été
exécutées sur PythonAnywhere. Avant leur exécution, vérifier la branche et le
répertoire déployés, les variables serveur et la base de données ciblée :

```bash
cd /home/chouchoum/sdi-market/sdi_market
workon sdi-market-py313
python -V
python manage.py check
python manage.py showmigrations marketplace
python manage.py migrate --plan
```

Après validation explicite du propriétaire seulement, appliquer les migrations
qui manquent avec `python manage.py migrate`, vérifier à nouveau
`showmigrations marketplace`, puis recharger le web app depuis PythonAnywhere.
Ne pas exécuter `migrate` sur la production ni la recharger avant cette
validation.

## Parcours Sandbox

1. Utiliser uniquement des identifiants et comptes acheteur/vendeur Sandbox.
2. Créer une commande de test et vérifier que son montant est celui calculé
   côté serveur.
3. Approuver le paiement Sandbox; vérifier que seule une capture PayPal
   `COMPLETED`, de montant et devise correspondants, confirme la commande.
4. Tester l'annulation, le refus, une nouvelle tentative, une devise ou un
   montant incohérent, une commande appartenant à un autre compte et un
   webhook dont la signature est invalide.
5. Vérifier les journaux côté serveur sans y copier de secret ni de données
   personnelles.

Les tests Django simulés ne constituent pas une transaction Sandbox réelle.
Un test réel doit être fait séparément avec des identifiants Sandbox
configurés; aucune transaction réelle n'a été exécutée pendant cet audit.

## Passage en Live ultérieur

Ne pas activer Live maintenant. Après validation explicite et tests Sandbox,
il faudra configurer les identifiants et l'ID de webhook de l'application
PayPal Live, définir `PAYPAL_MODE=live` et seulement alors autoriser
`PAYPAL_LIVE_ENABLED=True`. Refaire la validation HTTPS, URL webhook, montant,
devise et événements avant d'accepter de vrais paiements. Ne jamais réutiliser
les identifiants Sandbox en Live.

## Gestion du stock et limites opérationnelles

Le stock est décrémenté dans la transaction de création de commande et une
réservation PayPal avec lignes horodatées est créée dans la même transaction.
Une annulation confirmée côté PayPal, un refus définitif ou l'expiration
libèrent le stock une seule fois si la commande n'est pas payée et reste en
statut `pending`. Les nouvelles tentatives réservent de nouveau le stock
uniquement si la quantité est encore disponible. Le journal conserve les
réservations, libérations, expirations et consommations.

La tâche d'expiration doit être planifiée. Configurez par exemple une tâche
PythonAnywhere horaire qui exécute, dans l'environnement virtuel effectivement
configuré pour le web app :

```bash
cd /home/chouchoum/sdi-market/sdi_market
workon sdi-market-py313
python manage.py expire_paypal_stock_reservations
```

Sans cette tâche, les commandes impayées sont empêchées de capturer à l'heure
d'expiration, mais leur stock ne sera libéré qu'au prochain lancement de la
commande de gestion.
Une capture déjà démarrée dans le délai passe l'état de réservation à
`capturing`; la tâche d'expiration l'ignore jusqu'à la confirmation ou à
l'échec de l'appel PayPal. Si l'appel expire côté réseau ou si le processus
s'arrête pendant la capture, le stock reste volontairement bloqué jusqu'à la
réconciliation via un webhook PayPal valide ou une vérification manuelle : il
ne faut pas le libérer tant que l'état du paiement est ambigu, car la capture
peut avoir été acceptée par PayPal.
