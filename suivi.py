"""
suivi.py
--------
Récupère le classement d'un tournoi Challonge et le publie sur un salon Discord
via une « webhook », sous forme d'un message « embed » contenant un tableau aligné.

Conçu pour être exécuté automatiquement (par exemple chaque jour via GitHub
Actions), sans aucune intervention manuelle une fois en place.

Variables d'environnement attendues
-----------------------------------
CHALLONGE_USERNAME  Votre pseudo Challonge (sert à l'authentification HTTP Basic).
CHALLONGE_API_KEY   Clé API v1, créée depuis le portail Challonge (connect.challonge.com).
DISCORD_WEBHOOK_URL URL de la webhook du salon Discord cible.
TOURNAMENT_SLUG     Identifiant du tournoi dans son URL Challonge.
                    Pour https://challonge.com/fr/SquadronS16D2  ->  "SquadronS16D2".

Authentification
----------------
L'API est appelée en authentification HTTP Basic : utilisateur = pseudo
Challonge, mot de passe = clé API v1. C'est la méthode qui fonctionne de façon
fiable (l'envoi de la clé via le paramètre d'URL "api_key" provoquait une erreur
serveur 520 sur l'infrastructure actuelle de Challonge).

Le script ne fait que LIRE le tournoi (requête GET). Il ne modifie jamais le
tournoi distant.

Limites connues (à lire)
------------------------
1. Le classement est calculé à partir des matchs TERMINÉS (état "complete"),
   en comptant victoires / défaites par participant. C'est pertinent pour ce
   tournoi (format "round robin"). Le « vrai » classement Challonge applique en
   plus des règles de départage (tie-breaks) ; ce décompte V/D en est une
   approximation lisible.
2. En cas d'erreur serveur passagère (5xx, dont 520), le script réessaie
   automatiquement quelques fois avant d'abandonner.
3. Pour inspecter la réponse brute de Challonge, lancer avec la variable
   d'environnement DEBUG=1.
"""

import os
import sys
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

CHALLONGE_API_BASE = "https://api.challonge.com/v1"

# Couleur de la barre latérale de l'embed (bleu Discord), au format entier décimal.
COULEUR_EMBED = 0x5865F2

# Garde-fous de mise en forme pour rester sous les limites de l'API Discord.
LARGEUR_NOM = 18          # nb max de caractères affichés pour un nom d'équipe
MAX_LIGNES_TABLEAU = 60   # au-delà, le tableau est tronqué (sécurité anti-dépassement)

# Réessais en cas d'erreur serveur passagère.
NB_ESSAIS = 4
PAUSE_ENTRE_ESSAIS_S = 6


def lire_config():
    """Lit et valide la configuration depuis les variables d'environnement.

    Returns
    -------
    tuple(str, str, str, str)
        (username, api_key, webhook_url, slug)

    Raises
    ------
    SystemExit
        Si une variable obligatoire est absente ou vide. Le message indique
        précisément ce qui manque, pour faciliter le diagnostic.
    """
    username = os.environ.get("CHALLONGE_USERNAME", "").strip()
    api_key = os.environ.get("CHALLONGE_API_KEY", "").strip()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    slug = os.environ.get("TOURNAMENT_SLUG", "").strip()

    manquants = []
    if not username:
        manquants.append("CHALLONGE_USERNAME")
    if not api_key:
        manquants.append("CHALLONGE_API_KEY")
    if not webhook:
        manquants.append("DISCORD_WEBHOOK_URL")
    if not slug:
        manquants.append("TOURNAMENT_SLUG")

    if manquants:
        print(
            "ERREUR : variable(s) d'environnement manquante(s) : "
            + ", ".join(manquants),
            file=sys.stderr,
        )
        print(
            "Vérifiez vos « secrets » GitHub Actions et le fichier du workflow.",
            file=sys.stderr,
        )
        sys.exit(1)

    return username, api_key, webhook, slug


def recuperer_tournoi(slug, username, api_key):
    """Interroge l'API Challonge (HTTP Basic) et renvoie le dictionnaire 'tournament'.

    Réessaie automatiquement en cas d'erreur serveur passagère (5xx).

    Parameters
    ----------
    slug : str
        Identifiant du tournoi (partie finale de l'URL Challonge).
    username : str
        Pseudo Challonge (utilisateur HTTP Basic).
    api_key : str
        Clé API v1 (mot de passe HTTP Basic).

    Returns
    -------
    dict
        Le contenu de la clé "tournament" de la réponse JSON, incluant
        "participants" et "matches".

    Raises
    ------
    SystemExit
        En cas d'erreur non récupérable, ou après épuisement des réessais.
    """
    url = f"{CHALLONGE_API_BASE}/tournaments/{slug}.json"
    params = {"include_participants": 1, "include_matches": 1}
    derniere_cause = "inconnue"

    for essai in range(1, NB_ESSAIS + 1):
        try:
            reponse = requests.get(
                url, params=params, auth=(username, api_key), timeout=30
            )
        except requests.RequestException as exc:
            derniere_cause = f"erreur réseau ({exc})"
            print(
                f"Tentative {essai}/{NB_ESSAIS} : {derniere_cause}. Nouvel essai…",
                file=sys.stderr,
            )
            time.sleep(PAUSE_ENTRE_ESSAIS_S)
            continue

        # Erreurs définitives : inutile de réessayer.
        if reponse.status_code == 401:
            print(
                "ERREUR : authentification refusée (401). Vérifiez "
                "CHALLONGE_USERNAME (votre pseudo) et CHALLONGE_API_KEY (la clé).",
                file=sys.stderr,
            )
            sys.exit(1)
        if reponse.status_code == 404:
            print(
                f"ERREUR : tournoi introuvable (404) pour le slug « {slug} ». "
                "Vérifiez l'orthographe (sensible à la casse).",
                file=sys.stderr,
            )
            sys.exit(1)

        # Erreurs serveur passagères : on réessaie.
        if 500 <= reponse.status_code < 600:
            derniere_cause = f"erreur serveur Challonge (HTTP {reponse.status_code})"
            print(
                f"Tentative {essai}/{NB_ESSAIS} : {derniere_cause}. Nouvel essai…",
                file=sys.stderr,
            )
            time.sleep(PAUSE_ENTRE_ESSAIS_S)
            continue

        try:
            reponse.raise_for_status()
        except requests.HTTPError as exc:
            print(f"ERREUR HTTP Challonge : {exc}", file=sys.stderr)
            sys.exit(1)

        donnees = reponse.json()

        if os.environ.get("DEBUG", "").strip() == "1":
            print("=== DEBUG : réponse brute Challonge ===", file=sys.stderr)
            print(
                json.dumps(donnees, indent=2, ensure_ascii=False)[:8000],
                file=sys.stderr,
            )
            print("=== fin DEBUG ===", file=sys.stderr)

        return donnees["tournament"]

    print(
        f"ERREUR : échec après {NB_ESSAIS} tentatives ({derniere_cause}).",
        file=sys.stderr,
    )
    sys.exit(1)


def construire_classement(tournoi):
    """Construit un classement (victoires / défaites) à partir des matchs terminés.

    Fonction « pure » (aucun accès réseau), testable hors-ligne.

    Parameters
    ----------
    tournoi : dict
        Dictionnaire 'tournament' renvoyé par l'API, avec "participants" et
        "matches".

    Returns
    -------
    list[dict]
        Liste triée de dictionnaires {"nom": str, "v": int, "d": int}, du
        meilleur au moins bon (plus de victoires d'abord, puis moins de défaites,
        puis ordre alphabétique).

    Notes
    -----
    Challonge peut référencer les joueurs dans les matchs soit par leur
    identifiant de participant ("id"), soit, pour les formats à groupes, par un
    identifiant de groupe ("group_player_ids"). On ramène donc toute clé vers
    l'identifiant canonique du participant pour ne pas compter un joueur deux fois.
    """
    nom_par_pid = {}
    canon = {}

    for item in tournoi.get("participants", []):
        p = item.get("participant", item)
        pid = p.get("id")
        if pid is None:
            continue
        nom = p.get("name") or p.get("display_name") or f"Participant {pid}"
        nom_par_pid[pid] = nom.strip() if isinstance(nom, str) else str(nom)
        canon[pid] = pid
        for gpid in (p.get("group_player_ids") or []):
            canon[gpid] = pid

    victoires = defaultdict(int)
    defaites = defaultdict(int)

    for item in tournoi.get("matches", []):
        m = item.get("match", item)
        if m.get("state") != "complete":
            continue
        gagnant = canon.get(m.get("winner_id"))
        perdant = canon.get(m.get("loser_id"))
        if gagnant is not None:
            victoires[gagnant] += 1
        if perdant is not None:
            defaites[perdant] += 1

    classement = []
    for pid, nom in nom_par_pid.items():
        classement.append({"nom": nom, "v": victoires[pid], "d": defaites[pid]})

    classement.sort(key=lambda e: (-e["v"], e["d"], e["nom"].lower()))
    return classement


def formater_tableau(classement):
    """Met en forme le classement en tableau texte aligné (police à chasse fixe)."""
    if not classement:
        return "Aucun participant trouvé pour ce tournoi."

    tronque = classement[:MAX_LIGNES_TABLEAU]

    lignes = ["#   {:<{w}} V   D".format("Équipe", w=LARGEUR_NOM)]
    for rang, e in enumerate(tronque, start=1):
        nom = e["nom"]
        if len(nom) > LARGEUR_NOM:
            nom = nom[: LARGEUR_NOM - 1] + "…"
        lignes.append(
            "{:<3} {:<{w}} {:<3} {:<3}".format(rang, nom, e["v"], e["d"], w=LARGEUR_NOM)
        )

    if len(classement) > MAX_LIGNES_TABLEAU:
        lignes.append(f"… (+{len(classement) - MAX_LIGNES_TABLEAU} autres)")

    return "\n".join(lignes)


def construire_embed(tournoi, classement):
    """Construit l'objet 'embed' Discord à envoyer."""
    nom_tournoi = tournoi.get("name") or "Tournoi"
    url_tournoi = tournoi.get("full_challonge_url")

    tableau = formater_tableau(classement)
    description = f"```\n{tableau}\n```"

    if len(description) > 4000:  # la description d'un embed est limitée à 4096
        description = description[:3990] + "\n…```"

    embed = {
        "title": f"Classement — {nom_tournoi}"[:256],
        "description": description,
        "color": COULEUR_EMBED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Mis à jour automatiquement"},
    }
    if url_tournoi:
        embed["url"] = url_tournoi

    return embed


def publier_sur_discord(webhook_url, embed):
    """Envoie l'embed sur le salon Discord via la webhook."""
    payload = {"embeds": [embed]}
    try:
        reponse = requests.post(webhook_url, json=payload, timeout=30)
        reponse.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERREUR lors de la publication sur Discord : {exc}", file=sys.stderr)
        sys.exit(1)

    print("Classement publié sur Discord avec succès.")


def main():
    """Point d'entrée : lecture config -> Challonge -> Discord."""
    username, api_key, webhook, slug = lire_config()
    tournoi = recuperer_tournoi(slug, username, api_key)
    classement = construire_classement(tournoi)
    embed = construire_embed(tournoi, classement)
    publier_sur_discord(webhook, embed)


if __name__ == "__main__":
    main()
