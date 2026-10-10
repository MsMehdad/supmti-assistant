# -*- coding: utf-8 -*-
"""
Connexion à PostgreSQL + description des tables « pages » et « chunks ».

La connexion lit les identifiants dans le fichier .env (à la racine du projet).
Rien n'est écrit en clair dans le code.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import ARRAY, REAL
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")


def creer_moteur():
    """
    Crée la connexion à la base.
    Si la variable DATABASE_URL existe, elle est utilisée (pratique pour les tests).
    Sinon on construit l'adresse à partir des variables du fichier .env.
    """
    url_complete = os.environ.get("DATABASE_URL")
    if url_complete:
        return create_engine(url_complete)

    manquantes = [v for v in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT")
                  if not os.environ.get(v)]
    if manquantes:
        raise RuntimeError(
            "Variables manquantes : " + ", ".join(manquantes)
            + ". Copie .env.example en .env puis complète-le."
        )

    url = URL.create(
        drivername="postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host="localhost",
        port=int(os.environ["POSTGRES_PORT"]),
        database=os.environ["POSTGRES_DB"],
    )
    return create_engine(url)


class Base(DeclarativeBase):
    """Classe de base de toutes les tables."""


class Page(Base):
    """Une page du site SUPMTI après nettoyage (une ligne = une page)."""

    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)   # ex. 'news-blockchain'
    url: Mapped[str] = mapped_column(String(500))
    chemin: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(50))                    # formation, actualite...
    titre: Mapped[str] = mapped_column(String(500))
    contenu: Mapped[str] = mapped_column(Text)
    langue: Mapped[str] = mapped_column(String(5))                   # 'fr' ou 'ar'
    usage: Mapped[str] = mapped_column(String(20))                   # orientation / administratif
    date_evenement: Mapped[str | None] = mapped_column(String(50), nullable=True)
    categorie: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nb_mots: Mapped[int] = mapped_column(Integer)
    hash_contenu: Mapped[str] = mapped_column(String(32))
    date_scraping: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date_import: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Chunk(Base):
    """Un morceau de page (chunk) avec son vecteur (embedding), prêt pour la recherche."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)                   # 0 = premier morceau de la page
    texte: Mapped[str] = mapped_column(Text)                         # texte réellement indexé
    nb_mots: Mapped[int] = mapped_column(Integer)
    modele: Mapped[str | None] = mapped_column(String(100), nullable=True)   # modèle d'embedding utilisé
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(REAL), nullable=True)
    date_creation: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )