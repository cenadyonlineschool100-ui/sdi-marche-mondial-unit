# Déploiement des catégories sur 1sdi

La branche de production est `deploy/sdi-local-20261118`. La migration
`0120_seed_default_categories` ajoute ou active les cinq catégories principales
du site local. Elle conserve les catégories sans rapport et les descriptions
et images déjà personnalisées.

Le workflow `.github/workflows/deploy-1sdi-categories.yml` se déclenche lorsqu'une
modification contenant cette migration est poussée sur la branche de production.
Il vérifie le changement, teste la migration, met à jour le dépôt PythonAnywhere
par avance rapide, applique uniquement cette migration, vérifie les catégories,
puis recharge l'application.

Avant le push, configurer ces secrets dans les paramètres Actions du dépôt GitHub :

- `PA_SSH_PRIVATE_KEY` : clé privée autorisée pour le compte PythonAnywhere `1sdi`.
- `PA_SSH_KNOWN_HOSTS` : clé d'hôte SSH vérifiée de `ssh.pythonanywhere.com`.
- `PA_API_TOKEN` : jeton API PythonAnywhere de `1sdi`, utilisé uniquement pour recharger
  l'application.

Le workflow attend le dépôt `/home/1sdi/sdi-market`, l'environnement virtuel
`/home/1sdi/.virtualenvs/sdi-market` et l'origine GitHub
`cenadyonlineschool100-ui/sdi-marche-mondial-unit`. Il refuse de continuer si la
branche, le commit de départ ou les fichiers de migration sur PythonAnywhere ne
correspondent pas à ce qui est attendu. Il ne supprime pas les autres changements
locaux du serveur.
