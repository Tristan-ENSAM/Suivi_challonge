"""
suivi.py
--------
Récupère le classement d'un tournoi Challonge et le publie sur un salon Discord
via une « webhook », sous forme d'un message « embed » contenant un tableau aligné.

Conçu pour être exécuté automatiquement (par exemple chaque jour via GitHub
Actions), sans aucune intervention manuelle une fois en place.

Variables d'environnement attendues
-----------------------------------
CHALLONGE_API_KEY   Clé API Challonge. Compte gratuit -> https://challonge.com/settings/developer
DISCORD_WEBHOOK_URL URL de la webhook du salon Discord cible.
TOURNAMENT_SLUG     Identifiant du tournoi dans son URL Challonge.
                    Pour https://challonge.com/fr/SquadronS16D2  ->  "SquadronS16D2".

Le script ne fait que LIRE le tournoi (méthode GET de l'API). Il ne modifie
jamais le tournoi distant.

Limites connues (à lire)
------------------------
1. Le classement est calculé ici à partir des matchs TERMINÉS (état "complete"),
   en comptant victoires / défaites par participant. C'est pertinent pour un
   format ligue / round-robin. Pour une élimination directe, ce décompte reste
   affiché mais a moins de sens (il s'agit alors plutôt d'un arbre de matchs).
2. Les noms exacts des champs renvoyés par l'API Challonge sont SUPPOSÉS d'après
   la documentation publique (https://api.challonge.com/v1). Ils n'ont pas pu
   être testés en conditions réelles lors de l'écriture. En cas de résultat
   inattendu, lancer le script avec la variable d'environnement DEBUG=1 : il
   affichera la structure brute reçue, ce qui permet d'ajuster facilement.
3. L'accès en lecture à un tournoi dont on n'est PAS l'organisateur est, d'après
   la doc, autorisé pour les requêtes GET. C'est l'hypothèse retenue, à confirmer
   au premier lancement.
"""

import os
import sys
import json
from collections import defaultdict
from datetime import datetime, timezone

import requests

CHALLONGE_API_BASE = "https://api.challonge.com/v1"

# Couleur de la barre latérale de l'embed (bleu Discord), au format entier décimal.
COULEUR_EMBED = 0x5865F2

# Garde-fous de mise en forme pour rester sous les limites de l'API Discord.
LARGEUR_NOM = 18          # nb max de caractères affichés pour un nom d'équipe
MAX_LIGNES_TABLEAU = 60   # au-delà, le tableau est tronqué (sécurité anti-dépassement)


def lire_config():
    """Lit et valide la configuration depuis les variables d'environnement.

    Returns
    -------
    tuple(str, str, str)
        (api_key, webhook_url, slug)

    Raises
    ------
    SystemExit
        Si une variable obligatoire est absente ou vide. Le message indique
        précisément ce qui manque, pour faciliter le diagnostic.
    """
    api_key = os.environ.get("CHALLONGE_API_KEY", "").strip()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    slug = os.environ.get("TOURNAMENT_SLUG", "").strip()

    manquants = []
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

    return api_key, webhook, slug


def recuperer_tournoi(slug, api_key):
    """Interroge l'API Challonge et renvoie le dictionnaire 'tournament'.

    Parameters
    ----------
    slug : str
        Identifiant du tournoi (partie finale de l'URL Challonge).
    api_key : str
        Clé API Challonge.

    Returns
    -------
    dict
        Le contenu de la clé "tournament" de la réponse JSON, incluant
        "participants" et "matches".

    Raises
    ------
    SystemExit
        En cas d'erreur réseau ou de réponse HTTP non valide, avec un message
        adapté aux causes les plus probables (clé invalide, slug introuvable).
    """
    url = f"{CHALLONGE_API_BASE}/tournaments/{slug}.json"
    params = {
        "api_key": api_key,
        "include_participants": 1,
        "include_matches": 1,
    }
    try:
        reponse = requests.get(url, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"ERREUR réseau lors de l'appel à Challonge : {exc}", file=sys.stderr)
        sys.exit(1)

    if reponse.status_code == 401:
        print(
            "ERREUR : clé API Challonge refusée (401). "
            "Vérifiez CHALLONGE_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)
    if reponse.status_code == 404:
        print(
            f"ERREUR : tournoi introuvable (404) pour le slug « {slug} ». "
            "Vérifiez l'orthographe (sensible à la casse) ou l'accès au tournoi.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        reponse.raise_for_status()
    except requests.HTTPError as exc:
        print(f"ERREUR HTTP Challonge : {exc}", file=sys.stderr)
        sys.exit(1)

    donnees = reponse.json()

    if os.environ.get("DEBUG", "").strip() == "1":
        print("=== DEBUG : réponse brute Challonge ===", file=sys.stderr)
        print(json.dumps(donnees, indent=2, ensure_ascii=False)[:8000], file=sys.stderr)
        print("=== fin DEBUG ===", file=sys.stderr)

    return donnees["tournament"]


def construire_classement(tournoi):
    """Construit un classement (victoires / défaites) à partir des matchs terminés.

    La fonction est volontairement « pure » (aucun accès réseau) pour pouvoir
    être testée hors-ligne.

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
    identifiant de participant ("id"), soit, pour les formats à groupes /
    round-robin, par un identifiant de groupe ("group_player_ids"). On construit
    donc une table de correspondance qui ramène toute clé vers l'identifiant
    canonique du participant, afin de ne pas compter un même joueur deux fois.
    """
    nom_par_pid = {}
    canon = {}  # toute clé (id ou group_player_id) -> id canonique du participant

    for item in tournoi.get("participants", []):
        p = item.get("participant", item)  # tolérant aux deux formats possibles
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
    """Met en forme le classement en tableau texte aligné (police à chasse fixe).

    Parameters
    ----------
    classement : list[dict]
        Sortie de construire_classement().

    Returns
    -------
    str
        Un bloc de texte aligné, sans les balises de bloc de code (ajoutées
        ensuite par construire_embed).
    """
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
    """Construit l'objet 'embed' Discord à envoyer.

    Parameters
    ----------
    tournoi : dict
        Dictionnaire 'tournament' (pour le titre, l'URL, etc.).
    classement : list[dict]
        Sortie de construire_classement().

    Returns
    -------
    dict
        Un dictionnaire prêt à être placé dans {"embeds": [ ... ]}.
    """
    nom_tournoi = tournoi.get("name") or "Tournoi"
    url_tournoi = tournoi.get("full_challonge_url")

    tableau = formater_tableau(classement)
    description = f"```\n{tableau}\n```"

    # Sécurité : la description d'un embed est limitée à 4096 caractères.
    if len(description) > 4000:
        description = description[:3990] + "\n…```"

    horodatage = datetime.now(timezone.utc).isoformat()

    embed = {
        "title": f"Classement — {nom_tournoi}"[:256],
        "description": description,
        "color": COULEUR_EMBED,
        "timestamp": horodatage,
        "footer": {"text": "Mis à jour automatiquement"},
    }
    if url_tournoi:
        embed["url"] = url_tournoi

    return embed


def publier_sur_discord(webhook_url, embed):
    """Envoie l'embed sur le salon Discord via la webhook.

    Parameters
    ----------
    webhook_url : str
        URL de la webhook Discord.
    embed : dict
        Objet embed construit par construire_embed().

    Raises
    ------
    SystemExit
        En cas d'erreur réseau ou de réponse HTTP non valide.
    """
    payload = {"embeds": [embed]}
    try:
        reponse = requests.post(webhook_url, json=payload, timeout=30)
        reponse.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERREUR lors de la publication sur Discord : {exc}", file=sys.stderr)
        sys.exit(1)

    print("Classement publié sur Discord avec succès.")


def main():
    """Point d'entrée : enchaîne lecture config -> Challonge -> Discord."""
    api_key, webhook, slug = lire_config()
    tournoi = recuperer_tournoi(slug, api_key)
    classement = construire_classement(tournoi)
    embed = construire_embed(tournoi, classement)
    publier_sur_discord(webhook, embed)


if __name__ == "__main__":
    main()
