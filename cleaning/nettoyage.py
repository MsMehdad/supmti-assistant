# -*- coding: utf-8 -*-
"""
ÉTAPE 2 — NETTOYAGE des données collectées

Lancer (depuis n'importe quel dossier) :
    python cleaning/nettoyage.py

Entrée  : data/raw/supmti_data.json         (produit par l'étape 1)
Sortie  : data/processed/pages_propres.json (une entrée par page utile)

Ce que fait ce script :
  1. retire les pages sans intérêt pour le chatbot (formulaire de bourse, liste d'articles) ;
  2. retire les lignes de l'interface du site (« Accueil », « Revenir en arrière »...) ;
  3. coupe le texte juridique (CGU) de la page contact ;
  4. transforme les étiquettes des actualités (date, catégorie) en champs séparés ;
  5. ajoute des champs utiles : titre propre, langue, usage, id ;
  6. contrôle qu'il ne reste ni page trop courte ni doublon.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

# ----------------------------------------------------------------------
# CONFIGURATION (tout ce que tu peux modifier est ici)
# ----------------------------------------------------------------------

RACINE = Path(__file__).resolve().parent.parent
FICHIER_ENTREE = RACINE / "data" / "raw" / "supmti_data.json"
FICHIER_SORTIE = RACINE / "data" / "processed" / "pages_propres.json"

MIN_CHARS = 100  # une page plus courte est rejetée

# Pages qu'on ne garde pas pour le chatbot : chemin -> raison
PAGES_EXCLUES = {
    "/candidature": "formulaire de bourse (liste de villes + CGU), sans information utile",
    "/news": "simple liste d'articles, déjà couverts par chaque article",
}

# Lignes de l'interface du site, présentes sur beaucoup de pages, sans information
LIGNES_INTERFACE = {"Accueil", "Revenir en arrière", "Lire la suite", "Fermer"}

# Étiquettes des articles : on supprime l'étiquette, on garde le texte qui suit
ETIQUETTES_ARTICLE = {"Description", "Contenu", "Informations"}

# Lignes à retirer sur une page précise (ici : les champs du formulaire de contact)
LIGNES_A_RETIRER_PAR_PAGE = {
    "/contact": {
        "Entrer en contact", "Votre nom", "Votre adresse e-mail", "Votre sujet",
        "Numéro de contact", "Message", "J'ai lu et j'accepte les",
        "Conditions Générales d'Utilisation", "Envoyer le message",
    },
}

# Sur ces pages, on coupe le texte à partir de la première ligne qui commence ainsi
COUPER_A_PARTIR_DE = {
    "/contact": "Les présentes Conditions Générales d'Utilisation",
}

# Articles qui sont des documents administratifs internes (règlement, statut, PV...).
# On les garde dans les données mais on les marque, pour décider plus tard
# s'ils doivent être indexés par le chatbot d'orientation.
ARTICLES_ADMINISTRATIFS = {
    "autorisation-absence-personnel", "convocation", "demande", "fiche-evaluation",
    "note-interne", "pv", "reglement", "statut",
}


# ----------------------------------------------------------------------
# FONCTIONS DE NETTOYAGE
# ----------------------------------------------------------------------

def normaliser(ligne):
    """Remplace l'apostrophe typographique ’ par ' pour comparer sans erreur."""
    return ligne.replace("’", "'").strip()


def nettoyer_lignes(chemin, lignes):
    """Applique les règles de nettoyage communes et celles propres à une page."""
    # Couper le texte juridique s'il y en a un sur cette page
    debut_coupure = COUPER_A_PARTIR_DE.get(chemin)
    if debut_coupure:
        for i, ligne in enumerate(lignes):
            if normaliser(ligne).startswith(debut_coupure):
                lignes = lignes[:i]
                break

    a_retirer = LIGNES_INTERFACE | LIGNES_A_RETIRER_PAR_PAGE.get(chemin, set())
    return [l for l in lignes if normaliser(l) not in a_retirer]


def traiter_article(lignes):
    """
    Dans un article, « Date de l'événement » puis « Catégorie » sont des étiquettes
    suivies de leur valeur. On extrait les deux valeurs et on retire les étiquettes.
    Retourne (lignes_propres, date, categorie).
    """
    date, categorie, propres = None, None, []
    i = 0
    while i < len(lignes):
        ligne = normaliser(lignes[i])
        if ligne == "Date de l'événement" and i + 1 < len(lignes):
            date = lignes[i + 1].strip()
            i += 2
            continue
        if ligne == "Catégorie" and i + 1 < len(lignes):
            categorie = lignes[i + 1].strip()
            i += 2
            continue
        if ligne not in ETIQUETTES_ARTICLE:
            propres.append(lignes[i])
        i += 1
    return propres, date, categorie


def detecter_langue(texte):
    """'ar' si plus de la moitié des lettres sont arabes, sinon 'fr'."""
    arabes = len(re.findall(r"[\u0600-\u06FF]", texte))
    lettres = len(re.findall(r"[A-Za-z\u00C0-\u00FF\u0600-\u06FF]", texte))
    return "ar" if lettres and arabes / lettres > 0.5 else "fr"


def creer_id(chemin):
    """'/news/blockchain' -> 'news-blockchain' ; '/' -> 'accueil'."""
    return chemin.strip("/").replace("/", "-") or "accueil"


def hash_contenu(texte):
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ----------------------------------------------------------------------

def nettoyer(pages_brutes):
    propres, rejetees, hashes = [], [], set()

    for page in pages_brutes:
        chemin = page["chemin"]

        if chemin in PAGES_EXCLUES:
            rejetees.append((chemin, PAGES_EXCLUES[chemin]))
            continue

        lignes = nettoyer_lignes(chemin, page["contenu"].split("\n"))
        date_evenement = categorie = None
        if page["type"] == "actualite":
            lignes, date_evenement, categorie = traiter_article(lignes)

        contenu = "\n".join(lignes).strip()
        if len(contenu) < MIN_CHARS:
            rejetees.append((chemin, f"trop court après nettoyage ({len(contenu)} caractères)"))
            continue

        h = hash_contenu(contenu)
        if h in hashes:
            rejetees.append((chemin, "doublon exact d'une autre page"))
            continue
        hashes.add(h)

        # Titre : pour un article, c'est la 1re ligne (le <title> HTML est toujours
        # « Actualités ») ; pour les autres pages, on retire le préfixe « SUPMTI Oujda - ».
        if page["type"] == "actualite":
            titre = lignes[0].strip()
        else:
            titre = re.sub(r"^SUPMTI Oujda\s*-\s*", "", page.get("title", "")).strip()

        slug = chemin.rsplit("/", 1)[-1]
        usage = ("administratif"
                 if page["type"] == "actualite" and slug in ARTICLES_ADMINISTRATIFS
                 else "orientation")

        propres.append({
            "id": creer_id(chemin),
            "url": page["url"],
            "chemin": chemin,
            "type": page["type"],
            "titre": titre,
            "contenu": contenu,
            "langue": detecter_langue(contenu),
            "usage": usage,
            "date_evenement": date_evenement,
            "categorie": categorie,
            "nb_mots": len(contenu.split()),
            "hash_contenu": h,
            "date_scraping": page.get("date_scraping"),
        })
    return propres, rejetees


def rapport(propres, rejetees, nb_avant):
    df = pd.DataFrame(propres)
    print("=" * 55)
    print("RAPPORT DE NETTOYAGE")
    print("=" * 55)
    print(f"Pages avant : {nb_avant}  |  conservées : {len(df)}  |  rejetées : {len(rejetees)}")
    print("\nPar type :")
    resume = df.groupby("type").agg(pages=("id", "count"), mots_moyens=("nb_mots", "mean")).round(0)
    print(resume.to_string())
    print("\nPar usage :")
    print(df.groupby("usage").size().to_string())
    print("\nPar langue :")
    print(df.groupby("langue").size().to_string())
    print("\nContrôles :")
    print(f"  identifiants en double : {int(df['id'].duplicated().sum())}")
    print(f"  contenus en double     : {int(df['hash_contenu'].duplicated().sum())}")
    print(f"  page la plus courte    : {int(df['nb_mots'].min())} mots")
    if rejetees:
        print("\nPages rejetées (chemin : raison) :")
        for chemin, raison in rejetees:
            print(f"  {chemin} : {raison}")
    print("=" * 55)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not FICHIER_ENTREE.exists():
        sys.exit(f"Fichier introuvable : {FICHIER_ENTREE}\nLance d'abord l'étape 1 (scraper).")

    with open(FICHIER_ENTREE, "r", encoding="utf-8") as f:
        pages_brutes = json.load(f)

    propres, rejetees = nettoyer(pages_brutes)

    FICHIER_SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with open(FICHIER_SORTIE, "w", encoding="utf-8") as f:
        json.dump(propres, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] {FICHIER_SORTIE} -> {len(propres)} pages\n")

    rapport(propres, rejetees, len(pages_brutes))


if __name__ == "__main__":
    main()