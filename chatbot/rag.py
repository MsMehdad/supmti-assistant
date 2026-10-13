# -*- coding: utf-8 -*-
"""
ÉTAPE 5 — LE CHATBOT RAG

Lancer l'interface :      python chatbot/rag.py
Tester dans le terminal : python chatbot/rag.py "Quelles certifications Cisco sont proposées ?"

Pipeline à chaque question :
  1. la question est transformée en vecteur (même modèle que les documents) ;
  2. on garde les chunks dont le vecteur est le plus proche ;
  3. ces chunks + la question sont envoyés au LLM (via Groq) ;
  4. la réponse s'affiche avec les pages sources.
"""

import os
import sys
from pathlib import Path

import gradio as gr
import numpy as np
from dotenv import load_dotenv
from groq import Groq
from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.orm import Session

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "database"))
from models import Chunk, Page, creer_moteur  # noqa: E402

load_dotenv(RACINE / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------
MODELE_EMBEDDING = "intfloat/multilingual-e5-base"   # DOIT être le même que pour les documents
MODELE_LLM = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
NB_CHUNKS = 4                                        # nombre de chunks envoyés au LLM

CONSIGNE = (
    "Tu es l'assistant officiel de SUPMTI Oujda. "
    "Réponds à la question en t'appuyant UNIQUEMENT sur le CONTEXTE fourni. "
    "Réponds dans la langue de la question, de façon claire et concise. "
    "Si le contexte ne contient pas la réponse, dis-le honnêtement et "
    "conseille de contacter directement l'école. N'invente aucune information."
)


# ----------------------------------------------------------------------
# CHARGEMENT (une seule fois, au démarrage)
# ----------------------------------------------------------------------
def charger_base():
    """Lit tous les chunks (avec titre et url de leur page) depuis PostgreSQL."""
    moteur = creer_moteur()
    with Session(moteur) as session:
        lignes = session.execute(
            select(Chunk.texte, Chunk.embedding, Page.titre, Page.url)
            .join(Page, Page.id == Chunk.page_id)
            .order_by(Chunk.id)
        ).all()
    if not lignes:
        sys.exit("La table chunks est vide : lance d'abord embeddings/importer_chunks.py")
    infos = [{"texte": l.texte, "titre": l.titre, "url": l.url} for l in lignes]
    vecteurs = np.array([l.embedding for l in lignes], dtype=np.float32)
    return infos, vecteurs


cle_groq = os.environ.get("GROQ_API_KEY")
if not cle_groq:
    sys.exit("GROQ_API_KEY manquante : ajoute-la dans le fichier .env")

print("Lecture de la base...")
INFOS, VECTEURS = charger_base()
print(f"{len(INFOS)} chunks chargés. Chargement du modèle d'embedding...")
MODELE = SentenceTransformer(MODELE_EMBEDDING)
CLIENT = Groq(api_key=cle_groq)


# ----------------------------------------------------------------------
# RECHERCHE + RÉPONSE
# ----------------------------------------------------------------------
def rechercher(question):
    """Retourne les NB_CHUNKS chunks les plus proches de la question, avec leur score."""
    v = MODELE.encode(["query: " + question], normalize_embeddings=True)[0]
    scores = VECTEURS @ v                      # similarité cosinus avec chaque chunk
    meilleurs = np.argsort(-scores)[:NB_CHUNKS]
    return [(INFOS[i], float(scores[i])) for i in meilleurs]


def repondre(question, historique=None):
    trouves = rechercher(question)
    contexte = "\n\n---\n\n".join(f"[{c['titre']}]\n{c['texte']}" for c, _ in trouves)

    messages = [
        {"role": "system", "content": CONSIGNE},
        {"role": "user", "content": f"CONTEXTE :\n{contexte}\n\nQUESTION : {question}"},
    ]
    try:
        reponse = CLIENT.chat.completions.create(
            model=MODELE_LLM, messages=messages, temperature=0.2, max_tokens=2000
        )
        texte = reponse.choices[0].message.content
    except Exception as erreur:
        return f"Erreur lors de l'appel à Groq : {erreur}"

    sources = []
    for c, _ in trouves:
        if c["url"] not in sources:
            sources.append(c["url"])
    return texte + "\n\n**Sources :**\n" + "\n".join(f"- {u}" for u in sources)


# ----------------------------------------------------------------------
# INTERFACE (apparence)
# ----------------------------------------------------------------------
THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "sans-serif"],
    radius_size="md",
)

CSS = """
.gradio-container { max-width: 880px !important; margin: auto !important; }

.entete {
    padding: 26px 30px;
    margin-bottom: 14px;
    border-radius: 10px;
    background: linear-gradient(135deg, #0f2a4a 0%, #1e4a7a 100%);
    border-bottom: 4px solid #3b82f6;
}
.entete .etiquette {
    margin: 0 0 6px 0;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #93c5fd;
}
.entete h1 {
    margin: 0;
    font-size: 1.7rem;
    font-weight: 600;
    color: #ffffff;
}
.entete .sous-titre {
    margin: 8px 0 0 0;
    font-size: 0.95rem;
    color: #dbeafe;
}

.pied {
    margin-top: 10px;
    text-align: center;
    font-size: 0.8rem;
    opacity: 0.7;
}
"""

ENTETE = """
<div class="entete">
  <p class="etiquette">SUPMTI Oujda</p>
  <h1>Assistant virtuel</h1>
  <p class="sous-titre">
    Formations, admission, débouchés : posez votre question,
    la réponse s'appuie sur les pages du site officiel.
  </p>
</div>
"""

PIED = """
<div class="pied">
  Les réponses sont générées par une intelligence artificielle à partir du site de SUPMTI.
  Vérifiez les informations importantes auprès de l'établissement.
</div>
"""

EXEMPLES = [
    "Où se trouve SUPMTI Oujda ?",
    "Quels sont les débouchés de la cybersécurité ?",
    "Quelles certifications Cisco sont proposées ?",
    "Comment s'inscrire à SUPMTI ?",
]


def construire_interface():
    with gr.Blocks() as demo:
        gr.HTML(ENTETE)
        gr.ChatInterface(
            fn=repondre,
            chatbot=gr.Chatbot(
                height=460,
                show_label=False,
                placeholder="Bonjour. Posez-moi une question sur SUPMTI Oujda.",
            ),
            textbox=gr.Textbox(
                placeholder="Écrivez votre question ici...",
                container=False,
                scale=7,
            ),
            examples=EXEMPLES,
        )
        gr.HTML(PIED)
    return demo


# ----------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ----------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print("\n=== Chunks trouvés ===")
        for c, score in rechercher(question):
            print(f"{score:.3f} | {c['titre']}")
        print("\n=== Réponse ===")
        print(repondre(question))
    else:
        construire_interface().launch(theme=THEME, css=CSS)