# -*- coding: utf-8 -*-
"""
ÉTAPE 1 — COLLECTE : scraper de supmtioujda.ma

Lancer (depuis n'importe quel dossier) :
    python scraper/supmti_scraper.py

Sortie :
    data/raw/supmti_data.json   (une entrée par page utile)

Chaque entrée contient : url, chemin, type, title, description, contenu,
nb_mots, hash_contenu, date_scraping.
"""

import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ----------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------

BASE_URL = "https://supmtioujda.ma"
DELAY = 1.5              # secondes entre deux requêtes (politesse envers le serveur)
MIN_CHARS = 100          # en dessous : page vide ou page de connexion -> rejetée
MAX_PAGES_NEWS = 10      # nombre maximum de pages de la liste d'actualités

# Si le site bloque ce User-Agent, remplace-le par un User-Agent de navigateur.
USER_AGENT = "Mozilla/5.0 (compatible; SupmtiAssistantBot/1.0; projet-etudiant)"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

OUT_FILE = Path(__file__).resolve().parent.parent / "data" / "raw" / "supmti_data.json"

# Pages connues. Les actualités (/news et articles) sont gérées à part.
PAGES = [
    "/",
    "/about",
    "/mot-directeur",
    "/training",
    "/training-mge",
    "/training-prepa",
    "/training-isi",
    "/training-cisi",
    "/training-grh",
    "/training-cca",
    "/training-cybersecurite",
    "/training-tranformation_digitale",
    "/certification",
    "/current-students",
    "/future-students",
    "/contact",
    "/candidature",
]

# Chemins à ignorer : connexion, inscription, fichiers statiques.
EXCLUS = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|zip|css|js|ico)$"
    r"|login|logout|register|mot-de-passe|pre-registration",
    re.IGNORECASE,
)

# Balises supprimées avant d'extraire le texte.
# select/option : supprime les listes de villes des formulaires.
BALISES_BRUIT = [
    "script", "style", "noscript", "nav", "footer", "head",
    "select", "option", "input", "textarea", "button", "svg", "iframe",
]


# ----------------------------------------------------------------------
# RÉSEAU
# ----------------------------------------------------------------------

def creer_session():
    """Session HTTP avec 3 tentatives automatiques en cas d'erreur temporaire."""
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update(HEADERS)
    return s


def charger_robots(session):
    """Lit robots.txt. Retourne None s'il est absent (tout est alors autorisé)."""
    rp = RobotFileParser()
    try:
        r = session.get(BASE_URL + "/robots.txt", timeout=10)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
            print("[INIT] robots.txt chargé")
            return rp
    except requests.RequestException:
        pass
    print("[INIT] pas de robots.txt exploitable")
    return None


def autorise(rp, chemin):
    return rp is None or rp.can_fetch(USER_AGENT, BASE_URL + chemin)


def get_page(session, chemin):
    """Télécharge une page. Retourne (soup, url), ou (None, url) en cas d'échec."""
    url = urljoin(BASE_URL, chemin)
    try:
        r = session.get(url, timeout=20)
    except requests.RequestException as e:
        print(f"  [ERR] {url} | {e}")
        return None, url
    print(f"  [{r.status_code}] {url}")
    if r.status_code != 200:
        return None, url
    return BeautifulSoup(r.text, "html.parser"), url


# ----------------------------------------------------------------------
# EXTRACTION
# ----------------------------------------------------------------------

def normaliser_chemin(href):
    """
    Transforme un lien en chemin interne propre : '/contact'.
    Retourne None pour un lien externe, une ancre, un mailto, etc.
    """
    href = (href or "").strip()
    if not href or href.startswith(("#", "//", "mailto:", "tel:", "javascript:")):
        return None
    if href.startswith(("http://", "https://")):
        p = urlparse(href)
        if p.netloc != urlparse(BASE_URL).netloc:
            return None
        href = p.path
    elif not href.startswith("/"):
        return None
    chemin = href.split("#")[0].split("?")[0]
    if len(chemin) > 1:
        chemin = chemin.rstrip("/")
    return chemin or "/"


def extraire_metadata(soup):
    title = soup.find("title")
    desc = (soup.find("meta", attrs={"name": "description"})
            or soup.find("meta", attrs={"property": "og:description"}))
    return {
        "title": title.get_text(strip=True) if title else "",
        "description": desc.get("content", "") if desc else "",
    }


def extraire_contenu(soup):
    """Texte visible de la page, sans bruit, ligne par ligne, sans doublons."""
    s = BeautifulSoup(str(soup), "html.parser")  # copie : on ne modifie pas l'original
    for tag in s.find_all(BALISES_BRUIT):
        tag.decompose()

    body = s.find("body")
    if not body:
        return ""

    vues = set()
    lignes = []
    for ligne in body.get_text(separator="\n").splitlines():
        ligne = ligne.strip()
        if len(ligne) < 3 or ligne in ("#!", "#") or ligne in vues:
            continue
        vues.add(ligne)
        lignes.append(ligne)
    return "\n".join(lignes)


def extraire_liens_internes(soup):
    liens = set()
    for a in soup.find_all("a", href=True):
        chemin = normaliser_chemin(a["href"])
        if chemin:
            liens.add(chemin)
    return liens


def detecter_type(chemin):
    if chemin == "/":
        return "accueil"
    if "/news/" in chemin:
        return "actualite"
    if "news" in chemin:
        return "actualites_index"
    if "training" in chemin:
        return "formation"
    if "contact" in chemin:
        return "contact"
    if "about" in chemin or "directeur" in chemin:
        return "presentation"
    if "student" in chemin:
        return "etudiants"
    if "certif" in chemin:
        return "certification"
    if "candidature" in chemin:
        return "admission"
    return "page"


def hash_contenu(contenu):
    return hashlib.sha256(contenu.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------
# SCRAPER PRINCIPAL
# ----------------------------------------------------------------------

def scraper_site():
    print("=" * 55)
    print("SCRAPER SUPMTI OUJDA - " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 55)

    session = creer_session()
    robots = charger_robots(session)

    resultats = []
    visitees = set()
    hashes = set()
    decouverts = set()
    rejetees = []  # (chemin, raison)
    maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def enregistrer(chemin, url, soup):
        """Extrait, filtre (page courte, doublon) et ajoute à la liste des résultats."""
        decouverts.update(extraire_liens_internes(soup))
        contenu = extraire_contenu(soup)
        if len(contenu) < MIN_CHARS:
            rejetees.append((chemin, f"contenu trop court ({len(contenu)} caractères)"))
            return
        h = hash_contenu(contenu)
        if h in hashes:
            rejetees.append((chemin, "doublon exact d'une autre page"))
            return
        hashes.add(h)
        meta = extraire_metadata(soup)
        print(f"    -> {len(contenu)} caractères extraits")
        resultats.append({
            "url": url,
            "chemin": chemin,
            "type": detecter_type(chemin),
            "title": meta["title"],
            "description": meta["description"],
            "contenu": contenu,
            "nb_mots": len(contenu.split()),
            "hash_contenu": h,
            "date_scraping": maintenant,
        })

    def traiter(chemin):
        """Télécharge et enregistre une page, si elle n'a pas déjà été vue."""
        if chemin in visitees:
            return
        visitees.add(chemin)
        if EXCLUS.search(chemin):
            rejetees.append((chemin, "exclue (connexion, inscription ou fichier)"))
            return
        if not autorise(robots, chemin):
            rejetees.append((chemin, "interdite par robots.txt"))
            return
        soup, url = get_page(session, chemin)
        time.sleep(DELAY)
        if soup is None:
            rejetees.append((chemin, "erreur de téléchargement"))
            return
        enregistrer(chemin, url, soup)

    # --- 1. Pages connues ---
    print(f"\n[1/3] Pages connues ({len(PAGES)} URLs)...")
    for chemin in PAGES:
        traiter(chemin)

    # --- 2. Actualités : liste paginée, puis chaque article ---
    print("\n[2/3] Actualités...")
    articles = set()
    for n in range(1, MAX_PAGES_NEWS + 1):
        chemin_liste = "/news" if n == 1 else f"/news?page={n}"
        soup, url = get_page(session, chemin_liste)
        time.sleep(DELAY)
        if soup is None:
            break
        if n == 1:
            visitees.add("/news")
            enregistrer("/news", url, soup)
        trouves = {
            c for c in extraire_liens_internes(soup)
            if re.fullmatch(r"/news/[a-z0-9\-_]+", c)
        }
        if not (trouves - articles):   # plus de nouveaux articles : fin de la pagination
            break
        articles |= trouves
    print(f"    {len(articles)} articles trouvés")
    for chemin in sorted(articles):
        traiter(chemin)

    # --- 3. Pages découvertes via les liens (un seul niveau) ---
    print("\n[3/3] Pages découvertes via les liens...")
    for chemin in sorted(decouverts - visitees):
        traiter(chemin)

    return resultats, rejetees


# ----------------------------------------------------------------------
# EXPORT + RAPPORT
# ----------------------------------------------------------------------

def sauvegarder_json(donnees, fichier=OUT_FILE):
    fichier.parent.mkdir(parents=True, exist_ok=True)
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVE] {fichier} -> {len(donnees)} pages")


def rapport(donnees, rejetees):
    print("\n" + "=" * 55)
    print("RAPPORT FINAL")
    print("=" * 55)
    print(f"Pages conservées : {len(donnees)}")
    print(f"Pages rejetées   : {len(rejetees)}")
    print("\nPar type :")
    for t, n in sorted(Counter(d["type"] for d in donnees).items()):
        print(f"  {t:<20}{n}")
    print(f"\n~{sum(d['nb_mots'] for d in donnees)} mots au total")
    if rejetees:
        print("\nPages rejetées (chemin : raison) :")
        for chemin, raison in rejetees:
            print(f"  {chemin} : {raison}")
    print("=" * 55)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    donnees, rejetees = scraper_site()
    sauvegarder_json(donnees)
    rapport(donnees, rejetees)