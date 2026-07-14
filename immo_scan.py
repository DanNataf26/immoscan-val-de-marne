#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ImmoScan Val-de-Marne — Prototype v0.1
========================================
Objectif : détecter des maisons/immeubles à fort potentiel de valorisation
ou sous-estimés, sur le Val-de-Marne (94) et plus largement l'Île-de-France,
pour des projets d'investissement patrimonial et marchand de biens.

Principe :
  1. Télécharger les données DVF (Demandes de Valeurs Foncières, DGFiP,
     open data officiel) pour le département choisi.
  2. Construire une référence de prix au m² par commune et par type de bien
     (maison, appartement, immeuble vendu en bloc), à partir des vraies
     transactions passées.
  3. Comparer une annonce ou un bien repéré à cette référence pour estimer
     s'il est sous-évalué, dans le marché, ou surévalué.

Source des données : https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/
Fichiers utilisés  : https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{dept}.csv.gz
Mise à jour source : ~2 fois par an (avril / octobre), données DGFiP.

Usage :
  python immo_scan.py download --dept 94 --years 2021 2022 2023 2024 2025
  python immo_scan.py reference --dept 94
  python immo_scan.py score --commune "Vincennes" --type Maison --surface 90 --prix 480000
  python immo_scan.py batch --input mes_annonces.csv --dept 94

Limites connues (prototype v0.1, à valider avant tout usage commercial) :
  - Les biens "immeuble entier" sont reconstitués à partir des ventes en bloc
    de plusieurs lots DVF (approximation, cf. reconstruct_buildings()).
  - Pas de prise en compte de l'état du bien / travaux dans le prix de
    référence : deux biens du même prix/m² peuvent être dans un état très
    différent (voir DPE / ADEME en complément, non intégré ici).
  - Les données DVF ont un décalage de quelques mois avec le marché actuel.
"""

import gzip
import io
import json
import sys
import unicodedata
from pathlib import Path

import pandas as pd

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"
DVF_URL_TEMPLATE = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/departements/{dept}.csv.gz"

# Communes du Val-de-Marne (94) à titre indicatif — utile pour filtrer/valider
VAL_DE_MARNE_HINT = (
    "Ivry-sur-Seine, Vitry-sur-Seine, Créteil, Saint-Maur-des-Fossés, "
    "Champigny-sur-Marne, Vincennes, Nogent-sur-Marne, Fontenay-sous-Bois, "
    "Charenton-le-Pont, Maisons-Alfort, Cachan, L'Haÿ-les-Roses, "
    "Villejuif, Le Kremlin-Bicêtre, Choisy-le-Roi, Thiais, Bonneuil-sur-Marne, ..."
)

TYPES_RETENUS = ["Maison", "Appartement"]  # types_local bruts DVF exploités


def _normalize_text(value) -> str:
    """Normalise une chaîne pour comparer des adresses DVF/BAN."""
    txt = "" if value is None or pd.isna(value) else str(value)
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return " ".join(txt.lower().replace("'", " ").replace("-", " ").split())



# ----------------------------------------------------------------------------
# 1. Téléchargement des données DVF
# ----------------------------------------------------------------------------

def download_year(dept: str, year: int, force: bool = False) -> Path:
    """Télécharge le fichier DVF d'un département pour une année donnée."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / f"{dept}_{year}.csv.gz"
    if dest.exists() and not force:
        print(f"[skip] {dest.name} déjà présent")
        return dest

    url = DVF_URL_TEMPLATE.format(year=year, dept=dept)
    print(f"[download] {url}")
    try:
        import requests
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        print(f"[ok] {dest.name} ({len(resp.content) / 1e6:.1f} Mo)")
    except Exception as exc:
        print(f"[erreur] Impossible de télécharger {url} : {exc}", file=sys.stderr)
        raise
    return dest


def download(dept: str, years: list[int], force: bool = False) -> None:
    for year in years:
        try:
            download_year(dept, year, force=force)
        except Exception:
            print(f"[warn] Année {year} ignorée (fichier absent ou erreur réseau)")


# ----------------------------------------------------------------------------
# 2. Chargement et nettoyage
# ----------------------------------------------------------------------------

COLS_UTILES = [
    "date_mutation", "nature_mutation", "valeur_fonciere",
    "adresse_numero", "adresse_nom_voie", "code_postal",
    "nom_commune", "code_commune", "id_mutation", "id_parcelle",
    "type_local", "surface_reelle_bati", "nombre_pieces_principales",
    "surface_terrain", "longitude", "latitude",
]

# API publiques utilisées pour l'enrichissement par adresse
ADEME_DPE_API_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
IGN_CADASTRE_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"
IGN_GPU_ZONE_URBA_URL = "https://apicarto.ign.fr/api/gpu/zone-urba"
GEORISQUES_API_URL = "https://georisques.gouv.fr/api/v1/resultats_rapport_risque"


def load_all(dept: str, years: list[int]) -> pd.DataFrame:
    """Charge et concatène les fichiers DVF disponibles localement pour ce dept."""
    frames = []
    for year in years:
        path = DATA_DIR / f"{dept}_{year}.csv.gz"
        if not path.exists():
            print(f"[warn] {path.name} absent — lancez d'abord la commande 'download'")
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            df = pd.read_csv(f, usecols=lambda c: c in COLS_UTILES, low_memory=False)
        df["annee"] = year
        frames.append(df)
    if not frames:
        raise SystemExit("Aucune donnée chargée. Lancez 'download' d'abord.")
    return pd.concat(frames, ignore_index=True)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoie et calcule le prix au m² pour les ventes exploitables."""
    df = df[df["nature_mutation"] == "Vente"].copy()
    df = df[df["type_local"].isin(TYPES_RETENUS)]
    df = df[(df["valeur_fonciere"] > 10_000) & (df["surface_reelle_bati"] > 8)]

    # Une même mutation peut apparaître sur plusieurs lignes (dépendances,
    # plusieurs lots). On agrège au niveau de la mutation pour ne pas
    # sur-pondérer les biens à lots multiples dans le calcul du prix/m².
    agg = (
        df.groupby(["id_mutation", "date_mutation", "nom_commune", "code_postal",
                     "code_commune", "type_local", "annee", "valeur_fonciere"],
                    as_index=False)
          .agg(surface_reelle_bati=("surface_reelle_bati", "sum"),
               nb_lots=("id_parcelle", "nunique"),
               id_parcelle=("id_parcelle", "first"),
               adresse_nom_voie=("adresse_nom_voie", "first"),
               adresse_numero=("adresse_numero", "first"),
               longitude=("longitude", "first"),
               latitude=("latitude", "first"))
    )
    agg = agg[agg["surface_reelle_bati"] > 8]
    agg["prix_m2"] = agg["valeur_fonciere"] / agg["surface_reelle_bati"]
    # On retire les valeurs aberrantes (erreurs de saisie DVF fréquentes)
    agg = agg[(agg["prix_m2"] > 500) & (agg["prix_m2"] < 25_000)]
    return agg


def reconstruct_buildings(agg: pd.DataFrame) -> pd.DataFrame:
    """
    Isole les mutations correspondant probablement à une vente d'immeuble
    en bloc : plusieurs lots "Appartement" vendus sous le même id_mutation,
    au même prix total. Approximation à affiner avec le champ 'nombre_lots'
    du fichier source si besoin d'une précision supérieure.
    """
    immeubles = agg[(agg["type_local"] == "Appartement") & (agg["nb_lots"] >= 2)].copy()
    immeubles["type_local"] = "Immeuble (vente en bloc, estimé)"
    return immeubles


# ----------------------------------------------------------------------------
# 3. Référence de prix / m² par commune et type de bien
# ----------------------------------------------------------------------------

def build_reference(agg: pd.DataFrame) -> pd.DataFrame:
    ref = (
        agg.groupby(["nom_commune", "type_local"])["prix_m2"]
           .agg(prix_m2_median="median", prix_m2_moyen="mean",
                nb_transactions="count", ecart_type="std")
           .reset_index()
           .sort_values(["nom_commune", "type_local"])
    )
    return ref


def build_trend(agg: pd.DataFrame) -> pd.DataFrame:
    """Évolution annuelle du prix médian/m² par commune et type — utile
    pour repérer les zones en appréciation rapide (fort potentiel)."""
    trend = (
        agg.groupby(["nom_commune", "type_local", "annee"])["prix_m2"]
           .median()
           .reset_index()
           .pivot_table(index=["nom_commune", "type_local"], columns="annee",
                        values="prix_m2")
    )
    years = sorted(trend.columns)
    if len(years) >= 2:
        trend["evolution_pct"] = (
            (trend[years[-1]] - trend[years[0]]) / trend[years[0]] * 100
        ).round(1)
    return trend.reset_index()


def meta_path(dept: str) -> Path:
    return OUTPUT_DIR / f"meta_{dept}.json"


def load_meta(dept: str) -> dict | None:
    p = meta_path(dept)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save_meta(dept: str, years: list[int]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    meta_path(dept).write_text(json.dumps({"years": sorted(years)}))


REFERENCE_BUNDLED_DIR = Path(__file__).parent / "reference_data"


def _seed_from_bundled_reference(dept: str) -> bool:
    """
    Si une référence pré-construite existe dans `reference_data/` pour ce
    département (committée une fois pour toutes sur GitHub, comme pour
    Cerema DVF+), la copie dans le cache de travail éphémère (`output/`)
    pour éviter un téléchargement + reconstruction complète à chaque
    redémarrage à froid de l'app (cause principale des lenteurs/échecs
    occasionnels au démarrage — le cache de travail ne survit pas aux mises
    en veille de Streamlit Cloud). Retourne True si un fichier a été trouvé
    et copié.
    """
    import shutil

    ref_src = REFERENCE_BUNDLED_DIR / f"reference_{dept}.csv"
    if not ref_src.exists():
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in (f"reference_{dept}.csv", f"tendance_{dept}.csv",
                 f"transactions_nettoyees_{dept}.csv", f"meta_{dept}.json"):
        src = REFERENCE_BUNDLED_DIR / name
        if src.exists():
            shutil.copy(src, OUTPUT_DIR / name)
    return True


def reference_is_up_to_date(dept: str, years: list[int]) -> bool:
    """Vrai si une référence existe déjà pour ce département ET couvre bien
    exactement les années actuellement sélectionnées. Tente d'abord un
    amorçage depuis un fichier intégré au dépôt (voir
    `_seed_from_bundled_reference`) si le cache de travail est vide."""
    if not (OUTPUT_DIR / f"reference_{dept}.csv").exists():
        _seed_from_bundled_reference(dept)
    if not (OUTPUT_DIR / f"reference_{dept}.csv").exists():
        return False
    meta = load_meta(dept)
    if meta is None:
        return False
    return sorted(meta.get("years", [])) == sorted(years)


def prepare_data_if_needed(dept: str, years: list[int], force: bool = False,
                            progress_callback=None) -> bool:
    """
    Télécharge les données DVF et construit la référence de prix pour ce
    département si nécessaire (absente, ou années différentes de la dernière
    construction), sans intervention manuelle. Retourne True si une
    (re)construction a eu lieu, False si les données étaient déjà à jour.
    `progress_callback(message)` est appelé à chaque étape pour affichage
    (ex. dans un st.status côté app), et est optionnel.
    """
    def notify(msg):
        if progress_callback:
            progress_callback(msg)

    if not force and reference_is_up_to_date(dept, years):
        return False

    notify(f"Téléchargement des données DVF ({dept}, {', '.join(map(str, years))})...")
    download(dept, years, force=force)

    notify("Construction de la référence de prix/m²...")
    run_reference(dept, years)
    save_meta(dept, years)
    return True


def run_reference(dept: str, years: list[int]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_all(dept, years)
    agg = clean(df)
    immeubles = reconstruct_buildings(agg)
    full = pd.concat([agg, immeubles], ignore_index=True)

    ref = build_reference(full)
    trend = build_trend(full)

    ref_path = OUTPUT_DIR / f"reference_{dept}.csv"
    trend_path = OUTPUT_DIR / f"tendance_{dept}.csv"
    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"

    ref.to_csv(ref_path, index=False)
    trend.to_csv(trend_path, index=False)
    full.to_csv(cache_path, index=False)

    print(f"[ok] Référence prix/m² : {ref_path}  ({len(ref)} lignes commune x type)")
    print(f"[ok] Tendances annuelles : {trend_path}")
    print(f"[ok] Transactions nettoyées (cache) : {cache_path}")
    print("\nTop 10 communes les plus chères (Maison, médiane €/m²) :")
    print(
        ref[ref["type_local"] == "Maison"]
        .sort_values("prix_m2_median", ascending=False)
        .head(10)
        .to_string(index=False)
    )


# ----------------------------------------------------------------------------
# 3bis. Enrichissement par adresse : DPE, comparables à proximité
# ----------------------------------------------------------------------------
# NB : le géocodage (adresse -> coordonnées) se fait désormais entièrement
# côté navigateur, dans le composant st_address_search/index.html (appel
# direct à l'API Adresse du gouvernement en JavaScript). Les anciennes
# fonctions Python géocode_suggestions()/geocode_address() ont été retirées
# car devenues inutiles — elles n'étaient plus appelées nulle part.

def haversine_m(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS (formule de Haversine)."""
    from math import radians, sin, cos, sqrt, atan2
    r = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def lambert93_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """
    Convertit des coordonnées Lambert-93 (EPSG:2154, utilisé par les données
    cadastrales et Cerema DVF+) en latitude/longitude WGS84.

    Implémentation en pur Python (formule officielle IGN de projection
    conique conforme de Lambert, inversée), sans dépendance externe (évite
    pyproj, plus lourd et pas nécessaire pour notre précision requise).
    Validée à ~10m près sur un point de référence connu (rue de la Paix,
    Paris) — largement suffisant pour nos calculs de distance/comparables.
    """
    import math

    n = 0.7256077650
    C = 11754255.426
    Xs = 700000.0
    Ys = 12655612.050
    e = 0.08181919112823
    lon0 = math.radians(3.0)

    dX = x - Xs
    dY = y - Ys
    R = math.sqrt(dX ** 2 + dY ** 2)
    gamma = math.atan2(dX, -dY)
    lon = lon0 + gamma / n

    latiso = -1.0 / n * math.log(abs(R / C))
    lat = 2 * math.atan(math.exp(latiso)) - math.pi / 2
    for _ in range(15):
        lat = 2 * math.atan(
            ((1 + e * math.sin(lat)) / (1 - e * math.sin(lat))) ** (e / 2)
            * math.exp(latiso)
        ) - math.pi / 2

    return math.degrees(lat), math.degrees(lon)


# ----------------------------------------------------------------------------
# 3quater. Cerema DVF+ (historique complémentaire 2014-2020)
# ----------------------------------------------------------------------------
# Source : Cerema, "DVF+ open-data" (https://datafoncier.cerema.fr/donnees/
# autres-donnees-foncieres/dvfplus-open-data), Licence Ouverte v2.0 (Etalab).
# Complète la source principale (geo-dvf, 2021+) pour la période antérieure.
# Import manuel car ce jeu de données est distribué via des archives ZIP
# (pas d'URL directe automatisable par département comme pour geo-dvf).

CEREMA_ANNEE_MAX = 2020  # au-delà, on utilise la source principale geo-dvf

def _clean_cerema_dataframe(df: pd.DataFrame, annee_max: int) -> pd.DataFrame:
    """
    Nettoie un DataFrame Cerema DVF+ brut (un département) : filtre les
    ventes mono-type (uniquement maisons, ou uniquement appartements),
    calcule le prix/m², convertit les coordonnées Lambert-93 en WGS84.
    Fonction interne réutilisée pour un import département par département
    ou région par région (plusieurs départements dans la même archive).
    """
    df = df[(df["libnatmut"] == "Vente") & (df["anneemut"] <= annee_max)].copy()

    maison_pure = (df["nblocmai"] > 0) & (df["nblocapt"] == 0) & (df["nblocact"] == 0)
    appt_pure = (df["nblocapt"] > 0) & (df["nblocmai"] == 0) & (df["nblocact"] == 0)

    d_maison = df[maison_pure].copy()
    d_maison["type_local"] = "Maison"
    d_maison["surface_reelle_bati"] = d_maison["sbatmai"]

    d_appt = df[appt_pure].copy()
    d_appt["type_local"] = "Appartement"
    d_appt["surface_reelle_bati"] = d_appt["sbatapt"]

    combined = pd.concat([d_maison, d_appt], ignore_index=True)
    if combined.empty:
        return combined

    combined = combined.rename(columns={"datemut": "date_mutation", "anneemut": "annee",
                                          "valeurfonc": "valeur_fonciere"})
    combined = combined[(combined["valeur_fonciere"] > 10_000) & (combined["surface_reelle_bati"] > 8)]
    combined["prix_m2"] = combined["valeur_fonciere"] / combined["surface_reelle_bati"]
    combined = combined[(combined["prix_m2"] > 500) & (combined["prix_m2"] < 25_000)]

    combined["id_parcelle"] = combined["l_idpar"].astype(str).str.split(",").str[0]
    combined["nom_commune"] = None  # pas de nom de commune dans cette source (voir README)
    combined["code_commune"] = combined["l_codinsee"].astype(str).str.split(",").str[0]

    lat_lon = combined.apply(
        lambda r: lambert93_to_wgs84(r["geompar_x"], r["geompar_y"]), axis=1
    )
    combined["latitude"] = lat_lon.map(lambda t: t[0])
    combined["longitude"] = lat_lon.map(lambda t: t[1])
    combined["source"] = "Cerema DVF+"

    cols = ["date_mutation", "annee", "valeur_fonciere", "surface_reelle_bati",
            "type_local", "prix_m2", "id_parcelle", "code_commune", "nom_commune",
            "latitude", "longitude", "source"]
    return combined[cols].reset_index(drop=True)


def list_departements_in_zip(zip_path: str) -> list[str]:
    """
    Liste les départements présents dans une archive Cerema DVF+ (régionale
    ou départementale), en repérant les fichiers `dvf_plus_d{dept}.csv`
    qu'elle contient.
    """
    import zipfile, re

    with zipfile.ZipFile(zip_path) as zf:
        depts = []
        for name in zf.namelist():
            m = re.search(r"dvf_plus_d(\d{2,3})\.csv$", name)
            if m:
                depts.append(m.group(1))
    return sorted(depts)


def load_cerema_dvfplus(zip_path: str, dept: str, annee_max: int = CEREMA_ANNEE_MAX) -> pd.DataFrame:
    """
    Importe et nettoie les données Cerema DVF+ pour UN département, à partir
    d'une archive ZIP (départementale ou régionale) téléchargée manuellement
    sur https://cerema.app.box.com/v/dvfplus-opendata (voir README).

    Contrairement à geo-dvf, cette source n'a pas de champ adresse (numéro +
    rue) — seulement des identifiants de parcelle (l_idpar) et des
    coordonnées Lambert-93. Elle est donc utilisée pour enrichir les
    comparables et, quand un identifiant de parcelle est déjà connu (via une
    correspondance DVF exacte récente ou le cadastre), l'historique d'un
    bien précis — pas pour une recherche par adresse textuelle directe.

    Ne garde que les mutations "mono-type" (uniquement des maisons, ou
    uniquement des appartements) pour rester cohérent avec la méthodologie
    de la source principale ; les mutations mixtes sont écartées.
    """
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        candidates = [n for n in zf.namelist() if n.endswith(f"dvf_plus_d{dept}.csv")]
        if not candidates:
            raise SystemExit(
                f"Fichier dvf_plus_d{dept}.csv introuvable dans l'archive. "
                "Vérifiez que le département est bien couvert par le fichier "
                "régional téléchargé."
            )
        with zf.open(candidates[0]) as f:
            df = pd.read_csv(f, sep="|", low_memory=False)

    return _clean_cerema_dataframe(df, annee_max)


def load_cerema_dvfplus_region(zip_path: str, depts: list[str] | None = None,
                                annee_max: int = CEREMA_ANNEE_MAX,
                                progress_callback=None) -> dict[str, pd.DataFrame]:
    """
    Importe et nettoie les données Cerema DVF+ pour TOUS les départements
    d'une archive régionale en une seule fois (Cerema distribue ses fichiers
    par région, chacune contenant un CSV par département — ex. la région
    Île-de-France contient dvf_plus_d75.csv, d77.csv, ..., d95.csv).

    Si `depts` n'est pas fourni, traite tous les départements détectés dans
    l'archive (voir `list_departements_in_zip`). `progress_callback(message)`
    est appelé à chaque département traité, pour affichage côté app.

    Retourne un dict {département: DataFrame nettoyé}.
    """
    import zipfile

    if depts is None:
        depts = list_departements_in_zip(zip_path)
    if not depts:
        raise SystemExit(
            "Aucun fichier dvf_plus_d{dept}.csv trouvé dans cette archive. "
            "Vérifiez qu'il s'agit bien d'une archive Cerema DVF+ open-data."
        )

    resultats = {}
    with zipfile.ZipFile(zip_path) as zf:
        for dept in depts:
            candidates = [n for n in zf.namelist() if n.endswith(f"dvf_plus_d{dept}.csv")]
            if not candidates:
                if progress_callback:
                    progress_callback(f"⚠️ {dept} : fichier introuvable dans l'archive, ignoré.")
                continue
            if progress_callback:
                progress_callback(f"Traitement du département {dept}...")
            with zf.open(candidates[0]) as f:
                df_brut = pd.read_csv(f, sep="|", low_memory=False)
            resultats[dept] = _clean_cerema_dataframe(df_brut, annee_max)

    return resultats


def import_cerema_dvfplus(zip_path: str, dept: str) -> str:
    """
    Importe les données Cerema DVF+ pour un département et les met en cache
    localement (évite de re-parser l'archive ZIP, volumineuse, à chaque
    utilisation). Retourne un message de résumé.
    """
    df = load_cerema_dvfplus(zip_path, dept)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OUTPUT_DIR / f"cerema_dvfplus_{dept}.csv"
    df.to_csv(cache_path, index=False)
    annees = f"{df['annee'].min()}-{df['annee'].max()}" if not df.empty else "aucune"
    return (
        f"{len(df)} transactions Cerema DVF+ importées pour le {dept} "
        f"(années {annees}). Source : Cerema, DVF+ open-data, Licence "
        "Ouverte v2.0 (Etalab)."
    )


def import_cerema_dvfplus_region_combined(zip_path: str, region_name: str,
                                           depts: list[str] | None = None,
                                           progress_callback=None,
                                           taille_max_mo: float = 20.0) -> str:
    """
    Importe les données Cerema DVF+ pour tous les départements d'une archive
    régionale et les combine en UN SEUL fichier compressé (gzip), plutôt
    qu'un fichier par département — recommandé pour limiter le nombre de
    fichiers à gérer sur GitHub. La compression gzip réduit la taille
    d'environ 3-4x (ex. ~122 Mo → ~36 Mo pour l'Île-de-France), sans
    dépendance supplémentaire (gzip est natif à pandas/Python).

    Si le fichier compressé dépasse `taille_max_mo` (par défaut 20 Mo, avec
    marge sous la limite de 25 Mo de l'upload web GitHub — l'envoi en ligne
    de commande accepte jusqu'à 100 Mo, mais l'interface web mobile utilisée
    ici est plus restrictive), il est automatiquement découpé en plusieurs
    morceaux (`.part001`, `.part002`, ...) que l'app recolle elle-même au
    chargement — à déposer tous ensemble dans `cerema_data/`.

    `region_name` sert à nommer le(s) fichier(s) de sortie
    (`cerema_dvfplus_region_{region_name}.csv.gz[.partNNN]`) — utilisez un
    nom court et stable (ex. "idf" pour Île-de-France).
    """
    resultats = load_cerema_dvfplus_region(zip_path, depts, progress_callback=progress_callback)
    if not resultats:
        raise SystemExit("Aucun département n'a pu être importé depuis cette archive.")

    if progress_callback:
        progress_callback("Combinaison de tous les départements en un seul fichier...")
    combined = pd.concat(resultats.values(), ignore_index=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OUTPUT_DIR / f"cerema_dvfplus_region_{region_name}.csv.gz"

    if progress_callback:
        progress_callback("Compression du fichier régional (gzip)...")
    combined.to_csv(cache_path, index=False, compression="gzip")

    taille_mo = cache_path.stat().st_size / 1_000_000
    lignes_resume = [
        f"  • {dept} : {len(df)} transactions ({df['annee'].min()}-{df['annee'].max()})"
        if not df.empty else f"  • {dept} : aucune transaction"
        for dept, df in resultats.items()
    ]
    resume_base = (
        f"{len(combined)} transactions Cerema DVF+ importées et combinées "
        f"pour {len(resultats)} département(s) ({taille_mo:.0f} Mo) :\n"
        + "\n".join(lignes_resume) +
        "\n\nSource : Cerema, DVF+ open-data, Licence Ouverte v2.0 (Etalab)."
    )

    if taille_mo <= taille_max_mo:
        return (
            resume_base +
            f"\n\nFichier généré : output/cerema_dvfplus_region_{region_name}.csv.gz "
            "— à déposer dans cerema_data/ pour le rendre permanent."
        )

    # Découpage en morceaux sous taille_max_mo, pour passer sous la limite
    # d'upload web de GitHub (25 Mo).
    if progress_callback:
        progress_callback(
            f"Fichier de {taille_mo:.0f} Mo > {taille_max_mo:.0f} Mo : "
            "découpage en morceaux..."
        )
    chunk_size = int(taille_max_mo * 1_000_000)
    parts = []
    with open(cache_path, "rb") as f:
        idx = 1
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            part_path = OUTPUT_DIR / f"cerema_dvfplus_region_{region_name}.csv.gz.part{idx:03d}"
            part_path.write_bytes(chunk)
            parts.append(part_path.name)
            idx += 1
    cache_path.unlink()  # on retire le fichier non découpé, remplacé par les morceaux

    if progress_callback:
        progress_callback(f"✅ Découpé en {len(parts)} morceaux : {', '.join(parts)}")

    return (
        resume_base +
        f"\n\n⚠️ Fichier découpé en {len(parts)} morceaux car il dépasse "
        f"{taille_max_mo:.0f} Mo (limite d'upload web GitHub ≈ 25 Mo) :\n" +
        "\n".join(f"  • output/{p}" for p in parts) +
        "\n\nDéposez TOUS ces morceaux ensemble dans cerema_data/ — l'app "
        "les recolle elle-même automatiquement au chargement."
    )



CEREMA_BUNDLED_DIR = Path(__file__).parent / "cerema_data"

_regional_cache_memoire: dict[str, pd.DataFrame] = {}


def _load_regional_file_cached(path: Path) -> pd.DataFrame:
    """Charge un fichier régional Cerema compressé, avec un cache mémoire
    (process Python) pour éviter de le redécompresser à chaque appel —
    la décompression d'un fichier de plusieurs dizaines de Mo prend une
    à deux secondes, non négligeable si répété à chaque interaction."""
    key = str(path)
    if key not in _regional_cache_memoire:
        _regional_cache_memoire[key] = pd.read_csv(path)
    return _regional_cache_memoire[key]


def _completer_noms_commune(df: pd.DataFrame, dept: str) -> pd.DataFrame:
    """
    Complète les noms de commune manquants (source Cerema, qui ne fournit
    qu'un code INSEE, jamais de nom — voir README) à partir de la
    correspondance code_commune -> nom_commune déjà connue dans le cache
    des transactions DVF récentes (2021+) de ce département. Ne couvre pas
    100% des cas (une commune peut n'avoir eu aucune vente DVF récente),
    mais comble la grande majorité des trous en pratique.
    """
    if "nom_commune" not in df.columns or df["nom_commune"].notna().all():
        return df

    dvf_cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not dvf_cache_path.exists():
        return df

    dvf = pd.read_csv(dvf_cache_path, usecols=["code_commune", "nom_commune"])
    mapping = (
        dvf.dropna(subset=["code_commune", "nom_commune"])
           .drop_duplicates("code_commune")
           .set_index("code_commune")["nom_commune"]
    )

    df = df.copy()
    df["nom_commune"] = df["nom_commune"].astype(object)
    manquants = df["nom_commune"].isna()
    df.loc[manquants, "nom_commune"] = (
        df.loc[manquants, "code_commune"].astype(str).map(
            {str(k): v for k, v in mapping.items()}
        )
    )
    return df


def load_cerema_cache(dept: str) -> pd.DataFrame | None:
    """
    Charge les données Cerema DVF+ pour un département. Cherche, dans cet
    ordre :
    1. Un fichier régional intégré au dépôt (`cerema_data/cerema_dvfplus_region_*.csv.gz`,
       compressé, couvrant plusieurs départements — recommandé pour limiter
       le nombre de fichiers) — filtré au département demandé. Si ce
       fichier a été découpé en morceaux (`.part001`, `.part002`, ... — cas
       des fichiers dépassant la limite d'upload web GitHub de 25 Mo), les
       morceaux sont recollés automatiquement avant lecture.
    2. Un fichier par département intégré au dépôt
       (`cerema_data/cerema_dvfplus_{dept}.csv`, non compressé).
    3. À défaut, le cache généré par un import manuel via l'upload dans
       l'app (perdu à chaque redéploiement, stocké dans `output/`).

    Les fichiers intégrés au dépôt (1 et 2) survivent aux redéploiements et
    reboots ; le cache d'upload (3) est éphémère.

    Dans tous les cas, les noms de commune manquants (Cerema ne fournit
    qu'un code INSEE) sont complétés autant que possible à partir des
    données DVF récentes du même département (voir `_completer_noms_commune`).
    """
    for regional_path in sorted(CEREMA_BUNDLED_DIR.glob("cerema_dvfplus_region_*.csv.gz")):
        df_region = _load_regional_file_cached(regional_path)
        df_dept = df_region[df_region["code_commune"].astype(str).str.startswith(dept)]
        if not df_dept.empty:
            return _completer_noms_commune(df_dept.reset_index(drop=True), dept)

    # Fichiers régionaux découpés en morceaux (.part001, .part002, ...) :
    # regroupés par nom de base, recollés avant lecture.
    part_files = sorted(CEREMA_BUNDLED_DIR.glob("cerema_dvfplus_region_*.csv.gz.part*"))
    bases = sorted(set(p.name.split(".part")[0] for p in part_files))
    for base in bases:
        cache_key = f"reassembled::{base}"
        if cache_key not in _regional_cache_memoire:
            mes_parts = sorted(
                (p for p in part_files if p.name.startswith(base + ".part")),
                key=lambda p: p.name,
            )
            data = b"".join(p.read_bytes() for p in mes_parts)
            import io
            _regional_cache_memoire[cache_key] = pd.read_csv(
                io.BytesIO(data), compression="gzip"
            )
        df_region = _regional_cache_memoire[cache_key]
        df_dept = df_region[df_region["code_commune"].astype(str).str.startswith(dept)]
        if not df_dept.empty:
            return _completer_noms_commune(df_dept.reset_index(drop=True), dept)

    bundled_path = CEREMA_BUNDLED_DIR / f"cerema_dvfplus_{dept}.csv"
    if bundled_path.exists():
        return _completer_noms_commune(pd.read_csv(bundled_path), dept)

    cache_path = OUTPUT_DIR / f"cerema_dvfplus_{dept}.csv"
    if cache_path.exists():
        return _completer_noms_commune(pd.read_csv(cache_path), dept)

    return None


def find_comparables(dept: str, lat: float, lon: float, type_local: str | None = None,
                      radius_m: float = 500, max_results: int = 15,
                      since_years: int = 5, include_cerema: bool = True) -> pd.DataFrame:
    """
    Cherche, dans le cache des transactions nettoyées, les ventes réelles les
    plus proches d'un point GPS donné, limitées aux `since_years` dernières
    années (par défaut 5) — utile pour situer un bien recherché par adresse
    par rapport à de vraies ventes comparables récentes et proches.
    Nécessite d'avoir lancé 'reference' au préalable pour ce département.

    Si `include_cerema` est vrai et qu'un cache Cerema DVF+ existe pour ce
    département (2014-2020, importé manuellement — voir README), ses ventes
    sont ajoutées en complément historique pour la même zone/période/type,
    avec une colonne 'source' pour les distinguer.
    """
    from datetime import datetime

    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not cache_path.exists():
        raise SystemExit(f"Cache introuvable ({cache_path}). Lancez 'reference' d'abord.")

    df = pd.read_csv(cache_path)
    df = df.dropna(subset=["latitude", "longitude"])
    df["source"] = "DVF (2021+)"
    if type_local:
        df = df[df["type_local"] == type_local]

    if since_years and "date_mutation" in df.columns:
        seuil = pd.Timestamp(datetime.now()) - pd.DateOffset(years=since_years)
        dates = pd.to_datetime(df["date_mutation"], errors="coerce")
        df = df[dates >= seuil]

    frames = [df] if not df.empty else []

    if include_cerema:
        cerema = load_cerema_cache(dept)
        if cerema is not None and not cerema.empty:
            cerema = cerema.dropna(subset=["latitude", "longitude"]).copy()
            if type_local:
                cerema = cerema[cerema["type_local"] == type_local]
            if since_years:
                seuil = pd.Timestamp(datetime.now()) - pd.DateOffset(years=since_years)
                dates_c = pd.to_datetime(cerema["date_mutation"], errors="coerce")
                cerema = cerema[dates_c >= seuil]
            if not cerema.empty:
                frames.append(cerema)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined["distance_m"] = combined.apply(
        lambda r: haversine_m(lat, lon, r["latitude"], r["longitude"]), axis=1
    )
    proches = combined[combined["distance_m"] <= radius_m].sort_values("distance_m")
    cols = ["nom_commune", "type_local", "date_mutation", "valeur_fonciere",
            "surface_reelle_bati", "prix_m2", "distance_m", "source"]
    # adresse_numero/adresse_nom_voie n'existent pas côté Cerema (source sans
    # champ adresse, seulement des identifiants de parcelle — voir README) :
    # on remplace le vide par un texte explicite plutôt qu'un "None" qui
    # ressemble à une erreur.
    if "adresse_numero" in proches.columns:
        proches = proches.copy()
        proches["adresse_numero"] = proches["adresse_numero"].astype(object)
        proches.loc[proches["source"] == "Cerema DVF+", "adresse_numero"] = "n/d"
        proches.loc[proches["source"] == "Cerema DVF+", "adresse_nom_voie"] = "(adresse non disponible pour cette source)"
        cols = ["adresse_numero", "adresse_nom_voie"] + cols
    return proches[cols].head(max_results)




def _parse_address_number_street(address: str) -> tuple[str, str]:
    """Extrait (numéro, nom de voie) d'une adresse en texte libre. Gère le
    format BAN standard sans virgule, ex. '38 avenue Sainte-Marie 94000
    Créteil' -> ('38', 'avenue sainte marie'), en coupant avant le code
    postal (5 chiffres) et tout ce qui suit."""
    import re
    txt = _normalize_text(address)
    m = re.match(r"^(\d+\s*(?:bis|ter|quater)?)\s+(.*)$", txt)
    if not m:
        return "", txt
    numero = re.sub(r"\s+", "", m.group(1))
    rest = m.group(2)
    # On coupe avant la première virgule éventuelle, ou avant un code postal
    # à 5 chiffres (format BAN standard sans virgule), le premier des deux.
    cut_positions = [len(rest)]
    virgule = rest.find(",")
    if virgule != -1:
        cut_positions.append(virgule)
    cp_match = re.search(r"\d{5}", rest)
    if cp_match:
        cut_positions.append(cp_match.start())
    rest = rest[:min(cut_positions)].strip()
    return numero, rest


def find_property_history(dept: str, address: str, lat: float, lon: float,
                          commune: str | None = None, max_results: int = 30) -> pd.DataFrame:
    """
    Récupère l'historique DVF du bien précis recherché (ce numéro, cette rue,
    cette commune), sur TOUTE la période chargée en cache (pas de limite de
    rayon ni d'années).

    La DVF publique ne fournit pas d'identifiant stable de logement : on
    identifie donc le bien par correspondance stricte numéro + rue + commune
    (normalisés pour tolérer les abréviations et accents). Le même nom de rue
    peut exister dans plusieurs communes du département — la commune est
    donc un critère obligatoire, pas seulement indicatif. En copropriété,
    plusieurs lots peuvent partager le même numéro — toutes les lignes
    correspondantes sont alors montrées, à vérifier manuellement.

    Si aucune correspondance exacte n'est trouvée, un repli de proximité très
    étroit (30 m) est tenté et clairement signalé comme approximatif.
    """
    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not cache_path.exists():
        raise SystemExit(f"Cache introuvable ({cache_path}). Lancez 'reference' d'abord.")

    df = pd.read_csv(cache_path)
    if df.empty:
        return pd.DataFrame()

    df["adresse_dvf"] = (
        df["adresse_numero"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
        + " " + df["adresse_nom_voie"].fillna("").astype(str)
        + ", " + df["nom_commune"].fillna("").astype(str)
    )
    df["numero_norm"] = (
        df["adresse_numero"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.lower()
    )
    df["rue_norm"] = df["adresse_nom_voie"].map(_normalize_text)
    df["commune_norm"] = df["nom_commune"].map(_normalize_text)

    # Mots de type de voie trop génériques pour servir de critère de
    # correspondance à eux seuls (sinon "avenue X" matche n'importe quelle
    # autre avenue partageant juste le mot "avenue").
    MOTS_GENERIQUES = {
        "rue", "avenue", "boulevard", "chemin", "impasse", "allee", "place",
        "square", "route", "sentier", "quai", "cours", "villa", "cite",
        "passage", "voie", "chaussee", "rond", "point", "cite", "residence",
        "hameau", "faubourg", "quartier", "lotissement",
    }

    target_numero, target_rue = _parse_address_number_street(address)
    rue_tokens = [
        t for t in target_rue.split() if len(t) > 2 and t not in MOTS_GENERIQUES
    ]
    target_commune_norm = _normalize_text(commune) if commune else None

    def rue_correspond(rue_dvf: str) -> bool:
        if not rue_tokens:
            return False
        # Tous les mots distinctifs de l'adresse recherchée doivent se
        # retrouver dans le nom de voie DVF (pas de tolérance : un seul mot
        # manquant peut désigner une rue complètement différente).
        return all(t in rue_dvf for t in rue_tokens)

    mask = (df["numero_norm"] == target_numero) & (df["rue_norm"].apply(rue_correspond))
    if target_commune_norm:
        # Une même rue peut exister dans plusieurs communes du département :
        # la commune est un critère obligatoire dès qu'on la connaît.
        mask &= df["commune_norm"] == target_commune_norm

    exact = df[mask].copy()
    exact["correspondance"] = "Exacte (numéro + rue + commune)"
    exact["source"] = "DVF (2021+)"

    result = exact
    if not result.empty and "id_parcelle" in result.columns:
        # Historique complémentaire : une fois la parcelle confirmée via une
        # correspondance DVF exacte, on cherche ses ventes plus anciennes
        # (2014-2020) dans le cache Cerema DVF+, si importé pour ce département.
        cerema = load_cerema_cache(dept)
        if cerema is not None and not cerema.empty:
            ids_connus = set(result["id_parcelle"].dropna().astype(str))
            hist_cerema = cerema[cerema["id_parcelle"].astype(str).isin(ids_connus)].copy()
            if not hist_cerema.empty:
                hist_cerema["correspondance"] = "Exacte (identifiant de parcelle confirmé, Cerema DVF+)"
                hist_cerema["nom_commune"] = result["nom_commune"].iloc[0]
                hist_cerema["adresse_dvf"] = result["adresse_dvf"].iloc[0]
                hist_cerema["nb_lots"] = 1
                result = pd.concat([result, hist_cerema], ignore_index=True)

    if result.empty and lat is not None and lon is not None:
        # Repli très étroit, clairement signalé comme approximatif.
        df2 = df.dropna(subset=["latitude", "longitude"]).copy()
        if not df2.empty:
            df2["distance_m"] = df2.apply(
                lambda r: haversine_m(lat, lon, r["latitude"], r["longitude"]), axis=1
            )
            proche = df2[df2["distance_m"] <= 30].copy()
            proche["correspondance"] = "Approximative (proximité < 30 m, adresse non confirmée)"
            proche["source"] = "DVF (2021+)"
            result = proche

    if result.empty:
        return pd.DataFrame()

    result = result.sort_values("date_mutation", ascending=False)
    cols = ["date_mutation", "adresse_dvf", "nom_commune", "type_local",
            "valeur_fonciere", "surface_reelle_bati", "prix_m2",
            "nb_lots", "correspondance", "source"]
    if "id_parcelle" in result.columns:
        cols.append("id_parcelle")
    return result[cols].head(max_results)


def google_maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


def google_earth_url(lat: float, lon: float) -> str:
    return f"https://earth.google.com/web/@{lat},{lon},120a,700d,35y,0h,0t,0r"


def google_street_view_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"

def find_dpe(address: str, code_postal: str | None = None, max_results: int = 5) -> pd.DataFrame | None:
    """
    Recherche les DPE (diagnostics de performance énergétique) disponibles
    pour une adresse via l'API ouverte de l'ADEME. Recherche approximative
    par texte libre — à vérifier manuellement en cas de doute (plusieurs
    logements peuvent partager la même adresse : copropriétés, immeubles).

    IMPORTANT : ce jeu de données ne couvre que les DPE établis à partir du
    1er juillet 2021 (réforme du DPE). Un bien dont le dernier diagnostic est
    antérieur à cette date n'y figurera pas — ce n'est pas un défaut de cette
    fonction, l'ADEME publie ces DPE plus anciens dans un jeu de données séparé.

    NB : le nom exact du jeu de données / des champs sur l'API data-fair de
    l'ADEME évolue de temps en temps. Si cette fonction ne retourne rien
    alors qu'un DPE existe, vérifiez le nom du dataset et des champs sur
    https://data.ademe.fr/datasets/dpe03existant (bouton API).
    """
    import requests
    query = address.strip()
    if code_postal and code_postal not in query:
        query = f"{query} {code_postal}"
    params = {"q": query, "size": max_results}
    try:
        resp = requests.get(ADEME_DPE_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        return pd.json_normalize(results)
    except Exception as exc:
        print(f"[warn] Recherche DPE échouée pour '{address}' : {exc}")
        return None


# ----------------------------------------------------------------------------
# 3ter. Module "Potentiel caché" : cadastre, PLU, Géorisques
# ----------------------------------------------------------------------------
# NB générale : ces trois fonctions appellent des API publiques gratuites et
# sans clé (IGN API Carto, Géorisques). Elles n'ont pas pu être testées en
# conditions réelles au moment de l'écriture (environnement de développement
# sans accès réseau) : la logique est bâtie sur la documentation officielle,
# mais à vérifier au premier usage réel — les schémas de réponse de ces API
# évoluent de temps en temps. Chaque fonction échoue silencieusement (retourne
# None) plutôt que de faire planter l'app en cas de changement de schéma.

def parse_id_parcelle(id_parcelle: str) -> dict | None:
    """
    Décompose un identifiant de parcelle DVF (14 caractères : 5 code INSEE +
    3 préfixe + 2 section + 4 numéro) en ses composants. Cet identifiant est
    systématiquement rempli dans les données DVF — quand une correspondance
    DVF exacte existe pour un bien, c'est la référence cadastrale la plus
    fiable possible, bien plus fiable qu'une déduction à partir de
    coordonnées GPS (qui peuvent tomber sur la voie plutôt que sur la
    parcelle bâtie réelle).
    """
    if not id_parcelle or len(str(id_parcelle)) != 14:
        return None
    s = str(id_parcelle)
    return {
        "code_insee": s[0:5],
        "prefixe": s[5:8],
        "section": s[8:10],
        "numero": s[10:14],
    }


def get_parcelle_by_identifiants(code_insee: str, section: str, numero: str) -> dict | None:
    """
    Récupère une parcelle cadastrale précise par ses identifiants exacts
    (code INSEE + section + numéro), via l'API Carto IGN — sans passer par
    une géométrie/coordonnée. Fiable à 100% quand ces identifiants sont
    connus (ex. via une correspondance DVF exacte), contrairement à une
    recherche par point GPS qui peut tomber sur la mauvaise parcelle.
    """
    import requests
    try:
        resp = requests.get(
            IGN_CADASTRE_URL,
            params={"code_insee": code_insee, "section": section, "numero": numero},
            timeout=10,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return None
        p = features[0]["properties"]
        return {
            "id_parcelle": p.get("id"),
            "code_insee": p.get("commune"),
            "prefixe": p.get("prefixe"),
            "section": p.get("section"),
            "numero": p.get("numero"),
            "contenance_m2": p.get("contenance"),
            "nb_parcelles": 1,
            "parcelles": [{
                "id_parcelle": p.get("id"), "code_insee": p.get("commune"),
                "prefixe": p.get("prefixe"), "section": p.get("section"),
                "numero": p.get("numero"), "contenance_m2": p.get("contenance"),
            }],
            "source": "identifiant DVF exact",
        }
    except Exception as exc:
        print(f"[warn] Cadastre par identifiant échoué pour {code_insee}/{section}/{numero} : {exc}")
        return None


def get_parcelle_cadastrale(lat: float, lon: float, buffer_m: float = 10) -> dict | None:
    """
    Récupère les parcelles cadastrales à proximité immédiate du point donné
    (API Carto IGN, module cadastre — gratuit, sans clé).

    IMPORTANT : on interroge toujours un petit périmètre (par défaut 10 m)
    plutôt qu'un point exact. Un point d'adresse (API BAN) est souvent placé
    sur la voie d'accès plutôt qu'à l'intérieur de la parcelle bâtie réelle —
    une requête ponctuelle peut alors renvoyer avec confiance la mauvaise
    parcelle (ex. celle de la rue elle-même) sans jamais déclencher de repli,
    puisqu'elle obtient bien UN résultat, juste le mauvais. On retourne donc
    toutes les parcelles touchées par ce petit périmètre, pour que l'app
    puisse les présenter comme candidates à vérifier plutôt que d'en choisir
    une seule silencieusement.
    """
    import requests, json, math

    def _query(geom_dict):
        resp = requests.get(IGN_CADASTRE_URL, params={"geom": json.dumps(geom_dict)}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("features", [])

    try:
        d_lat = buffer_m / 111_320
        d_lon = buffer_m / (111_320 * max(math.cos(math.radians(lat)), 0.1))
        square = [
            [lon - d_lon, lat - d_lat], [lon + d_lon, lat - d_lat],
            [lon + d_lon, lat + d_lat], [lon - d_lon, lat + d_lat], [lon - d_lon, lat - d_lat],
        ]
        features = _query({"type": "Polygon", "coordinates": [square]})
        if not features:
            return None

        # Dédoublonnage par numéro de parcelle (l'API peut renvoyer des
        # doublons géométriques pour une même parcelle sur un petit périmètre).
        vues = {}
        for f in features:
            p = f["properties"]
            key = (p.get("section"), p.get("numero"))
            if key not in vues:
                vues[key] = {
                    "id_parcelle": p.get("id"),
                    "code_insee": p.get("commune"),
                    "prefixe": p.get("prefixe"),
                    "section": p.get("section"),
                    "numero": p.get("numero"),
                    "contenance_m2": p.get("contenance"),
                }
        parcelles = list(vues.values())
        contenances = [p["contenance_m2"] for p in parcelles if p["contenance_m2"]]

        # Champs "principaux" = la première parcelle, pour compatibilité avec
        # le reste du code qui affiche un seul jeu de valeurs — mais la liste
        # complète est aussi exposée pour que l'app puisse toutes les montrer.
        principal = parcelles[0]
        return {
            **principal,
            "contenance_m2": sum(contenances) if contenances else None,
            "nb_parcelles": len(parcelles),
            "parcelles": parcelles,
        }
    except Exception as exc:
        print(f"[warn] Cadastre échoué pour ({lat}, {lon}) : {exc}")
        return None


def get_zone_plu(lat: float, lon: float) -> list[dict] | None:
    """
    Récupère la ou les zones du PLU (Plan Local d'Urbanisme) intersectant le
    point donné, via API Carto IGN (module GPU — Géoportail de l'Urbanisme),
    gratuit et sans clé. Retourne le libellé de zone (ex. 'UD', 'UC') qui
    conditionne les règles de constructibilité — utile pour évaluer un
    potentiel de division ou d'extension, mais ne remplace pas la lecture du
    règlement de zone complet ni un certificat d'urbanisme officiel.
    """
    import requests, json
    geom = json.dumps({"type": "Point", "coordinates": [lon, lat]})
    try:
        resp = requests.get(IGN_GPU_ZONE_URBA_URL, params={"geom": geom}, timeout=10)
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return None
        zones = []
        for f in features:
            props = f["properties"]
            zones.append({
                "libelle": props.get("libelle"),
                "type_zone": props.get("typezone"),
                "destination_dominante": props.get("destdomi"),
                "libelle_long": props.get("libellong"),
            })
        return zones
    except Exception as exc:
        print(f"[warn] PLU/GPU échoué pour ({lat}, {lon}) : {exc}")
        return None


def get_georisques(lat: float, lon: float) -> dict | None:
    """
    Récupère un résumé des risques naturels et technologiques au point donné
    (API Géorisques, gratuite). Retourne le JSON brut simplifié : à afficher
    tel quel dans l'app, le détail exact des risques varie selon la zone.
    NB : Géorisques a récemment introduit un système de jeton de connexion
    pour certains usages — si cette fonction échoue systématiquement, vérifiez
    sur https://www.georisques.gouv.fr/doc-api si un jeton est désormais
    nécessaire pour ce endpoint.
    """
    import requests
    try:
        resp = requests.get(
            GEORISQUES_API_URL, params={"latlon": f"{lon},{lat}"}, timeout=15
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[warn] Géorisques échoué pour ({lat}, {lon}) : {exc}")
        return None


def estimate_hidden_potential(parcelle: dict | None, zones_plu: list[dict] | None,
                               surface_bati_existante: float | None = None) -> dict:
    """
    Estimation heuristique et indicative du "potentiel caché" d'un foncier :
    compare la contenance de la parcelle à l'emprise bâtie connue pour donner
    un ordre de grandeur de réserve foncière théorique.

    ATTENTION : ceci est une estimation grossière, PAS une analyse de
    constructibilité réelle. Elle ne remplace en aucun cas la lecture du
    règlement de zone PLU complet (hauteur, emprise au sol max, reculs,
    coefficient de biotope, etc.) ni un certificat d'urbanisme officiel
    auprès de la mairie. À utiliser uniquement comme signal de première
    intention pour prioriser les biens à approfondir manuellement.
    """
    result = {
        "contenance_parcelle_m2": None,
        "surface_bati_connue_m2": surface_bati_existante,
        "emprise_au_sol_estimee_pct": None,
        "reserve_fonciere_theorique_m2": None,
        "zone_plu": None,
        "commentaire": "",
    }

    if parcelle and parcelle.get("contenance_m2"):
        contenance = parcelle["contenance_m2"]
        result["contenance_parcelle_m2"] = contenance
        if surface_bati_existante:
            emprise_pct = min(surface_bati_existante / contenance * 100, 100)
            result["emprise_au_sol_estimee_pct"] = round(emprise_pct, 1)
            result["reserve_fonciere_theorique_m2"] = round(
                max(contenance - surface_bati_existante, 0), 0
            )

    if zones_plu:
        libelles = ", ".join(z["libelle"] for z in zones_plu if z.get("libelle"))
        result["zone_plu"] = libelles or None

    if result["reserve_fonciere_theorique_m2"] and result["reserve_fonciere_theorique_m2"] > 200:
        result["commentaire"] = (
            "Emprise au sol faible par rapport à la parcelle : réserve foncière "
            "théoriquement significative, à vérifier avec le règlement de zone "
            "complet (hauteur autorisée, coefficient d'emprise au sol, reculs)."
        )
    elif result["contenance_parcelle_m2"]:
        result["commentaire"] = (
            "Parcelle déjà largement occupée par le bâti existant : potentiel "
            "d'extension au sol probablement limité, une surélévation reste à "
            "étudier selon le règlement de zone."
        )
    else:
        result["commentaire"] = "Données insuffisantes pour estimer un potentiel."

    return result


def find_nearby_transport(lat: float, lon: float, radius_m: int = 1500,
                           max_results: int = 5) -> list[dict] | None:
    """
    Cherche les gares, stations de métro/RER/tramway les plus proches d'un
    point, via l'API Overpass (OpenStreetMap) — gratuite, sans clé, couvre
    toute la France. Retourne une liste triée par distance croissante, ou
    None si la requête échoue.

    NB : OpenStreetMap est une base collaborative ; la couverture est très
    bonne en Île-de-France mais peut être incomplète ailleurs. À vérifier
    manuellement en cas de doute (absence suspecte d'une gare connue).
    """
    import requests

    query = f"""
    [out:json][timeout:12];
    (
      node["railway"="station"](around:{radius_m},{lat},{lon});
      node["railway"="halt"](around:{radius_m},{lat},{lon});
      node["public_transport"="station"](around:{radius_m},{lat},{lon});
    );
    out body;
    """
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter", data={"data": query}, timeout=15
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
        results = []
        seen_names = set()
        for el in elements:
            name = el.get("tags", {}).get("name")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            dist = haversine_m(lat, lon, el["lat"], el["lon"])
            results.append({
                "nom": name,
                "type": el.get("tags", {}).get("railway")
                        or el.get("tags", {}).get("public_transport") or "station",
                "distance_m": round(dist),
            })
        results.sort(key=lambda r: r["distance_m"])
        return results[:max_results]
    except Exception as exc:
        print(f"[warn] Recherche transports échouée pour ({lat}, {lon}) : {exc}")
        return None


def interpret_dpe_classe(dpe: pd.DataFrame | None) -> dict | None:
    """
    Extrait la classe énergie (et GES si disponible) du premier résultat DPE,
    avec une note qualitative — PAS un ajustement chiffré du prix (les
    données DVF ne permettent pas de calibrer un coefficient fiable, mieux
    vaut rester sur un signal qualitatif que d'inventer une précision qu'on
    n'a pas). Les noms de champs de l'API ADEME évoluent parfois — plusieurs
    candidats sont essayés.
    """
    if dpe is None or dpe.empty:
        return None

    candidats_energie = ["etiquette_dpe", "classe_consommation_energie", "etiquette_dpe_final"]
    candidats_ges = ["etiquette_ges", "classe_estimation_ges", "etiquette_ges_final"]

    classe_energie = None
    for col in candidats_energie:
        if col in dpe.columns:
            val = dpe.iloc[0].get(col)
            if pd.notna(val):
                classe_energie = str(val).upper().strip()
                break

    classe_ges = None
    for col in candidats_ges:
        if col in dpe.columns:
            val = dpe.iloc[0].get(col)
            if pd.notna(val):
                classe_ges = str(val).upper().strip()
                break

    if classe_energie is None:
        return None

    if classe_energie in ("A", "B", "C"):
        note = "Bon DPE — se négocie souvent avec une légère prime sur le marché."
    elif classe_energie == "D":
        note = "DPE moyen — généralement neutre sur le prix."
    else:
        note = (
            "DPE peu performant (passoire thermique si F/G) — se négocie "
            "souvent avec une décote, et des travaux de rénovation "
            "énergétique sont probablement à anticiper dans le budget."
        )

    return {"classe_energie": classe_energie, "classe_ges": classe_ges, "note": note}


BDNB_API_URL = "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet/bbox"


def get_batiment_bdnb(lat: float, lon: float, radius_m: float = 40) -> dict | None:
    """
    Récupère la carte d'identité du bâtiment le plus proche via l'API BDNB
    (Base de Données Nationale des Bâtiments, CSTB) — gratuite, sans clé,
    croise cadastre + BDTopo IGN + Fichiers fonciers. Utilisée ici
    principalement pour l'année de construction, absente des données DVF.

    NB : cette intégration n'a pas pu être testée en conditions réelles au
    moment de l'écriture (pas d'accès réseau dans l'environnement de
    développement) — la logique suit la documentation publique de l'API
    (protocole PostgREST), mais le nom exact des colonnes de la table
    "complète" (100+ champs) n'a pas pu être vérifié précisément. Plusieurs
    candidats sont essayés pour l'année de construction ; à ajuster si
    besoin après un premier test réel.
    """
    import requests, math

    d_lat = radius_m / 111_320
    d_lon = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.1))
    bbox = f"{lon - d_lon},{lat - d_lat},{lon + d_lon},{lat + d_lat}"

    try:
        resp = requests.get(BDNB_API_URL, params={"bbox": bbox}, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        premier = results[0]

        candidats_annee = [
            "annee_construction", "date_construction", "annee_construction_estimation",
            "millesime_annee_construction", "ffo_bat_annee_construction",
        ]
        annee = None
        for col in candidats_annee:
            if col in premier and premier[col]:
                annee = premier[col]
                break

        return {
            "annee_construction": annee,
            "identifiant_bdnb": premier.get("batiment_groupe_id"),
            "brut": premier,  # gardé pour inspection/diagnostic si besoin
        }
    except Exception as exc:
        print(f"[warn] BDNB échoué pour ({lat}, {lon}) : {exc}")
        return None


# ----------------------------------------------------------------------------
# 4. Score d'une annonce / d'un bien repéré
# ----------------------------------------------------------------------------

def score_property(commune: str, type_local: str, surface: float, prix: float,
                    dept: str = "94") -> dict:
    ref_path = OUTPUT_DIR / f"reference_{dept}.csv"
    if not ref_path.exists():
        raise SystemExit(
            f"Référence introuvable ({ref_path}). Lancez d'abord 'reference'."
        )
    ref = pd.read_csv(ref_path)
    row = ref[(ref["nom_commune"].str.lower() == commune.lower())
              & (ref["type_local"] == type_local)]

    if row.empty:
        return {
            "commune": commune, "type_local": type_local,
            "erreur": "Pas assez de transactions de référence pour ce couple "
                      "commune/type de bien. Essayez une commune voisine ou "
                      "vérifiez l'orthographe exacte (voir reference_94.csv)."
        }

    ref_m2 = float(row.iloc[0]["prix_m2_median"])
    nb_transac = int(row.iloc[0]["nb_transactions"])
    prix_m2_annonce = prix / surface
    ecart_pct = (prix_m2_annonce - ref_m2) / ref_m2 * 100

    if ecart_pct <= -15:
        label = "Potentiellement sous-évalué"
    elif ecart_pct <= -5:
        label = "Légèrement sous le marché"
    elif ecart_pct < 5:
        label = "Dans le marché"
    elif ecart_pct < 15:
        label = "Légèrement au-dessus du marché"
    else:
        label = "Potentiellement surévalué"

    return {
        "commune": commune,
        "type_local": type_local,
        "surface_m2": surface,
        "prix_annonce": prix,
        "prix_m2_annonce": round(prix_m2_annonce),
        "prix_m2_reference_commune": round(ref_m2),
        "ecart_pct": round(ecart_pct, 1),
        "nb_transactions_reference": nb_transac,
        "diagnostic": label,
    }
