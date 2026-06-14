# Suivi du classement Challonge sur Discord

Ce petit projet publie automatiquement, **chaque jour**, le classement d'un
tournoi Challonge dans un salon Discord, sous forme d'un message « embed »
contenant un tableau aligné. Une fois installé, il fonctionne tout seul, dans le
cloud, gratuitement, sans laisser d'ordinateur allumé.

Le programme se contente de **lire** le tournoi. Il ne modifie jamais rien sur
Challonge.

---

## Ce dont vous avez besoin (3 comptes gratuits)

1. Un compte **Challonge** (pour obtenir une clé d'accès, dite « clé API »).
2. Un salon **Discord** où vous avez le droit de gérer les réglages.
3. Un compte **GitHub** (c'est lui qui exécute le programme chaque jour).

Aucune carte bancaire n'est nécessaire.

---

## Étape 1 — Obtenir votre clé API Challonge

1. Créez un compte sur https://challonge.com (gratuit) et validez votre e-mail.
2. Allez sur https://challonge.com/settings/developer
3. Copiez la **clé API** affichée (une suite de lettres et de chiffres).
   Gardez-la de côté, vous en aurez besoin à l'étape 4.

> Remarque : d'après la documentation de Challonge, cette clé permet de **lire**
> n'importe quel tournoi public, même si vous n'en êtes pas l'organisateur.
> C'est l'hypothèse de départ ; on le vérifie au tout premier lancement
> (étape 5). Si la lecture échouait, voir la section « Dépannage ».

---

## Étape 2 — Créer la webhook Discord

Une « webhook » est une adresse secrète qui permet d'écrire dans un salon.

1. Dans Discord, choisissez (ou créez) le salon où afficher le classement.
   Un salon dédié, par exemple `#classement`, est conseillé.
2. Survolez le nom du salon → roue dentée **« Modifier le salon »**.
3. Onglet **« Intégrations »** → **« Webhooks »** → **« Nouveau webhook »**.
4. Donnez-lui un nom (ex. « Suivi Squadron »), puis cliquez sur
   **« Copier l'URL du webhook »**.
5. Gardez cette URL de côté pour l'étape 4.

> Cette URL est un secret : ne la publiez nulle part publiquement.

---

## Étape 3 — Copier le projet sur GitHub

1. Créez un compte sur https://github.com (gratuit).
2. En haut à droite, cliquez sur **« + » → « New repository »**.
3. Donnez un nom (ex. `suivi-squadron`), laissez-le en **Public** ou **Private**
   (les deux fonctionnent), puis **« Create repository »**.
4. Sur la page du nouveau dépôt, cliquez sur le lien
   **« uploading an existing file »**.
5. Glissez-déposez **tout le contenu** de ce projet (le dossier
   `challonge-discord-suivi`), en conservant la structure des dossiers,
   notamment `.github/workflows/suivi.yml`.
   - Astuce : décompressez le `.zip` d'abord, puis glissez les fichiers.
   - Le dossier `.github` doit bien être présent après l'envoi.
6. Cliquez sur **« Commit changes »** (bouton vert).

---

## Étape 4 — Enregistrer vos clés (les « secrets »)

Vos deux clés ne doivent **jamais** être écrites en clair dans le code. GitHub
prévoit un coffre-fort pour ça.

1. Dans votre dépôt, allez dans **« Settings »** (onglet en haut).
2. Menu de gauche : **« Secrets and variables » → « Actions »**.
3. Bouton **« New repository secret »**, et créez **exactement** ces deux secrets :

   | Nom (à recopier à l'identique) | Valeur                              |
   |--------------------------------|-------------------------------------|
   | `CHALLONGE_API_KEY`            | votre clé API (étape 1)             |
   | `DISCORD_WEBHOOK_URL`          | l'URL de la webhook (étape 2)       |

4. Vérifiez le fichier `.github/workflows/suivi.yml` : la ligne
   `TOURNAMENT_SLUG: SquadronS16D2` doit correspondre à votre tournoi.
   Pour `https://challonge.com/fr/MonTournoi`, le slug est `MonTournoi`
   (attention aux majuscules/minuscules).

---

## Étape 5 — Premier lancement (test manuel)

1. Dans votre dépôt, ouvrez l'onglet **« Actions »**.
2. Si GitHub demande d'activer les workflows, acceptez.
3. Cliquez sur le workflow **« Suivi classement Challonge »** à gauche.
4. Bouton **« Run workflow » → « Run workflow »**.
5. Attendez ~1 minute, puis vérifiez votre salon Discord : le classement doit
   apparaître.
   - En cas d'erreur, cliquez sur l'exécution pour lire le message
     (voir « Dépannage »).

Si le message apparaît : c'est terminé. Le classement se republiera ensuite
**chaque jour automatiquement**.

---

## Réglages courants

- **Changer l'heure** : dans `suivi.yml`, modifiez `cron: "0 7 * * *"`.
  Le `7` est l'heure en **UTC** (Paris = UTC+1 en hiver, UTC+2 en été).
- **Changer de tournoi** : modifiez la ligne `TOURNAMENT_SLUG:` dans `suivi.yml`.

---

## Limites et points à connaître (honnêteté)

- **Un message par jour** : la version actuelle publie un nouveau message à
  chaque exécution (elle n'édite pas un message existant). C'est le choix le
  plus simple et le plus robuste. L'édition d'un message unique « qui se met à
  jour sur place » est possible mais demande de mémoriser un identifiant entre
  les exécutions ; ce n'est pas inclus ici.
- **Type de tournoi** : le classement Victoires/Défaites est pertinent pour un
  format ligue / round-robin. Pour une élimination directe, ce décompte
  s'affiche mais représente mal la réalité (il s'agit d'un arbre de matchs).
- **Heure approximative** : GitHub n'exécute pas toujours les tâches planifiées
  exactement à l'heure ; un léger décalage est normal.
- **Mise en veille après inactivité** : GitHub peut désactiver une tâche
  planifiée si le dépôt reste sans aucune activité pendant une longue période
  (de l'ordre de ~60 jours, à vérifier dans la documentation GitHub en vigueur).
  Un simple lancement manuel ou une modification réactive la planification.
- **Quotas gratuits GitHub Actions** : largement suffisants pour une exécution
  par jour, mais les conditions exactes peuvent évoluer ; à vérifier au besoin.

---

## Dépannage

Ouvrez l'onglet **« Actions »**, cliquez sur l'exécution en échec, puis sur
l'étape « Publier le classement » pour lire le message d'erreur.

- `clé API Challonge refusée (401)` → la valeur du secret `CHALLONGE_API_KEY`
  est incorrecte. Recopiez-la depuis https://challonge.com/settings/developer
- `tournoi introuvable (404)` → le slug est mal orthographié (sensible à la
  casse), ou l'accès en lecture à ce tournoi n'est pas autorisé pour votre clé.
- Le classement semble faux ou vide → relancez en ajoutant temporairement un
  secret `DEBUG` valant `1`. Le programme affichera alors la structure brute
  reçue de Challonge dans les logs, ce qui permet d'ajuster le code aux champs
  réellement renvoyés.
