# -*- coding: utf-8 -*-
"""
ÉTAPE 4 — CHUNKS ET EMBEDDINGS : partie « calcul »

Ce script peut tourner sur ton PC ou sur Google Colab. Il n'a pas besoin de la base de données.

  Sur ton PC :   python embeddings/calculer_embeddings.py
  Sur Colab  :   python calculer_embeddings.py --entree pages_propres.json --sortie chunks_embeddings.json

Entrée : pages_propres.json      (produit par l'étape 2)
Sortie : chunks_embeddings.json  (chunks + vecteurs)

Ensuite, importer_chunks.py envoie ce fichier dans PostgreSQL.

Ce que fait le script :
  1. découpe chaque page en chunks (petits morceaux de texte) ;
  2. transforme chaque chunk en vecteur de nombres (embedding) avec un modèle e5 ;
  3. enregistre chunks + vecteurs dans un fichier JSON ;
  4. fait un petit essai de recherche pour vérifier que ça fonctionne.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parent.parent
ENTREE_DEFAUT = RACINE / "data" / "processed" / "pages_propres.json"
SORTIE_DEFAUT = RACINE / "data" / "processed" / "chunks_embeddings.json"

# ----------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------

# Modèle d'embedding. Version plus légère (vecteurs de 384 nombres) :
#   "intfloat/multilingual-e5-small"
MODELE = "intfloat/multilingual-e5-base"

MAX_MOTS = 180   # taille visée d'un chunk (le modèle lit au maximum 512 « tokens » ≈ 350 mots)
MIN_MOTS = 40    # un dernier chunk plus court que ça est collé au précédent

QUESTIONS_ESSAI = [
    "Où se trouve SUPMTI Oujda ?",
    "Quels sont les débouchés de la cybersécurité ?",
    "Quelles certifications Cisco sont proposées ?",
]


# ----------------------------------------------------------------------
# DÉCOUPAGE
# ----------------------------------------------------------------------

def decouper(contenu):
    """
    Regroupe les lignes d'une page en chunks d'environ MAX_MOTS mots.
    On ne coupe jamais au milieu d'une ligne : une liste ou un paragraphe reste entier.
    """
    lignes = [l.strip() for l in contenu.split("\n") if l.strip()]
    chunks, courant, mots = [], [], 0

    for ligne in lignes:
        n = len(ligne.split())
        if courant and mots + n > MAX_MOTS:
            chunks.append("\n".join(courant))
            courant, mots = [], 0
        courant.append(ligne)
        mots += n
    if courant:
        chunks.append("\n".join(courant))

    # Un tout petit dernier morceau est regroupé avec le précédent
    if len(chunks) > 1 and len(chunks[-1].split()) < MIN_MOTS:
        dernier = chunks.pop()
        chunks[-1] += "\n" + dernier
    return chunks


def avec_titre(titre, texte):
    """
    Ajoute le titre de la page en tête du chunk (sauf s'il y est déjà).
    Ainsi, un chunk du milieu d'une page « Cybersécurité » mentionne quand même « Cybersécurité ».
    """
    if titre and not texte.startswith(titre):
        return f"{titre}\n{texte}"
    return texte


def construire_chunks(pages):
    """Retourne une liste de dictionnaires : page_id, position, texte, nb_mots."""
    resultat = []
    for page in pages:
        for position, morceau in enumerate(decouper(page["contenu"])):
            texte = avec_titre(page["titre"], morceau)
            resultat.append({
                "page_id": page["id"],
                "position": position,
                "texte": texte,
                "nb_mots": len(texte.split()),
            })
    return resultat


# ----------------------------------------------------------------------
# EMBEDDINGS
# ----------------------------------------------------------------------
# Règle des modèles e5 : les DOCUMENTS sont encodés avec le préfixe « passage: »
# et les QUESTIONS avec le préfixe « query: ». Sans ça, la recherche est moins bonne.

def encoder_documents(modele, textes):
    vecteurs = modele.encode(
        ["passage: " + t for t in textes],
        normalize_embeddings=True,      # vecteurs de longueur 1 : le produit scalaire = similarité cosinus
        batch_size=16,
        show_progress_bar=True,
    )
    return np.asarray(vecteurs, dtype=np.float32)


def encoder_question(modele, question):
    v = modele.encode(["query: " + question], normalize_embeddings=True)
    return np.asarray(v, dtype=np.float32)[0]


def apercu_recherche(modele, chunks, vecteurs):
    """Essai : pour quelques questions, affiche les 3 chunks les plus proches."""
    print("\n=== ESSAI DE RECHERCHE (aperçu de l'étape 5) ===")
    for question in QUESTIONS_ESSAI:
        scores = vecteurs @ encoder_question(modele, question)   # similarité cosinus avec chaque chunk
        meilleurs = np.argsort(-scores)[:3]
        print(f"\nQuestion : {question}")
        for i in meilleurs:
            print(f"  {scores[i]:.3f} | {chunks[i]['page_id']} (chunk {chunks[i]['position']})")


# ----------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ----------------------------------------------------------------------

def executer(pages, modele, nom_modele):
    """Découpe, calcule les vecteurs, et retourne le résultat sous forme de dictionnaire."""
    chunks = construire_chunks(pages)
    tailles = [c["nb_mots"] for c in chunks]
    print(f"{len(pages)} pages -> {len(chunks)} chunks "
          f"(mots par chunk : min {min(tailles)}, moyenne {sum(tailles) // len(tailles)}, max {max(tailles)})")
    if max(tailles) > 330:
        print("ATTENTION : un chunk dépasse 330 mots, le modèle risque de tronquer la fin.")

    vecteurs = encoder_documents(modele, [c["texte"] for c in chunks])
    print(f"Vecteurs : {vecteurs.shape[0]} x {vecteurs.shape[1]} dimensions")

    apercu_recherche(modele, chunks, vecteurs)

    return {
        "modele": nom_modele,
        "dimensions": int(vecteurs.shape[1]),
        "date_calcul": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chunks": [
            {**c, "embedding": [round(float(x), 6) for x in v]}
            for c, v in zip(chunks, vecteurs)
        ],
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parseur = argparse.ArgumentParser(description="Chunks et embeddings des pages SUPMTI")
    parseur.add_argument("--entree", type=Path, default=ENTREE_DEFAUT, help="pages_propres.json")
    parseur.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT, help="chunks_embeddings.json")
    args = parseur.parse_args()

    if not args.entree.exists():
        sys.exit(f"Fichier introuvable : {args.entree}")
    with open(args.entree, "r", encoding="utf-8") as f:
        pages = json.load(f)

    from sentence_transformers import SentenceTransformer   # import lent : fait ici volontairement
    print(f"Chargement du modèle {MODELE} (le premier lancement le télécharge)...")
    modele = SentenceTransformer(MODELE)

    resultat = executer(pages, modele, MODELE)

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False)
    taille = args.sortie.stat().st_size / 1024
    print(f"\n[SAVE] {args.sortie} -> {len(resultat['chunks'])} chunks ({taille:.0f} Ko)")


if __name__ == "__main__":
    main()
