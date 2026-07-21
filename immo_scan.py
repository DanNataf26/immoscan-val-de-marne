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

TYPES_RETENUS = ["Maison", "Appartement", "Local industriel. commercial ou assimilé"]  # types_local bruts DVF exploités


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
    """Nettoie et calcule le prix au m² pour les ventes exploitables.

    Les ventes en VEFA (état futur d'achèvement) sont incluses (pas
    exclues comme avant) mais marquées via la colonne `vefa`, pour
    permettre un affichage optionnel côté app.py (case à cocher) sans
    fausser par défaut les statistiques de référence (voir run_reference,
    qui exclut les VEFA du calcul prix médian/tendance). Adjudication et
    Echange restent exclus (volumes marginaux, prix non représentatifs
    du marché libre — vente sous contrainte ou troc sans prix de marché).
    """
    df = df[df["nature_mutation"].isin(["Vente", "Vente en l'état futur d'achèvement"])].copy()
    df = df[df["type_local"].isin(TYPES_RETENUS)]
    df = df[(df["valeur_fonciere"] > 10_000) & (df["surface_reelle_bati"] > 8)]
    df["_vefa"] = df["nature_mutation"] == "Vente en l'état futur d'achèvement"

    # Détection (avant agrégation, tant que les lignes brutes existent
    # encore) des lignes strictement identiques au sein d'une même
    # mutation+type — signal à faible fiabilité (le format geo-dvf ne
    # permet pas de distinguer avec certitude "co-acquéreurs" de "lots
    # réellement identiques"), mais utile comme avertissement pour les
    # petites mutations. Voir reconstruct_buildings() pour l'usage.
    compte_surface = df.groupby(
        ["id_mutation", "type_local", "surface_reelle_bati"]
    )["surface_reelle_bati"].transform("size")
    compte_type = df.groupby(["id_mutation", "type_local"])["surface_reelle_bati"].transform("size")
    df["_doublon_suspect"] = (compte_surface > 1) & (compte_type <= 4)

    # Une même mutation peut apparaître sur plusieurs lignes (dépendances,
    # plusieurs lots). On agrège au niveau de la mutation pour ne pas
    # sur-pondérer les biens à lots multiples dans le calcul du prix/m².
    # `nb_lots` compte les LIGNES DVF (chaque lot a la sienne), pas les
    # `id_parcelle` distincts : en copropriété, plusieurs lots (voire tous
    # les types d'un immeuble mixte) partagent souvent le même id_parcelle
    # — nunique(id_parcelle) sous-compterait alors une vente de 8
    # appartements comme "1 lot".
    agg = (
        df.groupby(["id_mutation", "date_mutation", "nom_commune", "code_postal",
                     "code_commune", "type_local", "annee", "valeur_fonciere"],
                    as_index=False)
          .agg(surface_reelle_bati=("surface_reelle_bati", "sum"),
               nb_lots=("id_parcelle", "size"),
               doublon_suspect=("_doublon_suspect", "max"),
               vefa=("_vefa", "max"),
               nombre_pieces_principales=("nombre_pieces_principales", "sum"),
               id_parcelle=("id_parcelle", "first"),
               adresse_nom_voie=("adresse_nom_voie", "first"),
               adresse_numero=("adresse_numero", "first"),
               longitude=("longitude", "first"),
               latitude=("latitude", "first"))
    )
    agg = agg[agg["surface_reelle_bati"] > 8]
    agg["prix_m2"] = agg["valeur_fonciere"] / agg["surface_reelle_bati"]
    # On retire les valeurs aberrantes (erreurs de saisie DVF fréquentes).
    # Seuil élargi pour les locaux commerciaux, dont la distribution de
    # prix/m² diffère beaucoup du résidentiel (entrepôt bon marché à
    # boutique en pied d'immeuble très chère) — même logique que côté
    # Cerema DVF+ (_clean_cerema_dataframe).
    est_commercial = agg["type_local"] == "Local industriel. commercial ou assimilé"
    seuil_bas = est_commercial.map({True: 100, False: 500})
    seuil_haut = est_commercial.map({True: 40_000, False: 25_000})
    agg = agg[(agg["prix_m2"] > seuil_bas) & (agg["prix_m2"] < seuil_haut)]
    return agg


def reconstruct_buildings(agg: pd.DataFrame) -> tuple[pd.DataFrame, set]:
    """
    Isole les mutations correspondant probablement à une vente en bloc :
    soit plusieurs lots d'un même type (ex. 8 appartements) sous le même
    id_mutation, soit une mutation MÊLANT plusieurs types de biens (ex.
    appartements + local commercial dans le même immeuble). Dans les deux
    cas, on reconstitue UNE seule ligne "Immeuble (vente en bloc, estimé)"
    au lieu de laisser coexister une ligne par type — car ces sous-lignes
    partagent toutes le même `valeur_fonciere` (le prix total de l'acte,
    répété tel quel sur chaque ligne DVF source), et diviser ce prix total
    par la seule surface d'UNE composante (juste les appartements, ou juste
    le commerce) surestime son prix/m² à elle seule.

    Une colonne `composition` détaille le nombre de lots par type d'origine
    et leur surface (ex. "8 Appartement (612 m²), 1 Local industriel.
    commercial ou assimilé (95 m²)"), pour ne pas perdre cette information
    dans l'historique/les comparables affichés.

    Retourne (immeubles, ids_mutation_reconstruites) — le second élément
    liste les `id_mutation` concernées, pour que l'appelant (run_reference)
    retire les sous-lignes par type d'origine de `agg` et évite de les
    compter deux fois.
    """
    lignes = []
    ids_reconstruits = set()

    for id_mut, groupe in agg.groupby("id_mutation"):
        nb_lots_total = groupe["nb_lots"].sum()
        types_distincts = groupe["type_local"].nunique()
        if types_distincts < 2 and nb_lots_total < 2:
            continue  # mutation simple, un seul bien : rien à reconstituer

        ids_reconstruits.add(id_mut)
        base = groupe.iloc[0]
        surface_totale = groupe["surface_reelle_bati"].sum()
        valeur = base["valeur_fonciere"]  # identique sur toutes les sous-lignes source
        composition = ", ".join(
            f"{int(r.nb_lots)} {r.type_local} ({r.surface_reelle_bati:.0f} m²)"
            for r in groupe.itertuples()
        )
        # Alerte non-bloquante : des lignes DVF strictement identiques (même
        # type + même surface) dans une mutation peuvent signifier soit
        # plusieurs biens réellement identiques (fréquent dans les grands
        # ensembles à plans-types répétés), soit un seul bien dupliqué à
        # cause de plusieurs co-acquéreurs (indivision) — le format geo-dvf
        # public ne permet pas de trancher avec certitude entre les deux.
        # On ne modifie donc PAS le calcul : on signale juste le doute
        # (voir clean() pour le calcul de doublon_suspect, fait AVANT
        # l'agrégation par type pendant que les lignes brutes existent
        # encore).
        if "doublon_suspect" in groupe.columns and groupe["doublon_suspect"].any():
            composition += (
                " — ⚠️ lignes identiques détectées : peut-être un seul bien "
                "avec plusieurs co-acquéreurs plutôt que des lots distincts, "
                "à vérifier sur l'acte"
            )
        lignes.append({
            "id_mutation": id_mut,
            "date_mutation": base["date_mutation"],
            "nom_commune": base["nom_commune"],
            "code_postal": base["code_postal"],
            "code_commune": base["code_commune"],
            "type_local": "Immeuble (vente en bloc, estimé)",
            "annee": base["annee"],
            "valeur_fonciere": valeur,
            "surface_reelle_bati": surface_totale,
            "nb_lots": int(nb_lots_total),
            "nombre_pieces_principales": groupe["nombre_pieces_principales"].sum(),
            "vefa": bool(groupe["vefa"].any()),
            "id_parcelle": base["id_parcelle"],
            "adresse_nom_voie": base["adresse_nom_voie"],
            "adresse_numero": base["adresse_numero"],
            "longitude": base["longitude"],
            "latitude": base["latitude"],
            "prix_m2": (valeur / surface_totale) if surface_totale else None,
            "composition": composition,
        })

    immeubles = pd.DataFrame(lignes)
    if not immeubles.empty:
        immeubles = immeubles[
            (immeubles["prix_m2"] > 500) & (immeubles["prix_m2"] < 40_000)
        ]
    return immeubles, ids_reconstruits


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
    immeubles, ids_reconstruits = reconstruct_buildings(agg)
    agg_restante = agg[~agg["id_mutation"].isin(ids_reconstruits)]
    agg_restante = agg_restante.drop(columns=["doublon_suspect"], errors="ignore")
    full = pd.concat([agg_restante, immeubles], ignore_index=True)

    # Les statistiques de référence (prix médian/m² par commune+type, et
    # leur tendance annuelle) servent au scoring et à la comparaison
    # marché ailleurs dans l'appli — la prime "neuf" des VEFA les
    # biaiserait vers le haut. On les exclut donc ICI, tout en les
    # gardant dans `full` (transactions_nettoysees_{dept}.csv) pour un
    # affichage optionnel côté app.py (case à cocher "Inclure les VEFA").
    full_hors_vefa = full[~full["vefa"].fillna(False)]
    ref = build_reference(full_hors_vefa)
    trend = build_trend(full_hors_vefa)

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
    act_pure = (df["nblocact"] > 0) & (df["nblocmai"] == 0) & (df["nblocapt"] == 0)

    def _composition(r, nb_lots_col, libelle):
        """Détail lisible : nombre de lots du type identifié, + dépendances
        (places de parking, caves...) si le champ nblocdep en signale."""
        base = f"{int(r[nb_lots_col])} {libelle}"
        nb_dep = r.get("nblocdep", 0)
        if pd.notna(nb_dep) and nb_dep > 0:
            base += f" + {int(nb_dep)} dépendance(s) (parking/cave, non chiffrées en surface)"
        return base

    d_maison = df[maison_pure].copy()
    d_maison["type_local"] = "Maison"
    d_maison["surface_reelle_bati"] = d_maison["sbatmai"]
    d_maison["nb_lots"] = d_maison["nblocmai"]
    d_maison["composition"] = d_maison.apply(
        lambda r: _composition(r, "nblocmai", "Maison"), axis=1)

    d_appt = df[appt_pure].copy()
    d_appt["type_local"] = "Appartement"
    d_appt["surface_reelle_bati"] = d_appt["sbatapt"]
    d_appt["nb_lots"] = d_appt["nblocapt"]
    d_appt["composition"] = d_appt.apply(
        lambda r: _composition(r, "nblocapt", "Appartement"), axis=1)

    d_act = df[act_pure].copy()
    d_act["type_local"] = "Local industriel. commercial ou assimilé"
    d_act["surface_reelle_bati"] = d_act["sbatact"]
    d_act["nb_lots"] = d_act["nblocact"]
    d_act["composition"] = d_act.apply(
        lambda r: _composition(r, "nblocact", "Local industriel. commercial ou assimilé"), axis=1)

    combined = pd.concat([d_maison, d_appt, d_act], ignore_index=True)
    if combined.empty:
        return combined

    combined = combined.rename(columns={"datemut": "date_mutation", "anneemut": "annee",
                                          "valeurfonc": "valeur_fonciere"})
    combined = combined[(combined["valeur_fonciere"] > 10_000) & (combined["surface_reelle_bati"] > 8)]
    combined["prix_m2"] = combined["valeur_fonciere"] / combined["surface_reelle_bati"]

    est_commercial = combined["type_local"] == "Local industriel. commercial ou assimilé"
    seuil_bas = est_commercial.map({True: 100, False: 500})
    seuil_haut = est_commercial.map({True: 40_000, False: 25_000})
    combined = combined[(combined["prix_m2"] > seuil_bas) & (combined["prix_m2"] < seuil_haut)]

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
            "latitude", "longitude", "source", "nb_lots", "composition"]
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
                      since_years: int = 5, include_cerema: bool = True,
                      tri: str = "distance",
                      include_vefa: bool = False,
                      surface_reference: float | None = None) -> tuple[pd.DataFrame, dict]:
    """
    Cherche, dans le cache des transactions nettoyées, les ventes réelles les
    plus proches d'un point GPS donné, limitées aux `since_years` dernières
    années (par défaut 5) — utile pour situer un bien recherché par adresse
    par rapport à de vraies ventes comparables récentes et proches.
    Nécessite d'avoir lancé 'reference' au préalable pour ce département.

    Si `include_cerema` est vrai et qu'un cache Cerema DVF+ existe pour ce
    département (2014-2020, importé manuellement — voir README), ses ventes
    sont ajoutées en complément historique pour la même zone/type, avec une
    colonne 'source' pour les distinguer. `since_years` NE s'applique QU'au
    DVF récent — Cerema couvre une période fixe et déjà close (2014-2020),
    lui appliquer un filtre "depuis aujourd'hui" l'exclurait purement et
    simplement dès que `since_years` est inférieur à l'écart (croissant
    avec le temps) entre aujourd'hui et 2020, sans rapport avec l'intention
    de l'utilisateur de voir cette période historique.

    `include_vefa` (faux par défaut) : les ventes en VEFA (état futur
    d'achèvement, neuf sur plan) sont exclues sauf activation explicite —
    leur prix inclut une prime "neuf" qui n'est pas directement comparable
    à une revente ancienne. Voir clean()/run_reference() pour le détail.

    `tri` détermine l'ordre du tableau retourné : "distance" (les plus
    proches en premier, par défaut) ou "date" (les plus récentes en premier).
    Dans les deux cas, les résultats DVF et Cerema DVF+ restent mélangés
    dans un seul tableau trié globalement — ce n'est pas une lecture
    chronologique du quartier, seulement un classement selon le critère choisi.

    `surface_reference` : si fourni (typiquement la surface du bien identifié
    dans "Historique probable"), sert de critère de tri SUPPLÉMENTAIRE, après
    la priorité de source et la distance — utile notamment quand plusieurs
    lots d'un même immeuble partagent exactement la même distance (le DVF ne
    géolocalise qu'au niveau de l'immeuble, pas du logement individuel), cas
    où trier uniquement par distance ne permet pas de les départager.

    Retourne un tuple (DataFrame limité à `max_results` lignes selon le tri
    choisi, dict de synthèse sur l'ENSEMBLE des résultats trouvés avant
    troncature : nombre total par source, prix moyen/m² par type de bien).
    """
    from datetime import datetime

    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not cache_path.exists():
        raise SystemExit(f"Cache introuvable ({cache_path}). Lancez 'reference' d'abord.")

    df = pd.read_csv(cache_path)
    df = df.dropna(subset=["latitude", "longitude"])
    if "vefa" in df.columns:
        if not include_vefa:
            df = df[~df["vefa"].fillna(False)]
        df["source"] = df["vefa"].fillna(False).map({True: "DVF (VEFA)", False: "DVF (2021+)"})
    else:
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
            # Pas de seuil "depuis aujourd'hui" ici : Cerema DVF+ couvre une
            # période fixe et déjà close (2014-2020, voir CEREMA_ANNEE_MAX).
            # Lui appliquer le même filtre glissant que le DVF récent
            # l'exclurait purement et simplement dès que `since_years` est
            # inférieur à l'écart entre aujourd'hui et 2020 (ce qui ne fait
            # que croître avec le temps) — sans lien avec l'intention de
            # l'utilisateur, qui est de voir cette période historique quand
            # elle est disponible. Le rayon et le type restent filtrés.
            if not cerema.empty:
                frames.append(cerema)

    if not frames:
        return pd.DataFrame(), {"total": 0, "total_par_source": {}, "prix_m2_moyen_par_type": {}}

    combined = pd.concat(frames, ignore_index=True)
    combined["distance_m"] = combined.apply(
        lambda r: haversine_m(lat, lon, r["latitude"], r["longitude"]), axis=1
    )
    proches_complet = combined[combined["distance_m"] <= radius_m]

    # Synthèse calculée sur l'ENSEMBLE trouvé (avant troncature à max_results),
    # pour donner une vision complète même quand le tableau affiché est limité.
    resume = {
        "total": len(proches_complet),
        "total_par_source": proches_complet["source"].value_counts().to_dict(),
        "prix_m2_moyen_par_type": (
            proches_complet.groupby("type_local")["prix_m2"].mean().round(0).to_dict()
        ),
    }

    if tri == "date":
        # Le DVF récent (2021+) est par construction toujours plus récent
        # que Cerema DVF+ (borné à 2020) : ce tri fait donc déjà naturellement
        # remonter le DVF en premier, sans besoin de traitement particulier.
        proches = proches_complet.sort_values("date_mutation", ascending=False)
    else:
        # Priorité au DVF récent sur Cerema DVF+ à distance égale : Cerema
        # est souvent plus dense localement (7 ans d'historique 2014-2020
        # contre quelques années de DVF récent), et un tri par distance pur
        # le ferait dominer la troncature à `max_results` alors que le DVF
        # récent est plus représentatif du marché actuel.
        proches_complet = proches_complet.copy()
        proches_complet["_cerema"] = proches_complet["source"].astype(str).str.startswith("Cerema")
        # Écart de surface au bien de référence, en tri tertiaire : le DVF ne
        # géolocalisant qu'au niveau de l'immeuble, plusieurs lots partagent
        # souvent exactement la même distance (cas fréquent en copropriété) —
        # sans ce critère, leur ordre entre eux serait arbitraire.
        if surface_reference is not None and "surface_reelle_bati" in proches_complet.columns:
            proches_complet["_ecart_surface"] = (
                proches_complet["surface_reelle_bati"] - surface_reference
            ).abs()
        else:
            proches_complet["_ecart_surface"] = 0
        proches = proches_complet.sort_values(
            ["_cerema", "distance_m", "_ecart_surface"]
        ).drop(columns=["_cerema", "_ecart_surface"])

    cols = ["nom_commune", "type_local", "date_mutation", "valeur_fonciere",
            "surface_reelle_bati", "prix_m2", "distance_m", "source"]
    if "nombre_pieces_principales" in proches.columns:
        cols.append("nombre_pieces_principales")
    if "composition" in proches.columns:
        cols.append("composition")
    # adresse_numero/adresse_nom_voie n'existent pas côté Cerema (source sans
    # champ adresse, seulement des identifiants de parcelle — voir README).
    # On uniformise TOUTE la colonne en texte (pas seulement les lignes
    # Cerema) : un mélange nombre/texte dans une même colonne pandas fait
    # planter la conversion Arrow utilisée par Streamlit pour l'affichage
    # (erreur "Could not convert 'n/d' ... tried to convert to double").
    if "adresse_numero" in proches.columns:
        proches = proches.copy()

        def _fmt_numero(v):
            if pd.isna(v):
                return "n/d"
            try:
                return str(int(v))  # évite le ".0" final sur les numéros entiers
            except (TypeError, ValueError):
                return str(v)

        proches["adresse_numero"] = proches["adresse_numero"].map(_fmt_numero)
        proches["adresse_nom_voie"] = proches["adresse_nom_voie"].fillna(
            "(adresse non disponible pour cette source)"
        )
        cols = ["adresse_numero", "adresse_nom_voie"] + cols
    return proches[cols].head(max_results), resume


def find_comparables_auto(dept: str, lat: float, lon: float, type_local: str | None = None,
                           radius_m: float = 100, since_years: int = 5,
                           max_results: int = 15, include_cerema: bool = True,
                           tri: str = "distance", cible_min: int = 15,
                           include_vefa: bool = False,
                           surface_reference: float | None = None) -> dict:
    """
    Comme `find_comparables`, mais élargit automatiquement la recherche si
    le nombre de résultats trouvés est inférieur à `cible_min` : d'abord le
    rayon (jusqu'à 1000 m), puis si toujours insuffisant, la période
    (jusqu'à 15 ans), en gardant le rayon maximal atteint. S'arrête dès que
    la cible est atteinte ou que les deux limites (1000m/15 ans) sont
    épuisées — nombre de tentatives volontairement limité (4 paliers de
    rayon, 3 paliers d'années) pour rester rapide.

    `include_vefa`, `surface_reference` : voir find_comparables().

    L'élargissement se base sur le nombre de résultats **DVF (2021+/VEFA)**
    trouvés, PAS sur le total combiné avec Cerema DVF+ : sinon, un volume
    Cerema abondant à proximité (2014-2020, souvent plus dense que quelques
    années de DVF récent) satisferait `cible_min` à lui seul et arrêterait
    l'élargissement avant que le DVF récent — plus représentatif du marché
    actuel — n'ait sa chance d'être exploré plus loin. Cerema reste malgré
    tout inclus dans le résultat final dès qu'il y en a (voir
    find_comparables), en complément, pas à la place du DVF récent.

    Retourne un dict : {df, resume, radius_final, since_years_final, elargi}
    — `elargi` indique si les paramètres initiaux ont dû être dépassés,
    pour que l'app puisse en informer clairement l'utilisateur.
    """
    def _nb_dvf(resume):
        return sum(
            n for src, n in resume["total_par_source"].items()
            if not str(src).startswith("Cerema")
        )

    paliers_radius = sorted(set([radius_m, 250, 500, 1000]))
    paliers_radius = [r for r in paliers_radius if r >= radius_m]
    paliers_annees = sorted(set([since_years, 10, 15]))
    paliers_annees = [a for a in paliers_annees if a >= since_years]

    radius_final = radius_m
    df, resume = find_comparables(dept, lat, lon, type_local, radius_m, max_results,
                                    since_years, include_cerema, tri,
                                    include_vefa=include_vefa,
                                    surface_reference=surface_reference)

    if _nb_dvf(resume) < cible_min:
        for r in paliers_radius[1:]:
            df, resume = find_comparables(dept, lat, lon, type_local, r, max_results,
                                            since_years, include_cerema, tri,
                                            include_vefa=include_vefa,
                                            surface_reference=surface_reference)
            radius_final = r
            if _nb_dvf(resume) >= cible_min:
                break

    since_years_final = since_years
    if _nb_dvf(resume) < cible_min:
        for a in paliers_annees[1:]:
            df, resume = find_comparables(dept, lat, lon, type_local, radius_final, max_results,
                                            a, include_cerema, tri,
                                            include_vefa=include_vefa,
                                            surface_reference=surface_reference)
            since_years_final = a
            if _nb_dvf(resume) >= cible_min:
                break

    elargi = (radius_final != radius_m) or (since_years_final != since_years)
    return {
        "df": df, "resume": resume, "radius_final": radius_final,
        "since_years_final": since_years_final, "elargi": elargi,
    }




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
                          commune: str | None = None, max_results: int = 30,
                          code_insee: str | None = None,
                          include_vefa: bool = False) -> pd.DataFrame:
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

    `code_insee`, si fourni (typiquement depuis le géocodage BAN de
    l'adresse, réputé fiable), est utilisé en priorité pour filtrer par
    commune dans le repli cadastre/Cerema — les API cadastre elles-mêmes se
    sont montrées peu fiables sur ce champ précis en conditions réelles
    (absent ou tronqué selon les services).

    `include_vefa` (faux par défaut) : voir find_comparables().

    Si aucune correspondance exacte n'est trouvée, un repli de proximité très
    étroit (30 m) est tenté et clairement signalé comme approximatif.
    """
    cache_path = OUTPUT_DIR / f"transactions_nettoyees_{dept}.csv"
    if not cache_path.exists():
        raise SystemExit(f"Cache introuvable ({cache_path}). Lancez 'reference' d'abord.")

    df = pd.read_csv(cache_path)
    if "vefa" in df.columns and not include_vefa:
        df = df[~df["vefa"].fillna(False)]
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
    if "vefa" in exact.columns:
        exact["source"] = exact["vefa"].fillna(False).map({True: "DVF (VEFA)", False: "DVF (2021+)"})
    else:
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
                # nb_lots vient désormais du cache Cerema lui-même (nombre
                # réel de lots du type identifié — voir _clean_cerema_dataframe),
                # plus la colonne composition pour le détail (dont dépendances).
                result = pd.concat([result, hist_cerema], ignore_index=True)

    if result.empty and lat is not None and lon is not None:
        # Repli : la parcelle cadastrale est indépendante de toute vente DVF
        # — elle permet de chercher dans Cerema DVF+ même quand aucune vente
        # récente (2021+) n'existe pour faire le pont habituel.
        #
        # Priorité au RNB (recherche par l'ADRESSE elle-même, via le
        # bâtiment identifié avec un score de confiance BAN) — bien plus
        # fiable que la géolocalisation seule dans les zones denses ou
        # subdivisées (lotissements, copropriétés), où plusieurs parcelles
        # voisines peuvent être proches d'un même point GPS.
        try:
            parcelle_info = get_parcelle_via_rnb(address)
        except Exception:
            parcelle_info = None

        if not parcelle_info:
            # Repli sur les méthodes GPS (Géoplateforme puis API Carto).
            # IMPORTANT : `get_parcelle_cadastrale` peut légitimement
            # retourner PLUSIEURS parcelles candidates quand le point GPS
            # est proche d'une frontière (comportement volontaire pour
            # d'autres usages). Ici, on ne procède QUE si une seule parcelle
            # sans ambiguïté est trouvée — sinon, on risquerait de mélanger
            # l'historique de plusieurs biens voisins différents sous une
            # même adresse, ce qui serait pire que de ne rien afficher.
            try:
                parcelle_info = get_parcelle_cadastrale(lat, lon)
            except Exception:
                parcelle_info = None

        if parcelle_info and parcelle_info.get("nb_parcelles") == 1 and parcelle_info.get("parcelles"):
            cerema = load_cerema_cache(dept)
            if cerema is not None and not cerema.empty:
                cerema = cerema.copy()
                cerema["_section"] = cerema["id_parcelle"].astype(str).str[8:10].str.lstrip("0").str.upper()
                cerema["_numero"] = cerema["id_parcelle"].astype(str).str[10:14].str.lstrip("0")
                cerema["_code_insee"] = cerema["id_parcelle"].astype(str).str[0:5]
                p = parcelle_info["parcelles"][0]
                sec = str(p.get("section") or "").lstrip("0").upper()
                num = str(p.get("numero") or "").lstrip("0")
                code_insee_cible = str(code_insee or p.get("code_insee") or "").strip()
                hist_cerema = (
                    cerema[
                        (cerema["_section"] == sec) & (cerema["_numero"] == num)
                        & (cerema["_code_insee"] == code_insee_cible)
                    ].copy()
                    if sec and num and code_insee_cible else pd.DataFrame()
                )
                if not hist_cerema.empty:
                    hist_cerema = hist_cerema.drop(columns=["_section", "_numero", "_code_insee"])
                    hist_cerema["correspondance"] = "Exacte (parcelle cadastrale confirmée via GPS, Cerema DVF+)"
                    hist_cerema["nom_commune"] = commune or hist_cerema.get("nom_commune")
                    hist_cerema["adresse_dvf"] = address
                    result = hist_cerema

    if result.empty and lat is not None and lon is not None:
        # Repli très étroit, clairement signalé comme approximatif.
        df2 = df.dropna(subset=["latitude", "longitude"]).copy()
        if not df2.empty:
            df2["distance_m"] = df2.apply(
                lambda r: haversine_m(lat, lon, r["latitude"], r["longitude"]), axis=1
            )
            proche = df2[df2["distance_m"] <= 30].copy()
            if target_numero and "adresse_numero" in proche.columns:
                # Un numéro DVF différent du numéro recherché, sur un point
                # pourtant proche, désigne presque toujours un bâtiment
                # voisin distinct (deux numéros consécutifs peuvent être à
                # quelques mètres l'un de l'autre) — on l'exclut plutôt que
                # de le faire passer pour une correspondance approximative
                # de CETTE adresse précise. On ne garde que les lignes sans
                # numéro renseigné (rare) ou dont le numéro correspond.
                numero_proche_norm = (
                    proche["adresse_numero"].fillna("").astype(str)
                    .str.replace(r"\.0$", "", regex=True).str.lower()
                )
                proche = proche[(numero_proche_norm == "") | (numero_proche_norm == target_numero)]
            proche["correspondance"] = "Approximative (proximité < 30 m, adresse non confirmée)"
            if "vefa" in proche.columns:
                proche["source"] = proche["vefa"].fillna(False).map({True: "DVF (VEFA)", False: "DVF (2021+)"})
            else:
                proche["source"] = "DVF (2021+)"
            result = proche

    if result.empty:
        return pd.DataFrame()

    result = result.sort_values("date_mutation", ascending=False)
    cols = ["date_mutation", "adresse_dvf", "nom_commune", "type_local",
            "valeur_fonciere", "surface_reelle_bati", "prix_m2",
            "nb_lots", "correspondance", "source"]
    if "nombre_pieces_principales" in result.columns:
        cols.append("nombre_pieces_principales")
    if "composition" in result.columns:
        cols.append("composition")
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
    pour l'adresse EXACTE (numéro + rue), via l'API ouverte de l'ADEME —
    même principe de correspondance que pour le DVF/la BDNB
    (_parse_address_number_street), pour ne plus remonter les DPE d'adresses
    voisines simplement proches en recherche textuelle libre.

    IMPORTANT : ce jeu de données ne couvre que les DPE établis à partir du
    1er juillet 2021 (réforme du DPE). Un bien dont le dernier diagnostic est
    antérieur à cette date n'y figurera pas — ce n'est pas un défaut de cette
    fonction, l'ADEME publie ces DPE plus anciens dans un jeu de données séparé.

    NB : le nom exact du jeu de données / des champs sur l'API data-fair de
    l'ADEME a déjà changé par le passé (dataset actuel : dpe03existant, vu
    aussi mentionné ailleurs sous d'autres noms selon les époques) — plusieurs
    noms de champs candidats sont donc essayés pour l'adresse et pour la
    lettre de classe énergie/GES, plutôt qu'un seul nom supposé figé.
    """
    import requests
    query = address.strip()
    if code_postal and code_postal not in query:
        query = f"{query} {code_postal}"
    params = {"q": query, "size": max(max_results * 6, 30)}

    target_numero, target_rue = _parse_address_number_street(address)
    rue_tokens = [t for t in target_rue.split() if len(t) > 2] if target_rue else []

    CHAMPS_ADRESSE_CANDIDATS = [
        "adresse_ban", "adresse_brut", "adresse", "Adresse_(BAN)",
        "Adresse_brut", "geo_adresse",
    ]

    try:
        resp = requests.get(ADEME_DPE_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        df = pd.json_normalize(results)
        if not target_numero or not rue_tokens:
            return df.head(max_results)

        champ_adresse = next((c for c in CHAMPS_ADRESSE_CANDIDATS if c in df.columns), None)
        if champ_adresse is None:
            # Aucun champ d'adresse reconnu dans ce schéma : on ne peut pas
            # filtrer précisément, on retourne tel quel plutôt que de risquer
            # de tout exclure à tort — voir le diagnostic technique dans l'app.
            return df.head(max_results)

        def _correspond(adr_dpe):
            if pd.isna(adr_dpe):
                return False
            num, rue = _parse_address_number_street(str(adr_dpe))
            return num == target_numero and all(t in rue for t in rue_tokens)

        df_exact = df[df[champ_adresse].apply(_correspond)]
        if not df_exact.empty:
            return df_exact.head(max_results)
        # Rien d'exact : on retourne quand même le lot brut (non filtré) pour
        # que l'appli puisse au moins montrer qu'il y a des résultats
        # voisins, clairement signalés comme non confirmés — mieux que rien
        # du tout si l'adresse exacte n'a simplement pas encore de DPE publié.
        return None
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


RNB_API_URL = "https://rnb-api.beta.gouv.fr/api/alpha/buildings"


def get_parcelle_via_rnb(address: str) -> dict | None:
    """
    Identifie le(s) bâtiment(s) correspondant à une adresse via le RNB
    (Référentiel National des Bâtiments, beta.gouv.fr — service public
    gratuit, sans clé), puis interroge le cadastre au point précis de CE
    bâtiment (et non au point d'adresse brut de la BAN).

    Pourquoi : le RNB géocode l'adresse via la BAN (avec un score de
    confiance) et identifie LE ou LES bâtiments réels à cette adresse, avec
    leur point géométrique propre — dérivé de l'empreinte du bâtiment, donc
    typiquement bien à l'intérieur de la bonne parcelle, contrairement au
    point d'adresse générique (souvent placé côté rue, proche d'une
    frontière de parcelle dans les zones denses/subdivisées).

    N'utilise PAS le paramètre `plots` de l'API RNB (documenté mais semble
    ne renvoyer aucune parcelle en conditions réelles testées — peut-être
    une fonctionnalité pas encore pleinement déployée sur ce service beta).
    Repose à la place sur une requête cadastre ponctuelle (Géoplateforme
    puis API Carto, voir `get_parcelle_cadastrale`) au(x) point(s) bâtiment
    obtenu(s), en essayant chaque bâtiment candidat jusqu'à obtenir un
    résultat non ambigu.
    """
    import requests

    try:
        resp = requests.get(
            f"{RNB_API_URL}/address/", params={"q": address}, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok" or not data.get("results"):
            return None

        for batiment in data["results"]:
            point = batiment.get("point") or {}
            coords = point.get("coordinates")
            if not coords or len(coords) != 2:
                continue
            lon_bat, lat_bat = coords[0], coords[1]

            # Priorité au test d'appartenance strict (point-in-polygon) —
            # garantie la plus forte pour un point déjà précis comme celui
            # d'un bâtiment. Repli sur les méthodes floues (Géoplateforme,
            # périmètre) seulement si le test strict échoue.
            parcelle_info = _point_exact_apicarto(lat_bat, lon_bat)
            if not parcelle_info:
                parcelle_info = get_parcelle_cadastrale(lat_bat, lon_bat)

            if parcelle_info and parcelle_info.get("nb_parcelles") == 1:
                parcelle_info = dict(parcelle_info)
                parcelle_info["source"] = (
                    f"RNB (point du bâtiment {batiment.get('rnb_id')}) "
                    f"+ {parcelle_info.get('source')}"
                )
                return parcelle_info
        return None
    except Exception as exc:
        print(f"[warn] RNB échoué pour '{address}' : {exc}")
        return None


GEOPLATEFORME_REVERSE_URL = "https://data.geopf.fr/geocodage/reverse"


def _get_parcelle_via_geoplateforme(lat: float, lon: float) -> dict | None:
    """
    Tente d'obtenir LA parcelle la plus proche du point via le nouveau
    service de géocodage inversé de la Géoplateforme (IGN), successeur
    officiel de l'ancienne API Adresse/BAN (dépréciée fin janvier 2026).

    Contrairement à notre ancienne méthode par périmètre (qui liste toutes
    les parcelles touchées sans les classer), ce service retourne la
    parcelle dont le **barycentre est le plus proche** du point recherché —
    un vrai classement par proximité, bien plus robuste dans les zones
    denses/subdivisées (lotissements, copropriétés) où plusieurs petites
    parcelles voisines se touchent. Documentation confirmée via forums
    techniques IGN/GeoRezo ; **non testée en conditions réelles** faute
    d'accès réseau dans l'environnement de développement — le nom exact de
    certains champs de la réponse peut nécessiter un ajustement après un
    premier test réel (plusieurs noms candidats déjà prévus ci-dessous).
    """
    import requests

    try:
        resp = requests.get(
            GEOPLATEFORME_REVERSE_URL,
            params={"index": "parcel", "lon": lon, "lat": lat, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return None
        p = features[0]["properties"]

        # Noms de champs pas confirmés à 100% pour cet index — plusieurs
        # candidats essayés par prudence (cf. docstring).
        section = p.get("section") or p.get("sheet_number") or p.get("feuille")
        numero = p.get("number") or p.get("numero") or p.get("insee_number")
        id_parcelle_brut = p.get("id") or p.get("cleabs")

        # code_insee dérivé de préférence depuis id_parcelle (5 premiers
        # caractères) plutôt que d'un champ séparé ("citycode" observé en
        # conditions réelles tronqué à 3 chiffres, sans le département —
        # ex. "028" au lieu de "94028").
        code_insee = None
        if id_parcelle_brut and len(str(id_parcelle_brut)) >= 5:
            code_insee = str(id_parcelle_brut)[0:5]
        if not code_insee:
            code_insee = (
                p.get("citycode") or p.get("municipalitycode") or p.get("commune")
            )
        if not section or not numero:
            return None

        parcelle = {
            "id_parcelle": id_parcelle_brut,
            "code_insee": code_insee,
            "prefixe": p.get("prefixe") or p.get("com_abs") or "000",
            "section": section,
            "numero": numero,
            "contenance_m2": p.get("contenance"),
        }
        return {
            **parcelle, "nb_parcelles": 1, "parcelles": [parcelle],
            "source": "Géoplateforme (barycentre le plus proche)",
        }
    except Exception as exc:
        print(f"[warn] Géoplateforme (reverse parcel) échouée pour ({lat}, {lon}) : {exc}")
        return None


def _point_exact_apicarto(lat: float, lon: float) -> dict | None:
    """
    Requête ponctuelle exacte (point-in-polygon strict) via l'API Carto IGN.
    Ne retourne un résultat que si le point tombe EXACTEMENT dans UNE SEULE
    parcelle — un test d'appartenance strict, garantie plus forte qu'un
    classement par proximité de centre (utilisé par la Géoplateforme), en
    particulier pour un point déjà connu comme précis (ex. point d'un
    bâtiment identifié via le RNB).
    """
    import requests, json

    try:
        resp = requests.get(
            IGN_CADASTRE_URL,
            params={"geom": json.dumps({"type": "Point", "coordinates": [lon, lat]})},
            timeout=10,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if len(features) != 1:
            return None
        p = features[0]["properties"]
        parcelle = {
            "id_parcelle": p.get("id"),
            "code_insee": p.get("commune"),
            "prefixe": p.get("prefixe"),
            "section": p.get("section"),
            "numero": p.get("numero"),
            "contenance_m2": p.get("contenance"),
        }
        return {**parcelle, "nb_parcelles": 1, "parcelles": [parcelle], "source": "point exact (API Carto)"}
    except Exception as exc:
        print(f"[warn] API Carto (point exact) échouée pour ({lat}, {lon}) : {exc}")
        return None


def get_parcelle_cadastrale(lat: float, lon: float, buffer_m: float = 10) -> dict | None:
    """
    Récupère la parcelle cadastrale au point donné.

    Stratégie en trois temps :
    0. **Nouveau service Géoplateforme** (géocodage inversé IGN, successeur
       de l'API BAN) — classe les parcelles par proximité du barycentre,
       ce qui résout la plupart des cas ambigus (zones denses/subdivisées)
       sans jamais renvoyer une liste non triée. Essayé en premier.
    1. **Requête ponctuelle exacte** (API Carto, point-in-polygon) — repli
       si la Géoplateforme échoue. Précise pour la grande majorité des
       adresses réelles, puisqu'un point d'adresse géocodé tombe
       normalement bien à l'intérieur de la parcelle bâtie correspondante.
    2. **Repli sur un petit périmètre** (par défaut ±10 m, soit un carré
       d'environ 20 m de côté) seulement si les deux étapes précédentes ne
       donnent rien — cas typique où le point d'adresse est placé sur la
       voie d'accès plutôt que sur la parcelle bâtie elle-même. Dans ce
       cas, toutes les parcelles du périmètre sont retournées comme
       candidates à vérifier plutôt que d'en choisir une seule
       silencieusement.
    """
    geoplateforme_result = _get_parcelle_via_geoplateforme(lat, lon)
    if geoplateforme_result:
        return geoplateforme_result

    import requests, json, math

    def _query(geom_dict):
        resp = requests.get(IGN_CADASTRE_URL, params={"geom": json.dumps(geom_dict)}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("features", [])

    def _to_parcelle_dict(props):
        return {
            "id_parcelle": props.get("id"),
            "code_insee": props.get("commune"),
            "prefixe": props.get("prefixe"),
            "section": props.get("section"),
            "numero": props.get("numero"),
            "contenance_m2": props.get("contenance"),
        }

    try:
        point_features = _query({"type": "Point", "coordinates": [lon, lat]})
        if len(point_features) == 1:
            p = _to_parcelle_dict(point_features[0]["properties"])
            return {**p, "nb_parcelles": 1, "parcelles": [p], "source": "point exact (API Carto)"}

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
                vues[key] = _to_parcelle_dict(p)
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
            "source": "périmètre (point exact ambigu ou vide)",
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


def interpret_dpe_par_logement(dpe: pd.DataFrame | None) -> list[dict]:
    """
    Comme interpret_dpe_classe(), mais renvoie UNE entrée par ligne du
    tableau DPE plutôt que de résumer sur la seule première ligne — une
    correspondance numéro+rue peut légitimement remonter plusieurs DPE
    distincts (un immeuble collectif a en général un DPE par logement, pas
    un DPE unique pour tout le bâtiment). Présenter une seule lettre pour
    l'ensemble laisserait croire à tort qu'elle s'applique à tout le
    bâtiment.

    Essaie aussi de repérer, parmi les colonnes disponibles, tout champ
    permettant de distinguer les logements entre eux (étage, complément
    d'adresse, cage d'escalier...) — noms de colonnes non garantis stables
    dans le temps côté ADEME, d'où une recherche par mot-clé plutôt qu'un
    nom de colonne unique supposé figé.
    """
    if dpe is None or dpe.empty:
        return []

    candidats_energie = ["etiquette_dpe", "classe_consommation_energie", "etiquette_dpe_final"]
    candidats_ges = ["etiquette_ges", "classe_estimation_ges", "etiquette_ges_final"]
    candidats_date = ["date_etablissement_dpe", "date_reception_dpe", "date_visite_diagnostiqueur"]
    MOTS_CLES_DISTINCTION = [
        "complement", "etage", "appartement", "logement", "cage",
        "escalier", "porte", "batiment", "lot",
    ]
    colonnes_distinction = [
        c for c in dpe.columns
        if any(mot in c.lower() for mot in MOTS_CLES_DISTINCTION)
        and c not in ("nombre_appartement",)  # champ agrégat, pas un identifiant de lot
    ]

    entrees = []
    for _, row in dpe.iterrows():
        classe_energie = next(
            (str(row[c]).upper().strip() for c in candidats_energie
             if c in dpe.columns and pd.notna(row.get(c))),
            None,
        )
        if classe_energie is None:
            continue
        classe_ges = next(
            (str(row[c]).upper().strip() for c in candidats_ges
             if c in dpe.columns and pd.notna(row.get(c))),
            None,
        )
        date_dpe = next(
            (row[c] for c in candidats_date if c in dpe.columns and pd.notna(row.get(c))),
            None,
        )
        distinction = {
            c: row[c] for c in colonnes_distinction
            if pd.notna(row.get(c)) and str(row[c]).strip() not in ("", "0")
        }
        entrees.append({
            "classe_energie": classe_energie,
            "classe_ges": classe_ges,
            "date_dpe": date_dpe,
            "distinction": distinction,
        })
    return entrees


def prioriser_dpe_selon_selection(
    dpe: pd.DataFrame | None, type_selectionne: str | None, surface_selectionnee: float | None,
) -> pd.DataFrame | None:
    """
    Trie (sans exclure) les DPE trouvés pour une adresse, en plaçant en
    premier ceux qui correspondent au type et/ou à la surface déjà
    sélectionnés dans "Historique probable" pour cette même adresse — pour
    corréler les deux sections plutôt que de les traiter indépendamment.

    Ne filtre PAS (n'exclut aucune ligne) : une différence de surface entre
    DVF (souvent Carrez) et DPE (surface habitable, définition différente)
    est normale et ne doit pas masquer à tort le bon logement si l'écart
    est seulement de quelques m². Le tri place juste les correspondances
    probables en tête, le reste des DPE de l'adresse restant visible en
    dessous.
    """
    if dpe is None or dpe.empty:
        return dpe

    df = dpe.copy()
    CANDIDATS_TYPE = ["type_batiment", "type_batiment_dpe"]
    CANDIDATS_SURFACE = ["surface_habitable_logement", "surface_habitable"]
    col_type = next((c for c in CANDIDATS_TYPE if c in df.columns), None)
    col_surface = next((c for c in CANDIDATS_SURFACE if c in df.columns), None)

    # Le DVF dit "Appartement"/"Maison", le DPE dit souvent "appartement"/
    # "maison" en minuscules (parfois d'autres variantes) — normalise pour
    # comparer sur le mot-clé plutôt que sur une égalité stricte de casse.
    type_norm = None
    if type_selectionne:
        t = type_selectionne.lower()
        if "appart" in t:
            type_norm = "appart"
        elif "maison" in t:
            type_norm = "maison"

    def _score_type(row):
        if col_type and type_norm and pd.notna(row.get(col_type)):
            return 0 if type_norm in str(row[col_type]).lower() else 1
        return 1

    def _ecart_surface(row):
        if col_surface and surface_selectionnee and pd.notna(row.get(col_surface)):
            try:
                return abs(float(row[col_surface]) - surface_selectionnee)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    df["_score_type"] = df.apply(_score_type, axis=1)
    df["_ecart_surface"] = df.apply(_ecart_surface, axis=1)
    df = df.sort_values(["_score_type", "_ecart_surface"]).drop(
        columns=["_score_type", "_ecart_surface"]
    )
    return df


def construire_tableau_dpe(dpe: pd.DataFrame | None) -> tuple[pd.DataFrame | None, str | None]:
    """
    Réorganise le tableau DPE brut en mettant en premier les colonnes
    essentielles pour distinguer un logement d'un autre dans un immeuble
    collectif : classe énergie, classe GES, date du DPE, puis tout champ
    de distinction du logement (étage, complément d'adresse...) — le reste
    des colonnes brutes suit, inchangé. Ne renomme ni ne supprime aucune
    colonne d'origine, se contente de réordonner pour la lisibilité — un
    seul tableau plutôt qu'un résumé séparé du détail brut, pour que la
    ligne d'un logement dans le résumé corresponde visuellement à la même
    ligne dans le détail.

    Retourne (tableau réordonné, nom de la colonne classe énergie) — le
    second élément permet à l'appelant d'appliquer une couleur de fond sur
    cette colonne précisément, sans avoir à redeviner son nom.
    """
    if dpe is None or dpe.empty:
        return dpe, None

    candidats_energie = ["etiquette_dpe", "classe_consommation_energie", "etiquette_dpe_final"]
    candidats_ges = ["etiquette_ges", "classe_estimation_ges", "etiquette_ges_final"]
    candidats_date = ["date_etablissement_dpe", "date_reception_dpe", "date_visite_diagnostiqueur"]
    MOTS_CLES_DISTINCTION = [
        "complement", "etage", "appartement", "logement", "cage",
        "escalier", "porte", "batiment", "lot",
    ]

    col_energie = next((c for c in candidats_energie if c in dpe.columns), None)
    col_ges = next((c for c in candidats_ges if c in dpe.columns), None)
    col_date = next((c for c in candidats_date if c in dpe.columns), None)
    deja_prioritaires = {col_energie, col_ges, col_date}
    colonnes_distinction = [
        c for c in dpe.columns
        if any(mot in c.lower() for mot in MOTS_CLES_DISTINCTION)
        and c not in ("nombre_appartement",)
        and c not in deja_prioritaires
    ]

    colonnes_prioritaires = [c for c in [col_energie, col_ges, col_date] + colonnes_distinction if c]
    autres_colonnes = [c for c in dpe.columns if c not in colonnes_prioritaires]
    return dpe[colonnes_prioritaires + autres_colonnes], col_energie



    """
    Réorganise le tableau DPE brut en mettant en premier les colonnes
    essentielles pour distinguer un logement d'un autre dans un immeuble
    collectif : classe énergie, classe GES, date du DPE, puis tout champ
    de distinction du logement (étage, complément d'adresse...) — le reste
    des colonnes brutes suit, inchangé. Ne renomme ni ne supprime aucune
    colonne d'origine, se contente de réordonner pour la lisibilité — un
    seul tableau plutôt qu'un résumé séparé du détail brut, pour que la
    ligne d'un logement dans le résumé corresponde visuellement à la même
    ligne dans le détail.

    Retourne (tableau réordonné, nom de la colonne classe énergie) — le
    second élément permet à l'appelant d'appliquer une couleur de fond sur
    cette colonne précisément, sans avoir à redeviner son nom.
    """
    if dpe is None or dpe.empty:
        return dpe, None

    candidats_energie = ["etiquette_dpe", "classe_consommation_energie", "etiquette_dpe_final"]
    candidats_ges = ["etiquette_ges", "classe_estimation_ges", "etiquette_ges_final"]
    candidats_date = ["date_etablissement_dpe", "date_reception_dpe", "date_visite_diagnostiqueur"]
    MOTS_CLES_DISTINCTION = [
        "complement", "etage", "appartement", "logement", "cage",
        "escalier", "porte", "batiment", "lot",
    ]

    col_energie = next((c for c in candidats_energie if c in dpe.columns), None)
    col_ges = next((c for c in candidats_ges if c in dpe.columns), None)
    col_date = next((c for c in candidats_date if c in dpe.columns), None)
    deja_prioritaires = {col_energie, col_ges, col_date}
    colonnes_distinction = [
        c for c in dpe.columns
        if any(mot in c.lower() for mot in MOTS_CLES_DISTINCTION)
        and c not in ("nombre_appartement",)
        and c not in deja_prioritaires
    ]

    colonnes_prioritaires = [c for c in [col_energie, col_ges, col_date] + colonnes_distinction if c]
    autres_colonnes = [c for c in dpe.columns if c not in colonnes_prioritaires]
    return dpe[colonnes_prioritaires + autres_colonnes], col_energie


BDNB_API_URL = "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet/bbox"


DIDO_API_BASE = "https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1"
SITADEL_RID_LOGEMENTS = "8b35affb-55fc-4c1f-915b-7750f974446a"
SITADEL_RID_LOCAUX = "f8f0700f-806c-40a7-83b1-f21cf507e7c4"


def find_ecoles_proches(
    lat: float, lon: float, code_postal: str | None, rayon_m: float = 2000,
) -> pd.DataFrame | None:
    """
    Cherche les établissements scolaires (premier et second degré, publics
    et privés) les plus proches d'un point, via l'Annuaire de l'Éducation
    nationale (API publique, sans authentification) — 66 000+
    établissements géolocalisés.

    Schéma confirmé par deux sources indépendantes réelles (atelier
    officiel type SSPHub/INSEE, intégration Grist en production) le
    22/07/2026 — pas testé en direct depuis cet environnement (pas d'accès
    réseau), mais champs corroborés deux fois séparément :
    code_postal, nom_commune, latitude/longitude (en WGS84 direct, PAS en
    Lambert93 contrairement à la BDNB), type_etablissement, libelle_nature,
    statut_public_prive.

    Filtre d'abord par code postal côté serveur (réduit à quelques dizaines
    d'établissements, pas les 66 000 de toute la France), puis calcule la
    distance réelle à chacun côté client — même logique que pour les ventes
    comparables (find_comparables) — pour ne garder que les plus proches.
    Un code postal peut chevaucher plusieurs communes en zone urbaine dense
    (ou une commune plusieurs codes postaux) : approximation à affiner si
    besoin, comme pour les autres filtrages géographiques de ce projet.
    """
    import requests

    if not code_postal:
        return None

    try:
        resp = requests.get(
            "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
            "fr-en-annuaire-education/records",
            params={
                "where": f'code_postal="{code_postal}"',
                "select": (
                    "nom_etablissement,type_etablissement,libelle_nature,"
                    "statut_public_prive,adresse_1,code_postal,nom_commune,"
                    "latitude,longitude"
                ),
                "limit": 100,
            },
            timeout=15,
        )
        resp.raise_for_status()
        records = resp.json().get("results", [])
    except Exception as exc:
        print(f"[warn] Annuaire éducation échoué pour code_postal={code_postal} : {exc}")
        return None

    if not records:
        return None

    lignes = []
    for r in records:
        r_lat, r_lon = r.get("latitude"), r.get("longitude")
        if r_lat is None or r_lon is None:
            continue
        d = haversine_m(lat, lon, float(r_lat), float(r_lon))
        if d <= rayon_m:
            r["distance_m"] = round(d)
            lignes.append(r)

    if not lignes:
        return None
    return pd.DataFrame(lignes).sort_values("distance_m").reset_index(drop=True)



def find_permis_urbanisme(code_insee: str, section: str, numero_parcelle: str) -> pd.DataFrame | None:
    """
    Cherche les permis de construire/démolir/aménager et déclarations
    préalables (base Sitadel, TYPE_DAU parmi PC/DP/PA/PD) connus pour une
    parcelle cadastrale précise, via l'API publique DiDo du SDES (gratuite,
    sans authentification — confirmée en conditions réelles le 20/07/2026).

    Contrairement au DVF/BDNB, ici la recherche se fait DIRECTEMENT par
    section + numéro de parcelle cadastrale (`SEC_CADASTRE1`/`NUM_CADASTRE1`,
    filtre `eq` confirmé disponible) — pas de recherche par texte d'adresse
    à corriger pour les abréviations ou les accents, la parcelle suffit.
    Réutilise `known_parcelle_ids` (déjà calculé de façon fiable via le DVF
    exact — voir find_property_history) sans nouvelle logique de correspondance.

    Interroge les deux jeux de données qui couvrent, à eux deux, tous les
    types de permis (les PC/DP/PA/PD ne sont PAS des fichiers séparés, ils
    sont distingués par la colonne TYPE_DAU au sein de ces deux fichiers) :
    - permis créant des logements (rid SITADEL_RID_LOGEMENTS)
    - permis créant des locaux non résidentiels (rid SITADEL_RID_LOCAUX)

    Ne précise pas de `millesime` dans l'URL : la doc DiDo confirme que le
    dernier millésime disponible est utilisé par défaut, donc toujours à
    jour sans avoir à gérer un cycle de rafraîchissement nous-mêmes.

    LIMITE DE PÉRIMÈTRE CONFIRMÉE (méthodologie officielle SDES, vérifiée le
    20/07/2026) : cet open data EXCLUT volontairement toute demande ne
    créant aucune surface de plancher — une simple déclaration préalable
    (ex. ouverture de fenêtres, ravalement) n'y figurera JAMAIS, même si
    elle existe réellement en mairie. Par ailleurs, les permis de démolir
    (PD), bien qu'enregistrés dans Sitadel, "ne sont pas statistiquement
    exploités et ne font l'objet d'aucune diffusion au niveau agrégé" selon
    le SDES lui-même — leur présence dans cette source n'est donc pas
    garantie même quand ils existent réellement. Une absence de résultat ne
    doit jamais être présentée comme une absence réelle de permis.

    AUTRE LIMITE CONFIRMÉE, avec impact concret constaté (1 Impasse
    Blanchard, Créteil — immeuble neuf de 40 logements, aucun permis
    retrouvé par parcelle exacte) : "les parcelles renseignées peuvent
    correspondre à d'anciennes parcelles aujourd'hui disparues (division
    par exemple...)" (SDSIG). Pour une construction neuve, le permis est
    déposé AVANT le chantier, sur la parcelle telle qu'elle existait alors
    — qui peut être redécoupée après construction, avant la vente qui nous
    donne la parcelle actuelle via le DVF. La recherche essaie donc, dans
    l'ordre : la parcelle exacte sur chacun des 3 emplacements possibles
    (un dossier Sitadel référence 1 à 3 parcelles), puis, si rien ne
    correspond, TOUTE LA SECTION cadastrale (sans le numéro), pour capter
    un ancien découpage — ces résultats élargis sont signalés comme
    approximatifs (colonne `correspondance_approximative`), jamais présentés
    comme une correspondance certaine.
    """
    import requests

    def _interroger(params_supplementaires):
        resultats_partiels = []
        for rid, categorie in [
            (SITADEL_RID_LOGEMENTS, "Logements"),
            (SITADEL_RID_LOCAUX, "Locaux non résidentiels"),
        ]:
            try:
                resp = requests.get(
                    f"{DIDO_API_BASE}/datafiles/{rid}/json",
                    params={"COMM": f"eq:{code_insee}", **params_supplementaires},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                lignes = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(lignes, list) and lignes:
                    for ligne in lignes:
                        ligne["categorie_sitadel"] = categorie
                    resultats_partiels.extend(lignes)
            except Exception as exc:
                print(f"[warn] Sitadel ({categorie}) échoué pour {code_insee} : {exc}")
                continue
        return resultats_partiels

    # 1. Parcelle exacte, sur chacun des 3 emplacements possibles (un
    # dossier Sitadel peut référencer jusqu'à 3 parcelles).
    for n in (1, 2, 3):
        resultats = _interroger({
            f"SEC_CADASTRE{n}": f"eq:{section}",
            f"NUM_CADASTRE{n}": f"eq:{numero_parcelle}",
        })
        if resultats:
            for r in resultats:
                r["correspondance_approximative"] = False
            return pd.json_normalize(resultats)

    # 2. Repli : toute la section cadastrale (numéro non garanti stable en
    # cas de redécoupage) — signalé comme approximatif, jamais silencieux.
    resultats = _interroger({"SEC_CADASTRE1": f"eq:{section}"})
    if resultats:
        for r in resultats:
            r["correspondance_approximative"] = True
        return pd.json_normalize(resultats)

    return None


def get_batiment_bdnb(
    address: str, code_insee: str | None, id_parcelle_connue: str | None = None,
) -> dict | None:
    """
    Récupère la carte d'identité du bâtiment via l'API BDNB (Base de Données
    Nationale des Bâtiments, CSTB) — gratuite, sans clé.

    `id_parcelle_connue` (l'identifiant DVF 14 caractères, si une
    correspondance DVF exacte existe pour l'adresse — voir
    find_property_history) est utilisé en PRIORITÉ ABSOLUE sur la
    correspondance par texte d'adresse : un immeuble d'angle peut avoir DEUX
    adresses valides (ex. "38 avenue Sainte-Marie" ET "52 avenue de
    Ceinture" pour le même bien, à Créteil, confirmé en conditions réelles
    le 20/07/2026) — le DVF les fait correctement pointer vers la même
    mutation, mais la BDNB peut avoir DEUX fiches bâtiment distinctes (l'une
    pour chaque adresse), sans lien entre elles pour l'une des deux. Chercher
    par texte d'adresse retombe alors sur la mauvaise fiche selon l'adresse
    tapée. La parcelle cadastrale, elle, est la même des deux côtés — la
    recherche par `l_parcelle_id` (champ exposé par la BDNB) lève donc
    l'ambiguïté avec certitude, quelle que soit l'adresse utilisée pour la
    recherche. Repli sur la correspondance par texte si aucune parcelle
    n'est fournie, ou si la BDNB ne la reconnaît pas.

    Confirmé en conditions réelles (millésime 2026-02.a, testé le
    19/07/2026) :
    - l'ancien chemin `/bbox` documenté en 2024 n'existe plus dans le schéma
      actuel (erreur PGRST202) — l'API a changé de structure depuis
    - sa géométrie (`geom_groupe`) est en Lambert93 (EPSG:2154), pas en
      latitude/longitude WGS84 : une recherche par proximité GPS directe
      n'est de toute façon pas possible sans reprojection
    - **10 résultats semble être un plafond serveur strict, quel que soit
      le filtre appliqué** — le filtre pousse donc côté serveur le numéro ET
      le mot le plus distinctif du nom de rue, pour rester sous ce plafond.
    - Plusieurs bâtiments distincts peuvent revendiquer la même adresse
      texte (bâtiment d'angle la listant en secondaire, en plus de sa
      propre adresse principale sur l'autre rue ; ou plusieurs entrées
      d'une même résidence) — tous les candidats correspondants sont donc
      renvoyés, pas seulement le "meilleur", pour ne pas perdre cette
      information (composition d'un ensemble immobilier, bâtiments voisins
      partageant le numéro...).

    Retourne un dict avec :
    - les champs du "meilleur" candidat (celui qui a une année de
      construction renseignée si un tel candidat existe, sinon le premier
      trouvé), directement accessibles comme avant (annee_construction,
      identifiant_bdnb...) pour ne pas casser le code appelant existant
    - `candidats` : la liste COMPLÈTE des bâtiments correspondants trouvés
      (chacun avec les mêmes champs), y compris ceux non retenus comme
      "meilleur" — utile pour montrer les bâtiments voisins/liés plutôt que
      les ignorer silencieusement

    Le numéro est ancré en DÉBUT de chaîne dans le filtre serveur
    (`ilike.{numero}*...`, sans `*` de tête) plutôt qu'en recherche libre :
    un numéro court comme "9" en recherche libre (`*9*`) matcherait aussi
    "39", "19", "90"... et peut à lui seul épuiser le plafond de 10
    résultats avec de faux positifs, noyant le vrai numéro recherché. Le
    format BAN commence toujours par le numéro, donc l'ancrage est sûr.

    Si le numéro exact ne donne aucun résultat, un repli tente les numéros
    voisins de la même rue (±2, ±4, ±6, ±8, ±10) : une résidence peut être
    enregistrée sous une adresse BAN/BDNB principale couvrant plusieurs
    numéros (constaté en conditions réelles : "Les Rives de Marne", 8 Quai
    Bir-Hakeim à Saint-Maurice, va en réalité du n°2 au n°10 sous une même
    entrée). Le résultat indique alors `numero_approximatif=True` et
    `numero_trouve` différent de `numero_recherche` — à l'appelant de
    l'afficher clairement comme approximatif plutôt que comme une
    correspondance exacte.
    """
    import requests

    MOTS_GENERIQUES_BDNB = {
        "rue", "avenue", "boulevard", "chemin", "impasse", "allee", "place",
        "square", "route", "sentier", "quai", "cours", "villa", "cite",
        "passage", "voie", "chaussee",
    }

    CHAMPS_UTILES_BDNB = [
        "batiment_groupe_id", "annee_construction",
        "libelle_adr_principale_ban", "l_libelle_adr", "l_parcelle_id",
        "nb_log", "nb_niveau", "hauteur_mean", "mat_mur_txt", "mat_toit_txt",
        "alea_argile", "usage_principal_bdnb_open",
        "denomination_monument_historique", "distance_monument_historique",
        "contrainte_urbanisme_ac1", "zone_plu_bati_patrimonial",
        "quartier_prioritaire", "nom_qp",
        "batenr_favorabilite_solaire_thermique",
        "batenr_potentiel_prod_solaire_thermique_annuelle",
        "valeur_fonciere_m2_residentiel_rel_commune",
        "surface_emprise_sol",
    ]

    # Équivalences d'abréviations administratives françaises courantes : la
    # BAN/BDNB et le DVF n'utilisent pas toujours la même forme pour le même
    # mot (ex. Saint-Maurice liste déjà "MAL DE LATTRE DE TASSIGNY" — Mal
    # pour Maréchal — dans le DVF lui-même). Sans cette tolérance, une seule
    # forme différente entre les deux sources bloque toute correspondance,
    # même avec le bon numéro et la bonne rue par ailleurs.
    EQUIVALENCES_ABREVIATIONS = {
        "general": "gal", "gal": "general",
        "marechal": "mal", "mal": "marechal",
        "saint": "st", "st": "saint",
        "sainte": "ste", "ste": "sainte",
    }

    def _tokens_correspondent(tokens_recherches, rue_candidate):
        return all(
            t in rue_candidate or EQUIVALENCES_ABREVIATIONS.get(t, "") in rue_candidate
            for t in tokens_recherches
        )

    if not code_insee:
        return None
    target_numero, target_rue = _parse_address_number_street(address)
    if not target_numero or not target_rue:
        return None
    rue_tokens = [t for t in target_rue.split() if len(t) > 2]
    if not rue_tokens:
        return None
    tokens_distinctifs = [t for t in rue_tokens if t not in MOTS_GENERIQUES_BDNB] or rue_tokens

    # `ilike` sur PostgREST/Postgres est insensible à la casse mais PAS aux
    # accents ("belvedere" ne matche jamais "Belvédère" côté serveur), alors
    # que notre normalisation (côté recherche) retire les accents. On essaie
    # donc aussi la forme brute (accentuée) de chaque mot pivot, retrouvée
    # dans l'adresse d'origine, en plus de sa forme normalisée.
    import re as _re_bdnb
    mots_bruts = _re_bdnb.findall(r"[^\s,]+", address)

    def _forme_brute(mot_normalise):
        for w in mots_bruts:
            if _normalize_text(w) == mot_normalise:
                return w
        return mot_normalise

    # Essaie chaque mot distinctif comme pivot de recherche serveur, du plus
    # long au plus court, jusqu'à trouver un candidat — utile si le premier
    # mot choisi n'existe pas sous cette forme dans la BDNB (abréviation
    # différente) alors qu'un autre mot de la même rue, lui, y figure bien.
    pivots_a_essayer = []
    for p in sorted(set(tokens_distinctifs), key=len, reverse=True):
        pivots_a_essayer.append(p)
        brut = _forme_brute(p)
        if brut.lower() != p:
            pivots_a_essayer.append(brut)

    def _chercher_pour_numero(numero_a_chercher):
        """Cherche un bâtiment pour un numéro précis sur cette rue, en
        essayant chaque mot pivot (et sa forme accentuée) jusqu'à trouver
        des candidats correspondants."""
        for mot_pivot in pivots_a_essayer:
            resp = requests.get(
                "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet",
                params={
                    "code_commune_insee": f"eq.{code_insee}",
                    "libelle_adr_principale_ban": f"ilike.{numero_a_chercher}*{mot_pivot}*",
                    "select": ",".join(CHAMPS_UTILES_BDNB),
                    "limit": 200,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                continue

            candidats = []
            for r in results:
                adresses = list(r.get("l_libelle_adr") or [])
                if r.get("libelle_adr_principale_ban"):
                    adresses.append(r["libelle_adr_principale_ban"])
                for adr in adresses:
                    num, rue = _parse_address_number_street(adr)
                    if num == numero_a_chercher and _tokens_correspondent(rue_tokens, rue):
                        candidats.append(r)
                        break  # inutile de vérifier les autres adresses de CE bâtiment
            if candidats:
                return candidats
        return []

    try:
        candidats = []
        numero_trouve = target_numero

        # Priorité absolue : si on a la parcelle DVF confirmée pour cette
        # adresse, chercher directement par parcelle lève toute ambiguïté
        # d'adresse (immeuble d'angle à deux adresses valides, etc.) — voir
        # docstring. `cs` est l'opérateur PostgREST "contient" pour un champ
        # tableau ; non garanti si `l_parcelle_id` n'est pas un vrai tableau
        # Postgres côté BDNB, d'où la bascule sur le texte en cas d'échec.
        if id_parcelle_connue:
            try:
                resp_parcelle = requests.get(
                    "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet",
                    params={
                        "code_commune_insee": f"eq.{code_insee}",
                        "l_parcelle_id": f"cs.{{{id_parcelle_connue}}}",
                        "select": ",".join(CHAMPS_UTILES_BDNB),
                        "limit": 200,
                    },
                    timeout=15,
                )
                resp_parcelle.raise_for_status()
                candidats_parcelle = resp_parcelle.json()
                if isinstance(candidats_parcelle, list) and candidats_parcelle:
                    candidats = candidats_parcelle
            except Exception:
                pass  # on retombe silencieusement sur la recherche par texte

        if not candidats:
            candidats = _chercher_pour_numero(target_numero)
            trouve_par_parcelle = False
        else:
            trouve_par_parcelle = True

        # Repli sur les numéros voisins de la même rue si le numéro exact ne
        # donne rien : une résidence peut couvrir plusieurs numéros sous une
        # seule adresse BAN/BDNB principale (constaté en conditions réelles :
        # "Les Rives de Marne", 8 Quai Bir-Hakeim, Saint-Maurice, qui va en
        # réalité du n°2 au n°10 sous une même entrée). On ne retourne alors
        # PAS le numéro exact — le résultat est clairement signalé comme
        # approximatif (voir `numero_approximatif` dans le retour), à
        # l'appelant de décider s'il l'affiche et comment.
        if not candidats and target_numero.isdigit():
            n = int(target_numero)
            for ecart in (2, 4, 6, 8, 10):
                for essai in (n - ecart, n + ecart):
                    if essai <= 0:
                        continue
                    candidats = _chercher_pour_numero(str(essai))
                    if candidats:
                        numero_trouve = str(essai)
                        break
                if candidats:
                    break

        if not candidats:
            return None

        # Plusieurs bâtiments peuvent revendiquer la même adresse texte (cas
        # fréquent : un bâtiment d'angle la liste en adresse secondaire, en
        # plus de sa propre adresse principale sur l'autre rue). Si le
        # premier candidat trouvé n'a pas d'année renseignée mais qu'un
        # AUTRE candidat correspondant en a une, celle-ci est plus utile à
        # afficher — un `null` ne veut dire "aucune adresse ne correspond
        # à une année connue" que si AUCUN candidat n'en a.
        meilleur = next((c for c in candidats if c.get("annee_construction")), candidats[0])
        return {
            "annee_construction": meilleur.get("annee_construction"),
            "identifiant_bdnb": meilleur.get("batiment_groupe_id"),
            "brut": meilleur,  # gardé pour inspection/diagnostic si besoin
            "candidats": candidats,  # tous les bâtiments correspondants, meilleur inclus
            "numero_recherche": target_numero,
            "numero_trouve": numero_trouve,
            "numero_approximatif": numero_trouve != target_numero,
            "trouve_par_parcelle": trouve_par_parcelle,
        }
    except Exception as exc:
        print(f"[warn] BDNB échoué pour code_insee={code_insee} : {exc}")
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
