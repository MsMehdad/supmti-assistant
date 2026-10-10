# -*- coding: utf-8 -*-
"""
ÉTAPE 3 — STOCKAGE : charge pages_propres.json dans PostgreSQL

Lancer (la base doit être démarrée avec « docker compose up -d ») :
    python database/charger_pages.py

On peut le relancer autant de fois qu'on veut : une page déjà présente est mise
à jour, une nouvelle page est ajoutée (pas de doublon).
"""

import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Base, Page, creer_moteur

RACINE = Path(__file__).resolve().parent.parent
FICHIER_ENTREE = RACINE / "data" / "processed" / "pages_propres.json"

# Colonnes à remplir depuis le JSON (date_import est remplie automatiquement)
COLONNES = [c.name for c in Page.__table__.columns if c.name != "date_import"]


def charger(pages, moteur):
    """Crée la table si besoin, puis insère ou met à jour chaque page."""
    Base.metadata.create_all(moteur)
    with Session(moteur) as session:
        for p in pages:
            champs = {nom: p.get(nom) for nom in COLONNES}
            session.merge(Page(**champs))   # merge = insère, ou met à jour si l'id existe
        session.commit()


def verifier(moteur):
    """Affiche quelques statistiques lues directement dans la base."""
    with Session(moteur) as session:
        total = session.scalar(select(func.count()).select_from(Page))
        print(f"\nPages en base : {total}")

        print("\nPar type :")
        for type_page, n in session.execute(
            select(Page.type, func.count()).group_by(Page.type).order_by(Page.type)
        ):
            print(f"  {type_page:<18}{n}")

        print("\nPar usage :")
        for usage, n in session.execute(
            select(Page.usage, func.count()).group_by(Page.usage).order_by(Page.usage)
        ):
            print(f"  {usage:<18}{n}")

        exemple = session.scalar(select(Page).where(Page.id == "training-cybersecurite"))
        if exemple:
            print(f"\nExemple : {exemple.id} | {exemple.titre} | {exemple.nb_mots} mots")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not FICHIER_ENTREE.exists():
        sys.exit(f"Fichier introuvable : {FICHIER_ENTREE}\nLance d'abord l'étape 2 (nettoyage).")

    with open(FICHIER_ENTREE, "r", encoding="utf-8") as f:
        pages = json.load(f)

    moteur = creer_moteur()
    charger(pages, moteur)
    print(f"[OK] {len(pages)} pages envoyées vers la base")
    verifier(moteur)


if __name__ == "__main__":
    main()