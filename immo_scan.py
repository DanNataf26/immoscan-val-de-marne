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

import argparse
import gzip
import io
import json
import os
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


def department_from_geo(code_postal: str | None = None, code_insee: str | None = None) -> str | None:
    """Déduit le département français à partir du code postal ou INSEE."""
    code_insee = str(code_insee or "").strip()
    code_postal = str(code_postal or "").strip()
    if code_insee.startswith(("2A", "2B")):
        return code_insee[:2]
    if len(code_insee) >= 3 and code_insee[:3] in {"971", "972", "973", "974", "976"}:
        return code_insee[:3]
    if len(code_postal) >= 3 and code_postal[:3] in {"971", "972", "973", "974", "976"}:
        return code_postal[:3]
    if len(code_postal) >= 2:
        return code_postal[:2]
    if len(code_insee) >= 2:
        return code_insee[:2]
    return None


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
BAN_API_URL = "https://api-adresse.data.gouv.fr/search/"
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


def reference_is_up_to_date(dept: str, years: list[int]) -> bool:
    """Vrai si une référence existe déjà pour ce département ET couvre bien
    exactement les années actuellement sélectionnées."""
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
# 3bis. Enrichissement par adresse : géocodage, DPE, comparables à proximité
# ----------------------------------------------------------------------------

def geocode_suggestions(address: str, limit: int = 5) -> list[dict]:
    """
    Retourne jusqu'à `limit` suggestions d'adresses via l'API Adresse (BAN),
    pour une autocomplétion pendant la frappe. Renvoie une liste vide si
    l'adresse est trop courte ou si l'API échoue (jamais d'exception levée).
    """
    import requests
    if not address or len(address.strip()) < 3:
        return []
    try:
        resp = requests.get(BAN_API_URL, params={"q": address, "limit": limit}, timeout=8)
        resp.raise_for_status()
        suggestions = []
        for f in resp.json().get("features", []):
            props = f["properties"]
            lon, lat = f["geometry"]["coordinates"]
            suggestions.append({
                "label": props.get("label"),
                "commune": props.get("city"),
                "code_insee": props.get("citycode"),
                "code_postal": props.get("postcode"),
                "score": props.get("score"),
                "longitude": lon,
                "latitude": lat,
                "departement": department_from_geo(props.get("postcode"), props.get("citycode")),
            })
        return suggestions
    except Exception as exc:
        print(f"[warn] Suggestions échouées pour '{address}' : {exc}")
        return []


def geocode_address(address: str) -> dict | None:
    """
    Géocode une adresse via l'API Adresse du gouvernement (BAN), gratuite et
    sans clé. Retourne un dict avec label, commune, code_insee, code_postal,
    latitude, longitude — ou None si l'adresse n'est pas reconnue.
    """
    import requests
    try:
        resp = requests.get(BAN_API_URL, params={"q": address, "limit": 1}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            return None
        f = features[0]
        props = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        return {
            "label": props.get("label"),
            "commune": props.get("city"),
            "code_insee": props.get("citycode"),
            "code_postal": props.get("postcode"),
            "departement": department_from_geo(props.get("postcode"), props.get("citycode")),
            "score": props.get("score"),
            "longitude": lon,
            "latitude": lat,
        }
    except Exception as exc:
        print(f"[warn] Géocodage échoué pour '{address}' : {exc}")
        return None


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS (formule de Haversine)."""
    from math import radians, sin, cos, sqrt, atan2
    r = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def find_comparables(dept: str, lat: float, lon: float, type_local: str | None = None,
                      radius_m: float = 500, max_results: int = 15) -> pd.DataFrame:
    """
    Cherche, dans le cache des transactions nettoyées, les ventes réelles les
    plus proches d'un point GPS donné (utile pour situer un bien recherché
    par adresse par rapport à de vraies ventes comparables toutes proches).
    Nécessite d'avoir lancé 'reference' au préalable pour ce département.
    """
    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not cache_path.exists():
        raise SystemExit(f"Cache introuvable ({cache_path}). Lancez 'reference' d'abord.")

    df = pd.read_csv(cache_path)
    df = df.dropna(subset=["latitude", "longitude"])
    if type_local:
        df = df[df["type_local"] == type_local]

    df["distance_m"] = df.apply(
        lambda r: haversine_m(lat, lon, r["latitude"], r["longitude"]), axis=1
    )
    proches = df[df["distance_m"] <= radius_m].sort_values("distance_m")
    cols = ["adresse_numero", "adresse_nom_voie", "nom_commune", "type_local",
            "date_mutation", "valeur_fonciere", "surface_reelle_bati", "prix_m2",
            "distance_m"]
    return proches[cols].head(max_results)




def find_property_history(dept: str, address: str, lat: float, lon: float,
                          radius_m: float = 80, max_results: int = 30) -> pd.DataFrame:
    """
    Récupère l'historique DVF probable d'un bien/adresse.

    La DVF publique ne fournit pas toujours un identifiant stable de logement.
    On combine donc deux signaux :
      - ventes très proches géographiquement ;
      - adresse DVF ressemblant à l'adresse saisie.

    Le résultat doit être lu comme un historique probable à vérifier, surtout en
    copropriété ou lorsqu'une rue contient plusieurs numéros/lotissements.
    """
    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not cache_path.exists():
        raise SystemExit(f"Cache introuvable ({cache_path}). Lancez 'reference' d'abord.")

    df = pd.read_csv(cache_path)
    df = df.dropna(subset=["latitude", "longitude"]).copy()
    if df.empty:
        return pd.DataFrame()

    df["distance_m"] = df.apply(
        lambda r: haversine_m(lat, lon, r["latitude"], r["longitude"]), axis=1
    )

    target = _normalize_text(address)
    df["adresse_dvf"] = (
        df["adresse_numero"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
        + " " + df["adresse_nom_voie"].fillna("").astype(str)
        + ", " + df["nom_commune"].fillna("").astype(str)
    )
    df["adresse_norm"] = df["adresse_dvf"].map(_normalize_text)

    # On garde les ventes proches. L'adresse textuelle sert à remonter les plus
    # probables en haut, sans exclure les cas où DVF/BAN n'écrivent pas pareil.
    proches = df[df["distance_m"] <= radius_m].copy()
    if proches.empty:
        return pd.DataFrame()

    proches["adresse_similaire"] = proches["adresse_norm"].apply(
        lambda x: x in target or target in x or any(part and part in x for part in target.split()[:4])
    )
    proches = proches.sort_values(["adresse_similaire", "distance_m", "date_mutation"],
                                  ascending=[False, True, False])

    cols = ["date_mutation", "adresse_dvf", "nom_commune", "type_local",
            "valeur_fonciere", "surface_reelle_bati", "prix_m2",
            "nb_lots", "distance_m", "adresse_similaire"]
    out = proches[cols].head(max_results)
    return out


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

def get_parcelle_cadastrale(lat: float, lon: float) -> dict | None:
    """
    Récupère la parcelle cadastrale au point donné (API Carto IGN, module
    cadastre — gratuit, sans clé). Retourne notamment la contenance (surface
    officielle de la parcelle en m²), utile pour estimer un foncier sous-
    exploité par rapport à la surface bâtie existante.

    Essaie d'abord une géométrie ponctuelle (Point) ; si aucune parcelle
    n'intersecte exactement ce point (cas fréquent en bordure de parcelle,
    précision de géocodage), retente avec un petit polygone tampon (~5 m)
    autour du point.
    """
    import requests, json

    def _query(geom_dict):
        resp = requests.get(IGN_CADASTRE_URL, params={"geom": json.dumps(geom_dict)}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("features", [])

    try:
        features = _query({"type": "Point", "coordinates": [lon, lat]})
        if not features:
            # Repli : petit carré tampon (~5 m) autour du point, au cas où le
            # point tombe pile sur une frontière de parcelle ou légèrement à
            # côté (précision de géocodage).
            d = 0.00005  # environ 5 m en latitude/longitude
            square = [
                [lon - d, lat - d], [lon + d, lat - d],
                [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d],
            ]
            features = _query({"type": "Polygon", "coordinates": [square]})
        if not features:
            return None
        props = features[0]["properties"]
        return {
            "id_parcelle": props.get("id"),
            "code_insee": props.get("commune"),
            "prefixe": props.get("prefixe"),
            "section": props.get("section"),
            "numero": props.get("numero"),
            "contenance_m2": props.get("contenance"),
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


def run_score(args) -> None:
    result = score_property(args.commune, args.type, args.surface, args.prix,
                             dept=args.dept)
    for k, v in result.items():
        print(f"  {k:28s}: {v}")


# ----------------------------------------------------------------------------
# 5. Traitement en lot d'une liste d'annonces (CSV)
# ----------------------------------------------------------------------------

def run_batch(args) -> None:
    """
    Attend un CSV en entrée avec (a minima) les colonnes :
      adresse, commune, type_local, surface, prix
    (type_local doit valoir 'Maison' ou 'Appartement')
    Produit un CSV trié par écart croissant (les plus sous-évalués en tête).
    """
    listings = pd.read_csv(args.input)
    required = {"commune", "type_local", "surface", "prix"}
    missing = required - set(listings.columns)
    if missing:
        raise SystemExit(f"Colonnes manquantes dans {args.input} : {missing}")

    results = []
    for _, r in listings.iterrows():
        res = score_property(r["commune"], r["type_local"], r["surface"], r["prix"],
                              dept=args.dept)
        res["adresse"] = r.get("adresse", "")
        results.append(res)

    out = pd.DataFrame(results)
    if "ecart_pct" in out.columns:
        out = out.sort_values("ecart_pct")
    out_path = OUTPUT_DIR / "opportunites_scorees.csv"
    out.to_csv(out_path, index=False)
    print(f"[ok] Résultats triés (sous-évalués en premier) : {out_path}")
    print(out.head(15).to_string(index=False))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ImmoScan Val-de-Marne — prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dl = sub.add_parser("download", help="Télécharger les données DVF")
    p_dl.add_argument("--dept", default="94")
    p_dl.add_argument("--years", nargs="+", type=int,
                       default=[2021, 2022, 2023, 2024, 2025])
    p_dl.add_argument("--force", action="store_true")

    p_ref = sub.add_parser("reference", help="Construire la référence prix/m²")
    p_ref.add_argument("--dept", default="94")
    p_ref.add_argument("--years", nargs="+", type=int,
                        default=[2021, 2022, 2023, 2024, 2025])

    p_score = sub.add_parser("score", help="Scorer un bien précis")
    p_score.add_argument("--commune", required=True)
    p_score.add_argument("--type", required=True, choices=TYPES_RETENUS +
                          ["Immeuble (vente en bloc, estimé)"])
    p_score.add_argument("--surface", required=True, type=float)
    p_score.add_argument("--prix", required=True, type=float)
    p_score.add_argument("--dept", default="94")

    p_batch = sub.add_parser("batch", help="Scorer une liste d'annonces (CSV)")
    p_batch.add_argument("--input", required=True)
    p_batch.add_argument("--dept", default="94")

    args = parser.parse_args()

    if args.command == "download":
        download(args.dept, args.years, force=args.force)
    elif args.command == "reference":
        run_reference(args.dept, args.years)
    elif args.command == "score":
        run_score(args)
    elif args.command == "batch":
        run_batch(args)


if __name__ == "__main__":
    main()
