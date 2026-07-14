#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ImmoScan France — Application Streamlit
=======================================
Prototype de détection d'opportunités immobilières sous-évaluées,
basé sur les transactions DVF, avec géolocalisation, historique probable,
comparables, DPE et vues cartographiques.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    from st_address_search import address_search_component
    CUSTOM_SEARCH_AVAILABLE = True
    CUSTOM_SEARCH_ERROR = None
except Exception as _e:
    CUSTOM_SEARCH_AVAILABLE = False
    CUSTOM_SEARCH_ERROR = str(_e)
    print(f"[warn] Composant address_search indisponible : {_e}")

sys.path.insert(0, str(Path(__file__).parent))
import immo_scan as core  # noqa: E402


st.set_page_config(page_title="ImmoScan France", page_icon="🏠", layout="wide")

DEPARTEMENTS_FRANCE = {
    "01 - Ain": "01", "02 - Aisne": "02", "03 - Allier": "03", "04 - Alpes-de-Haute-Provence": "04",
    "05 - Hautes-Alpes": "05", "06 - Alpes-Maritimes": "06", "07 - Ardèche": "07", "08 - Ardennes": "08",
    "09 - Ariège": "09", "10 - Aube": "10", "11 - Aude": "11", "12 - Aveyron": "12", "13 - Bouches-du-Rhône": "13",
    "14 - Calvados": "14", "15 - Cantal": "15", "16 - Charente": "16", "17 - Charente-Maritime": "17",
    "18 - Cher": "18", "19 - Corrèze": "19", "2A - Corse-du-Sud": "2A", "2B - Haute-Corse": "2B",
    "21 - Côte-d'Or": "21", "22 - Côtes-d'Armor": "22", "23 - Creuse": "23", "24 - Dordogne": "24",
    "25 - Doubs": "25", "26 - Drôme": "26", "27 - Eure": "27", "28 - Eure-et-Loir": "28",
    "29 - Finistère": "29", "30 - Gard": "30", "31 - Haute-Garonne": "31", "32 - Gers": "32",
    "33 - Gironde": "33", "34 - Hérault": "34", "35 - Ille-et-Vilaine": "35", "36 - Indre": "36",
    "37 - Indre-et-Loire": "37", "38 - Isère": "38", "39 - Jura": "39", "40 - Landes": "40",
    "41 - Loir-et-Cher": "41", "42 - Loire": "42", "43 - Haute-Loire": "43", "44 - Loire-Atlantique": "44",
    "45 - Loiret": "45", "46 - Lot": "46", "47 - Lot-et-Garonne": "47", "48 - Lozère": "48",
    "49 - Maine-et-Loire": "49", "50 - Manche": "50", "51 - Marne": "51", "52 - Haute-Marne": "52",
    "53 - Mayenne": "53", "54 - Meurthe-et-Moselle": "54", "55 - Meuse": "55", "56 - Morbihan": "56",
    "57 - Moselle": "57", "58 - Nièvre": "58", "59 - Nord": "59", "60 - Oise": "60",
    "61 - Orne": "61", "62 - Pas-de-Calais": "62", "63 - Puy-de-Dôme": "63", "64 - Pyrénées-Atlantiques": "64",
    "65 - Hautes-Pyrénées": "65", "66 - Pyrénées-Orientales": "66", "67 - Bas-Rhin": "67", "68 - Haut-Rhin": "68",
    "69 - Rhône": "69", "70 - Haute-Saône": "70", "71 - Saône-et-Loire": "71", "72 - Sarthe": "72",
    "73 - Savoie": "73", "74 - Haute-Savoie": "74", "75 - Paris": "75", "76 - Seine-Maritime": "76",
    "77 - Seine-et-Marne": "77", "78 - Yvelines": "78", "79 - Deux-Sèvres": "79", "80 - Somme": "80",
    "81 - Tarn": "81", "82 - Tarn-et-Garonne": "82", "83 - Var": "83", "84 - Vaucluse": "84",
    "85 - Vendée": "85", "86 - Vienne": "86", "87 - Haute-Vienne": "87", "88 - Vosges": "88",
    "89 - Yonne": "89", "90 - Territoire de Belfort": "90", "91 - Essonne": "91", "92 - Hauts-de-Seine": "92",
    "93 - Seine-Saint-Denis": "93", "94 - Val-de-Marne": "94", "95 - Val-d'Oise": "95",
    "971 - Guadeloupe": "971", "972 - Martinique": "972", "973 - Guyane": "973", "974 - La Réunion": "974", "976 - Mayotte": "976",
}

ANNEES_DISPONIBLES = [2021, 2022, 2023, 2024, 2025]


@st.cache_data(show_spinner=False)
def load_reference(dept: str):
    ref_path = core.OUTPUT_DIR / f"reference_{dept}.csv"
    trend_path = core.OUTPUT_DIR / f"tendance_{dept}.csv"
    ref = pd.read_csv(ref_path) if ref_path.exists() else None
    trend = pd.read_csv(trend_path) if trend_path.exists() else None
    return ref, trend


def reference_exists(dept: str) -> bool:
    return (core.OUTPUT_DIR / f"reference_{dept}.csv").exists()


def render_geo_views(lat: float, lon: float, radius_m: float | None = None):
    t1, t2, t3, t4 = st.tabs([
        "🗺️ Carte géolocalisation", "📐 Cadastre", "🌍 Vue Google Earth", "🚶 Vue Google Street",
    ])

    with t1:
        try:
            import folium
            if radius_m:
                m = folium.Map(location=[lat, lon], tiles="OpenStreetMap")
            else:
                m = folium.Map(location=[lat, lon], zoom_start=17, tiles="OpenStreetMap")
            folium.Marker(
                [lat, lon], tooltip="Adresse recherchée",
                icon=folium.Icon(color="red", icon="home", prefix="fa"),
            ).add_to(m)
            if radius_m:
                folium.Circle(
                    [lat, lon], radius=radius_m, color="#dc2626", weight=2,
                    fill=True, fill_opacity=0.10,
                    tooltip=f"Rayon comparables : {int(radius_m)} m",
                ).add_to(m)
                # On cadre la vue pour que tout le cercle soit visible, plutôt
                # qu'un zoom fixe qui le coupait pour les grands rayons.
                from math import cos, radians
                delta_lat = radius_m / 111_320
                delta_lon = radius_m / (111_320 * max(cos(radians(lat)), 0.1))
                m.fit_bounds([
                    [lat - delta_lat, lon - delta_lon],
                    [lat + delta_lat, lon + delta_lon],
                ])
            components.html(m._repr_html_(), height=440)
            if radius_m:
                st.caption(f"Le cercle rouge représente le rayon de {int(radius_m)} m utilisé pour les comparables.")
        except Exception as exc:
            st.warning(f"Carte indisponible ({exc}) — utilisez le lien Google Maps ci-dessous.")
        st.link_button("Ouvrir dans Google Maps", core.google_maps_url(lat, lon), use_container_width=True)

    with t2:
        try:
            import folium
            mc = folium.Map(location=[lat, lon], zoom_start=19, tiles=None)
            folium.TileLayer(
                tiles=(
                    "https://data.geopf.fr/wmts?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile"
                    "&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM"
                    "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg"
                ),
                attr="IGN-F/Géoportail", name="Photos aériennes", overlay=False,
            ).add_to(mc)
            folium.TileLayer(
                tiles=(
                    "https://data.geopf.fr/wmts?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile"
                    "&LAYER=CADASTRALPARCELS.PARCELLAIRE_EXPRESS&STYLE=PCI vecteur"
                    "&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
                ),
                attr="IGN-F/Géoportail — Cadastre", name="Parcelles cadastrales",
                overlay=True, opacity=0.9,
            ).add_to(mc)
            folium.Marker([lat, lon], tooltip="Adresse recherchée",
                          icon=folium.Icon(color="red", icon="home", prefix="fa")).add_to(mc)
            components.html(mc._repr_html_(), height=440)
            st.caption(
                "Couche cadastrale officielle IGN sur fond de photo aérienne "
                "(numéros de parcelle visibles en zoomant). Le rendu diffère "
                "visuellement de cadastre.gouv.fr (dont l'intégration est "
                "bloquée par le site lui-même), mais la donnée est la même."
            )
        except Exception as exc:
            st.warning(f"Vue cadastre indisponible ({exc}).")
        cadastre_url = f"https://www.cadastre.gouv.fr/scpc/rechercherPlan.do?lat={lat}&lon={lon}"
        st.link_button("Ouvrir le plan cadastral officiel (cadastre.gouv.fr)", cadastre_url, use_container_width=True)

    with t3:
        earth = core.google_earth_url(lat, lon)
        satellite = f"https://maps.google.com/maps?q={lat},{lon}&t=k&z=18&output=embed"
        components.html(
            f'<iframe src="{satellite}" width="100%" height="420" style="border:0;" loading="lazy"></iframe>',
            height=440,
        )
        st.link_button("Ouvrir dans Google Earth", earth, use_container_width=True)

    with t4:
        street = core.google_street_view_url(lat, lon)
        street_embed = f"https://maps.google.com/maps?q=&layer=c&cbll={lat},{lon}&cbp=12,0,0,0,0&output=svembed"
        components.html(
            f'<iframe src="{street_embed}" width="100%" height="420" style="border:0;" loading="lazy"></iframe>',
            height=440,
        )
        st.link_button("Ouvrir dans Google Street View", street, use_container_width=True)


st.sidebar.title("🏠 ImmoScan France")
st.sidebar.caption("DVF · DPE · comparables · historique probable")

default_index = list(DEPARTEMENTS_FRANCE.values()).index("94")
dept_label = st.sidebar.selectbox("Département de travail", list(DEPARTEMENTS_FRANCE.keys()), index=default_index)
dept = DEPARTEMENTS_FRANCE[dept_label]

with st.sidebar.expander("Options avancées"):
    annee_min, annee_max = st.slider(
        "Années DVF à utiliser (plage)",
        min_value=min(ANNEES_DISPONIBLES), max_value=max(ANNEES_DISPONIBLES),
        value=(min(ANNEES_DISPONIBLES), max(ANNEES_DISPONIBLES)),
        help=(
            f"Plage réellement disponible auprès de la source DVF utilisée : "
            f"{min(ANNEES_DISPONIBLES)}-{max(ANNEES_DISPONIBLES)} (au-delà, une "
            "autre source type Cerema DVF+ serait nécessaire). Détermine les "
            "données disponibles pour TOUT le reste de l'app : l'historique du "
            "bien les utilise toutes, et le curseur 'dernières N années' des "
            "comparables ne peut pas dépasser cette plage. Pour toute la France, "
            "travaillez département par département pour éviter des "
            "téléchargements très lourds."
        ),
    )
    annees = list(range(annee_min, annee_max + 1))
    force_refresh = st.button("🔄 Forcer un nouveau téléchargement + recalcul", use_container_width=True)

    st.divider()
    st.markdown("**Historique complémentaire 2014-2020 (Cerema DVF+)**")

    regional_files = sorted(core.CEREMA_BUNDLED_DIR.glob("cerema_dvfplus_region_*.csv.gz"))
    regional_parts = sorted(core.CEREMA_BUNDLED_DIR.glob("cerema_dvfplus_region_*.csv.gz.part*"))
    bundled_dept_exists = (core.CEREMA_BUNDLED_DIR / f"cerema_dvfplus_{dept}.csv").exists()
    uploaded_exists = (core.OUTPUT_DIR / f"cerema_dvfplus_{dept}.csv").exists()
    bundled_exists = bool(regional_files) or bool(regional_parts) or bundled_dept_exists

    if bundled_exists:
        if regional_files:
            noms = ", ".join(f.name for f in regional_files)
            st.success(
                f"✅ Historique Cerema DVF+ intégré en permanence au dépôt via "
                f"un fichier régional ({noms}) — couvre potentiellement "
                "plusieurs départements, filtré automatiquement pour le "
                f"{dept}. Survit aux redémarrages."
            )
        elif regional_parts:
            nb_bases = len(set(p.name.split(".part")[0] for p in regional_parts))
            st.success(
                f"✅ Historique Cerema DVF+ intégré en permanence au dépôt via "
                f"{len(regional_parts)} morceau(x) régional(aux) découpé(s) "
                f"({nb_bases} fichier(s) recollé(s) automatiquement) — filtré "
                f"pour le {dept}. Survit aux redémarrages."
            )
        else:
            st.success(
                f"✅ Historique Cerema DVF+ intégré en permanence au dépôt pour le "
                f"{dept} (fichier `cerema_data/cerema_dvfplus_{dept}.csv`) — "
                "survit aux redémarrages, pas besoin de le réimporter."
            )
    else:
        st.caption(
            "Source : Cerema, DVF+ open-data (Licence Ouverte v2.0, Etalab) — "
            "https://datafoncier.cerema.fr/donnees/autres-donnees-foncieres/dvfplus-open-data. "
            "Téléchargement manuel requis (fichiers distribués en archives ZIP, "
            "pas d'URL directe automatisable) : rendez-vous sur "
            "cerema.app.box.com/v/dvfplus-opendata, téléchargez l'archive de "
            "votre région, puis déposez-la ci-dessous."
        )
        st.info(
            "💡 **Astuce pour éviter de réimporter à chaque redéploiement** : "
            "une fois importé ci-dessous, téléchargez le fichier généré dans "
            "`output/` et déposez-le directement dans un dossier "
            "`cerema_data/` de votre dépôt GitHub — l'app le détecte alors "
            "automatiquement de façon permanente, sans jamais avoir besoin "
            "de le réimporter. **L'option combinée (recommandée) ne "
            "génère qu'un seul fichier compressé pour toute la région**, "
            "plus simple à gérer qu'un fichier par département."
        )
        cerema_zip = st.file_uploader(
            "Archive ZIP Cerema DVF+", type=["zip"], key="cerema_zip_upload",
            help="Les archives régionales (plusieurs départements dans un seul "
                 "fichier, comme distribuées par Cerema) peuvent peser plusieurs "
                 "centaines de Mo — la limite d'upload est fixée à 1 Go "
                 "(voir .streamlit/config.toml).",
        )
        if cerema_zip is not None:
            tmp_path = core.OUTPUT_DIR / "_tmp_cerema_upload.zip"
            core.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(cerema_zip.getvalue())
            try:
                depts_detectes = core.list_departements_in_zip(str(tmp_path))
            except Exception:
                depts_detectes = []

            if depts_detectes:
                st.caption(
                    f"📦 {len(depts_detectes)} département(s) détecté(s) dans "
                    f"cette archive : {', '.join(depts_detectes)}."
                )

            region_name = st.text_input(
                "Nom court pour cette région (pour nommer le fichier)",
                value="idf", key="cerema_region_name",
                help="Utilisé dans le nom du fichier généré : "
                     "cerema_dvfplus_region_{nom}.csv.gz",
            )

            if st.button(
                "⭐ Importer toute la région en 1 fichier compressé (recommandé)",
                key="cerema_import_region_combined_button", type="primary",
                use_container_width=True,
            ):
                status_box = st.status("Import régional combiné en cours...", expanded=True)
                try:
                    msg = core.import_cerema_dvfplus_region_combined(
                        str(tmp_path), region_name=region_name, progress_callback=status_box.write
                    )
                    status_box.update(label="✅ Import régional combiné terminé", state="complete")
                    st.success(msg)
                except SystemExit as e:
                    status_box.update(label="Erreur", state="error")
                    st.error(str(e))

            with st.expander("Autres options d'import (un fichier par département)"):
                col_dept, col_region = st.columns(2)
                with col_dept:
                    if st.button(f"Importer seulement le {dept}", key="cerema_import_button"):
                        with st.spinner(f"Import Cerema DVF+ pour le {dept} en cours..."):
                            try:
                                msg = core.import_cerema_dvfplus(str(tmp_path), dept)
                                st.success(msg)
                            except SystemExit as e:
                                st.error(str(e))
                with col_region:
                    if st.button("Importer toute la région (fichiers séparés)", key="cerema_import_region_button"):
                        status_box = st.status("Import de la région en cours...", expanded=True)
                        try:
                            msg = core.import_cerema_dvfplus_region(
                                str(tmp_path), progress_callback=status_box.write
                            )
                            status_box.update(label="✅ Import régional terminé", state="complete")
                            st.success(msg)
                        except SystemExit as e:
                            status_box.update(label="Erreur", state="error")
                            st.error(str(e))
            tmp_path.unlink(missing_ok=True)

        if uploaded_exists:
            st.caption(
                f"✅ Historique Cerema DVF+ importé pour le {dept} pour cette "
                "session (sera perdu au prochain redémarrage de l'app — voir "
                "l'astuce ci-dessus pour le rendre permanent)."
            )

st.sidebar.divider()
st.sidebar.markdown("**Préparation des données**")

if force_refresh:
    with st.sidebar.status(f"Retéléchargement forcé pour le {dept}...", expanded=True) as status_box:
        try:
            core.prepare_data_if_needed(dept, annees, force=True, progress_callback=status_box.write)
            load_reference.clear()
            status_box.update(label="✅ Données actualisées", state="complete")
        except SystemExit as e:
            status_box.update(label="Erreur", state="error")
            st.sidebar.error(str(e))
elif core.reference_is_up_to_date(dept, annees):
    reference_bundled = (core.REFERENCE_BUNDLED_DIR / f"reference_{dept}.csv").exists()
    if reference_bundled:
        st.sidebar.success(
            f"✅ Référence à jour pour le {dept} — intégrée en permanence au "
            "dépôt, pas de nouveau téléchargement au prochain démarrage."
        )
    else:
        st.sidebar.warning(
            f"⚠️ Référence à jour pour le {dept} pour cette session, mais "
            "**pas encore permanente** — sera reconstruite depuis zéro au "
            "prochain redémarrage à froid de l'app (cause principale des "
            "lenteurs). Voir ci-dessous pour la rendre permanente."
        )
        with st.sidebar.expander("💾 Rendre cette référence permanente"):
            st.caption(
                "Téléchargez ces 3 fichiers et déposez-les dans un dossier "
                "`reference_data/` de votre dépôt GitHub — l'app les "
                "détectera alors automatiquement au démarrage, sans "
                "jamais avoir besoin de les reconstruire."
            )
            for nom in (f"reference_{dept}.csv", f"tendance_{dept}.csv",
                        f"transactions_nettoyees_{dept}.csv", f"meta_{dept}.json"):
                chemin = core.OUTPUT_DIR / nom
                if chemin.exists():
                    st.download_button(
                        f"⬇️ {nom}", chemin.read_bytes(), file_name=nom,
                        key=f"dl_{nom}", use_container_width=True,
                    )
else:
    with st.sidebar.status(f"Préparation automatique des données ({dept})...", expanded=True) as status_box:
        try:
            core.prepare_data_if_needed(dept, annees, progress_callback=status_box.write)
            load_reference.clear()
            status_box.update(label="✅ Données prêtes", state="complete")
        except SystemExit as e:
            status_box.update(label="Erreur lors de la préparation", state="error")
            st.sidebar.error(str(e))

st.sidebar.caption(
    "Astuce : une adresse peut détecter automatiquement un autre département. "
    "Sa référence sera alors préparée automatiquement à son tour."
)

st.title("ImmoScan — France entière")
st.caption("Détection d'opportunités immobilières à partir des transactions réelles DVF, avec historique probable du bien et vues géographiques.")

tab_recherche, tab_batch, tab_explore = st.tabs([
    "🔍 Rechercher un bien",
    "📋 Scorer plusieurs annonces",
    "📊 Explorer le marché",
])

ref, trend = load_reference(dept) if reference_exists(dept) else (None, None)

with tab_recherche:
    st.markdown(
        "Tapez une adresse : les suggestions apparaissent automatiquement en "
        "dessous pendant la frappe. Sélectionnez la bonne — toutes les "
        "informations disponibles s'affichent ensuite à la suite sur cette "
        "même page."
    )

    if CUSTOM_SEARCH_AVAILABLE:
        result = address_search_component(key="adresse_component")
        if result:
            st.session_state["adresse_confirmee"] = result
    else:
        st.error(
            "Le composant de suggestions automatiques n'a pas pu se charger."
        )
        if CUSTOM_SEARCH_ERROR:
            st.caption(f"Détail technique : `{CUSTOM_SEARCH_ERROR}`")

    st.divider()

    geo = st.session_state.get("adresse_confirmee")
    if geo is None:
        st.info("Aucune adresse confirmée pour le moment.")
    else:
        col_info, col_reset = st.columns([4, 1])
        with col_info:
            st.success(f"📍 Adresse active : {geo['label']}")
        with col_reset:
            if st.button("🔄 Nouvelle recherche"):
                for k in ("adresse_confirmee",):
                    st.session_state.pop(k, None)
                st.rerun()

        detected_dept = geo.get("departement") or dept
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Commune", geo["commune"])
        c2.metric("Code postal", geo["code_postal"])
        c3.metric("Département", detected_dept)
        c4.metric("Score BAN", f"{geo.get('score', 0):.2f}" if geo.get("score") else "—")

        col_radius, col_years = st.columns(2)
        with col_radius:
            radius_comparables = st.slider(
                "Rayon pour les ventes comparables", 100, 1000, 500, step=50, format="%d m",
            )
        with col_years:
            since_years = st.slider("Comparables : dernières N années", 1, 15, 5, step=1)

        col_nb, col_tri = st.columns(2)
        with col_nb:
            max_comparables = st.slider(
                "Nombre de comparables affichés", 5, 100, 15, step=5,
            )
        with col_tri:
            tri_label = st.selectbox(
                "Trier par", ["Distance (plus proches d'abord)", "Date (plus récentes d'abord)"],
            )
            tri_comparables = "date" if tri_label.startswith("Date") else "distance"

        st.subheader("Vues du bien")
        render_geo_views(geo["latitude"], geo["longitude"], radius_m=radius_comparables)

        if detected_dept != dept:
            st.warning(
                f"Cette adresse semble être dans le département {detected_dept}, "
                f"alors que la barre latérale est sur {dept}. Sélectionnez "
                f"{detected_dept} dans la barre latérale pour que sa référence "
                "se prépare automatiquement."
            )

        active_dept = detected_dept if reference_exists(detected_dept) else dept
        active_ref, _ = load_reference(active_dept) if reference_exists(active_dept) else (None, None)

        suggested_surface = None
        suggested_type = None
        known_parcelle_ids = None  # (code_insee, section, numero) si trouvé via DVF exact

        # --- Historique probable + comparables ---------------------------------
        if active_ref is None:
            st.info(
                f"La référence de prix pour le département {active_dept} n'est "
                "pas encore prête (voir la barre latérale) : historique DVF et "
                "comparables indisponibles pour l'instant."
            )
        else:
            st.subheader("Historique probable des ventes de ce bien précis")
            try:
                history = core.find_property_history(
                    active_dept, geo["label"], geo["latitude"], geo["longitude"],
                    commune=geo.get("commune"),
                )
                if history.empty:
                    st.caption(
                        "Aucune vente DVF ne correspond à ce numéro et cette rue "
                        "précisément (sur toutes les années chargées)."
                    )
                else:
                    st.dataframe(history, use_container_width=True)
                    st.caption(
                        "Filtré sur ce numéro + cette rue + cette commune "
                        "exactement, toutes années chargées confondues. En "
                        "copropriété, plusieurs lots peuvent partager ce numéro "
                        "— vérifiez la colonne 'correspondance' et l'adresse "
                        "DVF affichée."
                    )
                    exact_rows = history[history["correspondance"].str.startswith("Exacte")]
                    if not exact_rows.empty:
                        derniere = exact_rows.iloc[0]  # déjà triée par date décroissante
                        suggested_surface = derniere.get("surface_reelle_bati")
                        suggested_type = derniere.get("type_local")
                        if "id_parcelle" in exact_rows.columns:
                            parsed = core.parse_id_parcelle(derniere.get("id_parcelle"))
                            if parsed:
                                known_parcelle_ids = parsed
            except SystemExit as e:
                st.warning(str(e))

            st.subheader(f"Ventes comparables à proximité (derniers {since_years} ans)")
            try:
                comparables, resume_comparables = core.find_comparables(
                    active_dept, geo["latitude"], geo["longitude"],
                    radius_m=radius_comparables, since_years=since_years,
                    max_results=max_comparables, tri=tri_comparables,
                )
                if comparables.empty:
                    st.caption("Aucune transaction DVF comparable dans ce rayon/cette période.")
                else:
                    total = resume_comparables["total"]
                    par_source = resume_comparables["total_par_source"]
                    st.caption(
                        f"**{total} bien(s) trouvé(s) au total** dans ce rayon/cette "
                        f"période (affichage limité aux {max_comparables} premiers, "
                        f"triés par {'date' if tri_comparables == 'date' else 'distance'}) — "
                        + " · ".join(f"{v} via {k}" for k, v in par_source.items())
                    )

                    prix_par_type = resume_comparables["prix_m2_moyen_par_type"]
                    if prix_par_type:
                        cols_prix = st.columns(len(prix_par_type))
                        for col, (type_bien, prix_moy) in zip(cols_prix, prix_par_type.items()):
                            col.metric(f"€/m² moyen — {type_bien}", f"{prix_moy:,.0f} €")
                        if "Local commercial" not in prix_par_type and "Local industriel. commercial ou assimilé" not in prix_par_type:
                            st.caption(
                                "ℹ️ Les locaux commerciaux ne sont pas suivis par cette "
                                "app pour l'instant (seuls maisons, appartements et "
                                "immeubles en bloc sont traités)."
                            )

                    st.dataframe(comparables, use_container_width=True)
                    st.caption(
                        "Toutes les ventes à proximité, quel que soit le numéro/la "
                        "rue — pour comparer le prix au marché local récent. Les "
                        "sources DVF (2021+) et Cerema DVF+ (2014-2020) sont "
                        "mélangées dans un seul classement (par distance ou par "
                        "date selon le tri choisi ci-dessus), pas affichées "
                        "séparément."
                    )
            except SystemExit as e:
                st.warning(str(e))

        # --- DPE -----------------------------------------------------------
        st.subheader("DPE enregistré à cette adresse")
        with st.spinner("Recherche DPE ADEME..."):
            dpe = core.find_dpe(geo["label"], geo.get("code_postal"))
        if dpe is None or dpe.empty:
            st.caption("Aucun DPE trouvé automatiquement pour cette adresse.")
        else:
            st.dataframe(dpe, use_container_width=True)
            st.caption(
                "Le DPE n'alimente pas le pré-remplissage automatique (recherche "
                "textuelle approximative, non validée aussi strictement que "
                "l'historique DVF) — seule une correspondance exacte le fait."
            )

        st.subheader("Année de construction (BDNB)")
        with st.spinner("Recherche BDNB..."):
            batiment = core.get_batiment_bdnb(geo["latitude"], geo["longitude"])
        if batiment is None or not batiment.get("annee_construction"):
            st.caption(
                "Année de construction non trouvée automatiquement pour ce "
                "bâtiment (donnée parfois manquante ou non encore croisée "
                "dans la BDNB)."
            )
        else:
            st.metric("Année de construction estimée", batiment["annee_construction"])
            st.caption(
                "Source : BDNB (Base de Données Nationale des Bâtiments, CSTB) — "
                "croise cadastre, BDTopo IGN et Fichiers fonciers. Peut être une "
                "estimation statistique plutôt qu'une donnée certaine selon les "
                "bâtiments — à vérifier si un doute important."
            )

        if suggested_surface and suggested_type:
            st.caption(
                "💡 Surface et type trouvés via une vente exacte de ce bien : "
                "repris automatiquement ci-dessous (modifiable)."
            )

        st.divider()

        # --- Analyser ce bien : score marché + potentiel caché ensemble ------
        st.subheader("🔍 Analyser ce bien")

        detected_commune = geo.get("commune")
        lat, lon = geo["latitude"], geo["longitude"]

        if active_ref is not None:
            communes_dispo = sorted(active_ref["nom_commune"].unique())
            types_dispo = sorted(active_ref["type_local"].unique())
        else:
            communes_dispo, types_dispo = [], []

        # Resynchronise commune/type/surface à chaque nouvelle adresse
        # recherchée, sans jamais écraser une modification déjà faite pour
        # cette même adresse.
        if st.session_state.get("score_last_geo_label") != geo["label"]:
            st.session_state["score_last_geo_label"] = geo["label"]
            if detected_commune in communes_dispo:
                st.session_state["score_commune"] = detected_commune
            if suggested_type in types_dispo:
                st.session_state["score_type"] = suggested_type
            if suggested_surface:
                try:
                    st.session_state["score_surface"] = float(suggested_surface)
                except (TypeError, ValueError):
                    pass

        if communes_dispo and "score_commune" not in st.session_state:
            st.session_state["score_commune"] = communes_dispo[0]

        commune_score = type_local = None
        if communes_dispo:
            sc1, sc2 = st.columns(2)
            with sc1:
                commune_score = st.selectbox("Commune", communes_dispo, key="score_commune")
                type_local = st.selectbox("Type de bien", types_dispo, key="score_type")
            with sc2:
                surface = st.number_input(
                    "Surface (m²)", min_value=0.0, step=1.0, key="score_surface",
                    help="Utilisée à la fois pour le score marché et l'estimation du potentiel caché.",
                )
                prix = st.number_input(
                    "Prix affiché (€) — laisser à 0 si inconnu", min_value=0.0, step=1000.0,
                    key="score_prix",
                )
        else:
            st.info(
                f"La référence de prix pour le département {active_dept} n'est "
                "pas encore prête (voir la barre latérale) — le score marché "
                "sera indisponible, mais le potentiel caché reste utilisable."
            )
            surface = st.number_input("Surface (m²)", min_value=0.0, step=1.0, key="score_surface")
            prix = 0.0

        st.markdown("**Vérification manuelle complémentaire**")
        lc1, lc2, lc3, lc4 = st.columns(4)
        lc1.link_button("Cadastre", f"https://www.cadastre.gouv.fr/scpc/rechercherPlan.do?lat={lat}&lon={lon}",
                         use_container_width=True)
        lc2.link_button("Géoportail Urbanisme",
                         f"https://www.geoportail-urbanisme.gouv.fr/map/#tile=1&lat={lat}&lon={lon}&zoom=18",
                         use_container_width=True)
        lc3.link_button("Géorisques", f"https://www.georisques.gouv.fr/mes-risques/connaitre-les-risques-pres-de-chez-moi?lat={lat}&lon={lon}",
                         use_container_width=True)
        lc4.link_button("Pappers Immo", "https://immobilier.pappers.fr/",
                         use_container_width=True)
        st.caption(
            "Pappers Immo n'a pas d'intégration automatique ici : son API "
            "nécessite une clé payante au-delà de 100 crédits gratuits. Le lien "
            "ouvre sa carte interactive pour une vérification manuelle gratuite."
        )

        if st.button("Analyser ce bien", type="primary", key="score_button"):
            if not surface:
                st.warning("Renseignez au moins la surface pour lancer l'analyse.")
            else:
                # --- Score marché (si commune dispo et prix renseigné) -----
                st.markdown("#### 📊 Score vs marché")
                if not commune_score:
                    st.caption("Référence de prix indisponible pour ce département.")
                elif not prix:
                    st.caption(
                        "ℹ️ Prix non renseigné : score marché non calculé "
                        "(le potentiel caché ci-dessous reste disponible)."
                    )
                else:
                    result = core.score_property(commune_score, type_local, surface, prix, dept=active_dept)
                    if "erreur" in result:
                        st.error(result["erreur"])
                    else:
                        ecart = result["ecart_pct"]
                        color = "🟢" if ecart <= -15 else "🟡" if ecart < 5 else "🟠" if ecart < 15 else "🔴"
                        st.markdown(f"**{color} {result['diagnostic']}**")
                        rc1, rc2, rc3, rc4 = st.columns(4)
                        rc1.metric("Prix/m² annonce", f"{result['prix_m2_annonce']:,} €")
                        rc2.metric(f"Référence {commune_score}", f"{result['prix_m2_reference_commune']:,} €")
                        rc3.metric("Écart au marché", f"{ecart:+.1f} %")
                        rc4.metric("Transactions", result["nb_transactions_reference"])
                        st.caption(
                            "Ce score compare uniquement le prix au m². Il ne "
                            "remplace pas l'analyse travaux, urbanisme et liquidité."
                        )
                        dpe_info = core.interpret_dpe_classe(dpe)
                        if dpe_info:
                            classe_str = dpe_info["classe_energie"]
                            if dpe_info["classe_ges"]:
                                classe_str += f" / GES {dpe_info['classe_ges']}"
                            st.caption(f"💡 DPE {classe_str} — {dpe_info['note']}")

                st.divider()

                # --- Potentiel caché : cadastre, PLU, Géorisques, transports -
                st.markdown("#### 🏗️ Potentiel caché")
                with st.spinner("Cadastre (API Carto IGN)..."):
                    if known_parcelle_ids:
                        parcelle = core.get_parcelle_by_identifiants(
                            known_parcelle_ids["code_insee"],
                            known_parcelle_ids["section"],
                            known_parcelle_ids["numero"],
                        )
                        if parcelle is None:
                            # Repli si jamais l'identifiant DVF ne matche plus
                            # (rare : remaniement cadastral, ou parcelle
                            # simplement absente du PCI vecteur actuel).
                            parcelle = core.get_parcelle_cadastrale(lat, lon)
                    else:
                        parcelle = core.get_parcelle_cadastrale(lat, lon)
                with st.spinner("Zone PLU (API Carto IGN — GPU)..."):
                    zones_plu = core.get_zone_plu(lat, lon)
                with st.spinner("Risques naturels et technologiques (Géorisques)..."):
                    georisques = core.get_georisques(lat, lon)
                with st.spinner("Transports à proximité (OpenStreetMap)..."):
                    transports = core.find_nearby_transport(lat, lon)

                st.markdown("**Parcelle(s) cadastrale(s)**")
                if parcelle is None:
                    st.caption(
                        "Aucune parcelle trouvée automatiquement. Cela peut arriver "
                        "en zone non cadastrée ou si l'API est temporairement "
                        "indisponible."
                    )
                elif parcelle.get("source") == "identifiant DVF exact":
                    pc1, pc2, pc3 = st.columns(3)
                    pc1.metric("Code INSEE (cadastre)", parcelle.get("code_insee") or "—")
                    pc2.metric("Section / numéro",
                               f"{parcelle.get('section') or '—'} / {parcelle.get('numero') or '—'}")
                    pc3.metric("Contenance", f"{parcelle.get('contenance_m2') or '—'} m²")
                    st.success(
                        "✅ Parcelle identifiée via une vente DVF exacte de ce bien "
                        "(identifiant cadastral officiel, pas une estimation par "
                        "coordonnées GPS) — fiable à 100%."
                    )
                else:
                    nb = parcelle.get("nb_parcelles") or 1
                    if nb > 1:
                        st.dataframe(
                            pd.DataFrame(parcelle["parcelles"])[["section", "numero", "contenance_m2"]],
                            use_container_width=True,
                        )
                        st.caption(
                            f"⚠️ {nb} parcelles trouvées dans un rayon de 10 m autour du "
                            "point recherché (aucune vente DVF exacte disponible pour "
                            "identifier la bonne directement) — l'adresse géocodée "
                            "tombe parfois sur la voie plutôt que sur la parcelle "
                            "bâtie réelle. **Vérifiez laquelle correspond vraiment à "
                            "ce bien** via l'onglet '📐 Cadastre' ou le lien Cadastre "
                            "ci-dessus avant de vous fier à l'estimation plus bas."
                        )
                    else:
                        pc1, pc2, pc3 = st.columns(3)
                        pc1.metric("Code INSEE (cadastre)", parcelle.get("code_insee") or "—")
                        pc2.metric("Section / numéro",
                                   f"{parcelle.get('section') or '—'} / {parcelle.get('numero') or '—'}")
                        pc3.metric("Contenance", f"{parcelle.get('contenance_m2') or '—'} m²")
                        st.caption(
                            "Rappel : la contenance est la surface du **terrain** "
                            "(cadastre), pas la surface habitable — une maison "
                            "étroite sur plusieurs étages peut avoir une contenance "
                            "bien plus petite que sa surface habitable totale. "
                            "Vérifiez via l'onglet '📐 Cadastre' en cas de doute."
                        )

                st.markdown("**Zone PLU**")
                if not zones_plu:
                    st.caption(
                        "Aucune zone PLU trouvée automatiquement à ce point (commune "
                        "au RNU, document non encore publié sur le Géoportail de "
                        "l'Urbanisme, ou point hors zonage)."
                    )
                else:
                    st.dataframe(pd.DataFrame(zones_plu), use_container_width=True)

                st.markdown("**Transports en commun à proximité**")
                if not transports:
                    st.caption(
                        "Aucune gare/station trouvée automatiquement dans un rayon "
                        "de 1,5 km, ou service temporairement indisponible."
                    )
                else:
                    st.dataframe(pd.DataFrame(transports), use_container_width=True)
                    st.caption(
                        "Source : OpenStreetMap (base collaborative) — couverture "
                        "très bonne en Île-de-France, à vérifier ailleurs en cas de doute."
                    )

                st.markdown("**Risques naturels et technologiques (Géorisques)**")
                if georisques is None:
                    st.caption(
                        "Résultat indisponible automatiquement. Vérifiez manuellement "
                        "sur georisques.gouv.fr en cas de doute avant tout projet."
                    )
                else:
                    st.json(georisques, expanded=False)

                st.markdown("**Estimation indicative de réserve foncière**")
                potentiel = core.estimate_hidden_potential(
                    parcelle, zones_plu, surface_bati_existante=surface or None
                )
                ec1, ec2, ec3 = st.columns(3)
                ec1.metric("Contenance parcelle",
                           f"{potentiel['contenance_parcelle_m2'] or '—'} m²")
                ec2.metric("Emprise au sol estimée",
                           f"{potentiel['emprise_au_sol_estimee_pct'] or '—'}%")
                ec3.metric("Réserve foncière théorique",
                           f"{potentiel['reserve_fonciere_theorique_m2'] or '—'} m²")
                st.info(potentiel["commentaire"])
                st.caption(
                    "⚠️ Estimation grossière, à but indicatif uniquement. Ne remplace "
                    "ni la lecture du règlement de zone PLU complet (hauteur, emprise "
                    "au sol maximale, reculs, coefficient de biotope...) ni un "
                    "certificat d'urbanisme officiel demandé en mairie."
                )

with tab_batch:
    if ref is None:
        st.info("Construisez d'abord la référence de prix via la barre latérale.")
    else:
        st.markdown("Déposez un CSV avec les colonnes : `adresse, commune, type_local, surface, prix`")
        exemple = pd.DataFrame([{"adresse": "12 rue de la Paix", "commune": "Vincennes", "type_local": "Maison", "surface": 90, "prix": 480000}])
        st.download_button("Télécharger un exemple de CSV", exemple.to_csv(index=False), file_name="exemple_annonces.csv")
        uploaded = st.file_uploader("Fichier d'annonces (CSV)", type=["csv"])
        if uploaded is not None:
            listings = pd.read_csv(uploaded)
            required = {"commune", "type_local", "surface", "prix"}
            missing = required - set(listings.columns)
            if missing:
                st.error(f"Colonnes manquantes : {missing}")
            else:
                results = []
                for _, r in listings.iterrows():
                    res = core.score_property(r["commune"], r["type_local"], r["surface"], r["prix"], dept=dept)
                    res["adresse"] = r.get("adresse", "")
                    results.append(res)
                out = pd.DataFrame(results)
                if "ecart_pct" in out.columns:
                    out = out.sort_values("ecart_pct")
                st.dataframe(out, use_container_width=True)
                st.download_button("Télécharger les résultats", out.to_csv(index=False), file_name="opportunites_scorees.csv")

with tab_explore:
    if ref is None:
        st.info("Construisez d'abord la référence de prix via la barre latérale.")
    else:
        type_filter = st.selectbox("Type de bien à afficher", sorted(ref["type_local"].unique()), key="explore_type")
        subset = ref[ref["type_local"] == type_filter].sort_values("prix_m2_median", ascending=False)
        st.markdown(f"**Prix médian au m² par commune — {type_filter} — département {dept}**")
        st.bar_chart(subset.set_index("nom_commune")["prix_m2_median"])
        st.dataframe(subset, use_container_width=True)
        if trend is not None:
            st.markdown("**Évolution des prix**")
            trend_subset = trend[trend["type_local"] == type_filter]
            if "evolution_pct" in trend_subset.columns:
                trend_subset = trend_subset.sort_values("evolution_pct", ascending=False)
            st.dataframe(trend_subset, use_container_width=True)
