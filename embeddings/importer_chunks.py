# -*- coding: utf-8 -*-
"""
ÉTAPE 4 — CHUNKS ET EMBEDDINGS : partie « import dans PostgreSQL »

Lancer (la base doit être démarrée avec « docker compose up -d ») :
    python embeddings/importer_chunks.py

Entrée : data/processed/chunks_embeddings.json (produit par calculer_embeddings.py)
Sortie : la table « chunks » de PostgreSQL

Ce script est léger : il n'a pas besoin de PyTorch ni du modèle d'embedding.
On peut le relancer : la table « chunks » est reconstruite à chaque fois.
"""

import json
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "database"))      # pour retrouver models.py
from models import Base, Chunk, Page, creer_moteur  # noqa: E402

FICHIER_ENTREE = RACINE / "data" / "processed" / "chunks_embeddings.json"


def controler(donnees, ids_pages_en_base):
    """Vérifie le fichier avant de toucher à la base. Arrête le programme si un problème est trouvé."""
    chunks = donnees["chunks"]
    if not chunks:
        sys.exit("Le fichier ne contient aucun chunk.")

    mauvaises = [c for c in chunks if len(c["embedding"]) != donnees["dimensions"]]
    if mauvaises:
        sys.exit(f"{len(mauvaises)} chunk(s) n'ont pas {donnees['dimensions']} dimensions.")

    inconnues = {c["page_id"] for c in chunks} - set(ids_pages_en_base)
    if inconnues:
        sys.exit("Pages absentes de la base (relance l'étape 3) : " + ", ".join(sorted(inconnues)[:5]))


def importer(donnees, moteur):
    """Vide la table chunks puis y enregistre chaque chunk avec son vecteur."""
    Base.metadata.create_all(moteur)

    with Session(moteur) as session:
        ids_pages = session.scalars(select(Page.id)).all()
    controler(donnees, ids_pages)

    with Session(moteur) as session:
        session.execute(delete(Chunk))
        for c in donnees["chunks"]:
            session.add(Chunk(
                page_id=c["page_id"],
                position=c["position"],
                texte=c["texte"],
                nb_mots=c["nb_mots"],
                modele=donnees["modele"],
                embedding=c["embedding"],
            ))
        session.commit()


def verifier(moteur):
    """Relit la base et affiche des contrôles."""
    with Session(moteur) as session:
        total = session.scalar(select(func.count()).select_from(Chunk))
        pages_avec_chunks = session.scalar(select(func.count(func.distinct(Chunk.page_id))))
        modeles = session.scalars(select(Chunk.modele).distinct()).all()
        vecteurs = np.array(session.scalars(select(Chunk.embedding)).all(), dtype=np.float32)

    normes = np.linalg.norm(vecteurs, axis=1)
    print(f"\nChunks en base        : {total}")
    print(f"Pages avec des chunks : {pages_avec_chunks}")
    print(f"Modèle                : {', '.join(modeles)}")
    print(f"Dimensions            : {vecteurs.shape[1]}")
    print(f"Norme des vecteurs    : {normes.min():.3f} à {normes.max():.3f} (attendu : 1.000)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not FICHIER_ENTREE.exists():
        sys.exit(f"Fichier introuvable : {FICHIER_ENTREE}\n"
                 "Calcule d'abord les embeddings (Colab ou calculer_embeddings.py).")

    with open(FICHIER_ENTREE, "r", encoding="utf-8") as f:
        donnees = json.load(f)

    moteur = creer_moteur()
    importer(donnees, moteur)
    print(f"[OK] {len(donnees['chunks'])} chunks importés (modèle {donnees['modele']})")
    verifier(moteur)


if __name__ == "__main__":
    main()