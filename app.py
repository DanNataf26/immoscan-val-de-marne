#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ImmoScan France — Application Streamlit
=======================================
Prototype de détection d'opportunités immobilières sous-évaluées,
basé sur les transactions DVF, avec géolocalisation, historique probable,
comparables, DPE et vues cartographiques.
"""

import math
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
                for k in (
                    "adresse_confirmee", "adresse_component",
                    "history_cache_key", "history_cache_result",
                    "types_bien_selection", "type_bien_historique_widget",
                    "type_bien_comparables_widget",
                    "surface_bien_selection", "surface_bien_historique_widget",
                ):
                    st.session_state.pop(k, None)
                st.rerun()

        detected_dept = geo.get("departement") or dept
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Commune", geo["commune"])
        c2.metric("Code postal", geo["code_postal"])
        c3.metric("Département", detected_dept)
        c4.metric("Score BAN", f"{geo.get('score', 0):.2f}" if geo.get("score") else "—")

        map_placeholder = st.container()

        if detected_dept != dept and not core.reference_is_up_to_date(detected_dept, annees):
            with st.status(
                f"Cette adresse est dans le département {detected_dept} — "
                "préparation automatique de ses données...", expanded=True
            ) as status_box:
                try:
                    core.prepare_data_if_needed(detected_dept, annees, progress_callback=status_box.write)
                    load_reference.clear()
                    status_box.update(label="✅ Données prêtes", state="complete")
                except SystemExit as e:
                    status_box.update(label="Erreur lors de la préparation", state="error")
                    st.error(str(e))
        elif detected_dept != dept:
            st.info(
                f"📍 Cette adresse est dans le département {detected_dept} "
                f"(différent du {dept} sélectionné en barre latérale) — sa "
                "référence est déjà prête et utilisée automatiquement."
            )

        active_dept = detected_dept if reference_exists(detected_dept) else dept
        active_ref, _ = load_reference(active_dept) if reference_exists(active_dept) else (None, None)

        suggested_surface = None
        suggested_type = None
        known_parcelle_ids = None  # (code_insee, section, numero) si trouvé via DVF exact

        # --- Historique probable + comparables ---------------------------------
        if active_ref is None:
            with map_placeholder:
                st.subheader("Vues du bien")
                render_geo_views(geo["latitude"], geo["longitude"], radius_m=500)
            st.info(
                f"La référence de prix pour le département {active_dept} n'est "
                "pas encore prête (voir la barre latérale) : historique DVF et "
                "comparables indisponibles pour l'instant."
            )
        else:
            st.subheader("Historique probable des ventes de cette adresse précise")
            include_vefa_historique = st.checkbox(
                "Inclure les ventes en VEFA (neuf sur plan)", value=False,
                key="include_vefa_historique",
                help="Prix incluant une prime 'neuf' (TVA, garanties constructeur), "
                     "pas directement comparable à une revente ancienne — exclu par défaut.",
            )
            try:
                cache_key_historique = (geo["label"], include_vefa_historique)
                if st.session_state.get("history_cache_key") == cache_key_historique:
                    history = st.session_state["history_cache_result"]
                else:
                    with st.spinner("Recherche de l'historique (et, si besoin, du cadastre)..."):
                        history = core.find_property_history(
                            active_dept, geo["label"], geo["latitude"], geo["longitude"],
                            commune=geo.get("commune"), code_insee=geo.get("code_insee"),
                            include_vefa=include_vefa_historique,
                        )
                    st.session_state["history_cache_key"] = cache_key_historique
                    st.session_state["history_cache_result"] = history
                if history.empty:
                    st.caption(
                        "Aucune vente DVF ne correspond à ce numéro et cette rue "
                        "précisément (sur toutes les années chargées)."
                    )
                else:
                    exact_rows = history[history["correspondance"].str.startswith("Exacte")]
                    types_bien_adresse = []
                    if not exact_rows.empty:
                        derniere = exact_rows.iloc[0]  # déjà triée par date décroissante
                        suggested_surface = derniere.get("surface_reelle_bati")
                        suggested_type = derniere.get("type_local")
                        if "id_parcelle" in exact_rows.columns:
                            parsed = core.parse_id_parcelle(derniere.get("id_parcelle"))
                            if parsed:
                                known_parcelle_ids = parsed
                        types_bien_adresse = sorted(exact_rows["type_local"].dropna().unique())

                    if len(types_bien_adresse) > 1:
                        # Adresse mixte (ex. immeuble avec commerce + habitation) :
                        # on laisse choisir un, plusieurs, ou tous les types à
                        # consulter. La sélection est partagée avec le filtre
                        # "Type de bien" de "Ventes comparables" plus bas
                        # (synchronisation dans les deux sens via la liste
                        # "types_bien_selection" + callbacks on_change).
                        if "types_bien_selection" not in st.session_state:
                            st.session_state["types_bien_selection"] = (
                                [suggested_type] if suggested_type in types_bien_adresse
                                else [types_bien_adresse[0]]
                            )
                        # Si "Ventes comparables" a changé la sélection canonique
                        # depuis le dernier rendu, on aligne l'état du widget
                        # AVANT de l'instancier (restreint aux types réellement
                        # présents à cette adresse).
                        valeur_alignee = [
                            t for t in st.session_state["types_bien_selection"]
                            if t in types_bien_adresse
                        ]
                        if st.session_state.get("type_bien_historique_widget") != valeur_alignee:
                            st.session_state["type_bien_historique_widget"] = valeur_alignee

                        def _sync_depuis_historique():
                            st.session_state["types_bien_selection"] = (
                                st.session_state["type_bien_historique_widget"]
                            )

                        types_choisis_hist = st.multiselect(
                            "Types de bien trouvés à cette adresse — lesquels "
                            "consulter ? (aucun = tous)",
                            types_bien_adresse,
                            key="type_bien_historique_widget",
                            on_change=_sync_depuis_historique,
                        )
                        if types_choisis_hist:
                            history_affichee = history[
                                history["type_local"].isna()
                                | history["type_local"].isin(types_choisis_hist)
                            ]
                        else:
                            history_affichee = history
                    else:
                        history_affichee = history
                        if types_bien_adresse:
                            st.session_state["types_bien_selection"] = types_bien_adresse

                    # Une fois le type filtré, plusieurs lots peuvent encore
                    # partager la même adresse (copropriété) — la surface est
                    # en général le repère le plus fiable pour identifier son
                    # propre bien parmi eux. Cette sélection sert aussi de
                    # référence pour prioriser "Ventes comparables" plus bas.
                    surfaces_dispo = []
                    if "correspondance" in history_affichee.columns and "surface_reelle_bati" in history_affichee.columns:
                        exact_pour_surface = history_affichee[
                            history_affichee["correspondance"].str.startswith("Exacte")
                        ]
                        surfaces_dispo = sorted(
                            exact_pour_surface["surface_reelle_bati"].dropna().unique()
                        )

                    if len(surfaces_dispo) > 1:
                        surfaces_choisies = st.multiselect(
                            "Plusieurs surfaces trouvées pour ce type à cette "
                            "adresse — laquelle est la vôtre ? (aucune = toutes)",
                            surfaces_dispo,
                            key="surface_bien_historique_widget",
                            format_func=lambda s: f"{s:.0f} m²",
                        )
                        if surfaces_choisies:
                            history_affichee = history_affichee[
                                history_affichee["surface_reelle_bati"].isna()
                                | history_affichee["surface_reelle_bati"].isin(surfaces_choisies)
                            ]
                        st.session_state["surface_bien_selection"] = (
                            surfaces_choisies[0] if len(surfaces_choisies) == 1 else None
                        )
                    elif len(surfaces_dispo) == 1:
                        st.session_state["surface_bien_selection"] = surfaces_dispo[0]
                    else:
                        st.session_state["surface_bien_selection"] = None

                    st.dataframe(history_affichee, use_container_width=True)
                    st.caption(
                        "Filtré sur ce numéro + cette rue + cette commune "
                        "exactement, toutes années chargées confondues. En "
                        "copropriété, plusieurs lots peuvent partager ce numéro "
                        "— vérifiez la colonne 'correspondance' et l'adresse "
                        "DVF affichée."
                    )

                with st.expander("🔧 Diagnostic technique (cadastre / Cerema)"):
                    import json as _json
                    _rapport = []  # accumule le texte pour copie/téléchargement en fin de bloc

                    def _log(titre, contenu=None):
                        """Affiche à l'écran ET ajoute au rapport texte copiable."""
                        st.write(titre)
                        _rapport.append(titre.replace("**", ""))
                        if contenu is not None:
                            if isinstance(contenu, (dict, list)):
                                texte = _json.dumps(contenu, ensure_ascii=False, indent=2)
                                st.json(contenu)
                            else:
                                texte = str(contenu)
                            _rapport.append(texte)
                        _rapport.append("")

                    _log(f"Adresse : {geo['label']}")
                    _log(
                        f"Commune affichée : {geo.get('commune')} — "
                        f"code_insee utilisé (BAN) : {geo.get('code_insee')}"
                    )
                    if geo.get("code_insee") and not str(geo["code_insee"]).startswith(active_dept):
                        st.error(
                            f"⚠️ Incohérence : ce code_insee ne commence pas par "
                            f"le département actif ({active_dept}) — probable "
                            "erreur de géocodage BAN pour cette adresse."
                        )
                        _rapport.append(
                            f"⚠️ INCOHÉRENCE : code_insee ne commence pas par {active_dept}"
                        )
                        _rapport.append("")

                    with st.spinner("Test en direct : RNB étape 1 (adresse)..."):
                        try:
                            import requests as _requests
                            _resp_rnb1 = _requests.get(
                                f"{core.RNB_API_URL}/address/",
                                params={"q": geo["label"]}, timeout=10,
                            )
                            _data_rnb1 = _resp_rnb1.json()
                            _log(f"**RNB étape 1 — code HTTP : {_resp_rnb1.status_code}**", _data_rnb1)
                        except Exception as exc:
                            _data_rnb1 = None
                            st.error(f"Exception RNB étape 1 : {type(exc).__name__}: {exc}")
                            _rapport.append(f"Exception RNB étape 1 : {type(exc).__name__}: {exc}\n")

                    if _data_rnb1 and _data_rnb1.get("results"):
                        st.write("**Étape 2 — test cadastre strict au point de chaque bâtiment :**")
                        _rapport.append("Étape 2 — test cadastre strict au point de chaque bâtiment :\n")
                        for i, bat in enumerate(_data_rnb1["results"]):
                            rnb_id = bat.get("rnb_id")
                            coords = (bat.get("point") or {}).get("coordinates")
                            if not coords:
                                _log(f"Bâtiment {i} ({rnb_id}) — pas de point exploitable.")
                                continue
                            lon_bat, lat_bat = coords
                            try:
                                res_bat = core._point_exact_apicarto(lat_bat, lon_bat)
                                _log(
                                    f"Bâtiment {i} ({rnb_id}), point ({lat_bat:.6f}, {lon_bat:.6f}) :",
                                    res_bat if res_bat else {"resultat": None},
                                )
                            except Exception as exc:
                                st.error(f"Exception (bâtiment {i}) : {type(exc).__name__}: {exc}")
                                _rapport.append(f"Exception (bâtiment {i}) : {type(exc).__name__}: {exc}\n")

                    with st.spinner("Test en direct : RNB (complet) puis GPS si besoin..."):
                        diag_parcelle, methode_utilisee = None, None
                        try:
                            diag_parcelle = core.get_parcelle_via_rnb(geo["label"])
                            methode_utilisee = "RNB (par adresse)"
                        except Exception as exc:
                            st.error(f"Exception RNB : {type(exc).__name__}: {exc}")
                            _rapport.append(f"Exception RNB : {type(exc).__name__}: {exc}\n")
                        if not diag_parcelle:
                            try:
                                diag_parcelle = core.get_parcelle_cadastrale(
                                    geo["latitude"], geo["longitude"]
                                )
                                methode_utilisee = "GPS (Géoplateforme/API Carto)"
                            except Exception as exc:
                                st.error(f"Exception GPS : {type(exc).__name__}: {exc}")
                                _rapport.append(f"Exception GPS : {type(exc).__name__}: {exc}\n")
                    _log(f"**Méthode ayant abouti : {methode_utilisee or 'aucune'}**")
                    _log("**Résultat :**", diag_parcelle if diag_parcelle else {"resultat": None})

                    if diag_parcelle:
                        _log(
                            f"nb_parcelles = {diag_parcelle.get('nb_parcelles')} "
                            f"(source : {diag_parcelle.get('source')})"
                        )
                        if diag_parcelle.get("nb_parcelles") != 1:
                            st.warning(
                                "Plus d'une parcelle trouvée (ou 0) — c'est pour ça "
                                "que le lien avec Cerema ne se fait pas automatiquement "
                                "(voir la logique de sécurité anti-faux-positifs)."
                            )
                        else:
                            diag_cerema = core.load_cerema_cache(active_dept)
                            if diag_cerema is None:
                                st.warning("Aucun cache Cerema trouvé pour ce département.")
                            else:
                                sec = str(diag_parcelle.get("section") or "").lstrip("0").upper()
                                num = str(diag_parcelle.get("numero") or "").lstrip("0")
                                code_insee_cible = str(geo.get("code_insee") or diag_parcelle.get("code_insee") or "").strip()
                                diag_cerema = diag_cerema.copy()
                                diag_cerema["_section"] = diag_cerema["id_parcelle"].astype(str).str[8:10].str.lstrip("0").str.upper()
                                diag_cerema["_numero"] = diag_cerema["id_parcelle"].astype(str).str[10:14].str.lstrip("0")
                                diag_cerema["_code_insee"] = diag_cerema["id_parcelle"].astype(str).str[0:5]
                                diag_match = diag_cerema[
                                    (diag_cerema["_section"] == sec) & (diag_cerema["_numero"] == num)
                                    & (diag_cerema["_code_insee"] == code_insee_cible)
                                ]
                                _log(
                                    f"Recherché dans Cerema : code_insee={code_insee_cible}, "
                                    f"section={sec}, numéro={num}"
                                )
                                _log(f"Lignes Cerema correspondantes trouvées : {len(diag_match)}")
                                if not diag_match.empty:
                                    st.dataframe(diag_match, use_container_width=True)
                                    _rapport.append(diag_match.to_string(index=False))
                                    _rapport.append("")

                    st.divider()
                    st.markdown("**📋 Copier ce diagnostic**")
                    texte_complet = "\n".join(_rapport)
                    st.code(texte_complet, language="text")
                    st.download_button(
                        "⬇️ Télécharger ce diagnostic (.txt)",
                        texte_complet,
                        file_name=f"diagnostic_{geo['label'][:30].replace(' ', '_')}.txt",
                        use_container_width=True,
                    )
            except SystemExit as e:
                st.warning(str(e))

            st.subheader("Ventes comparables à proximité")
            try:
                with st.expander("🔍 Paramètres de la recherche", expanded=False):
                    st.caption(
                        "Ces réglages relancent une vraie recherche (avec "
                        "élargissement automatique du rayon/de la période si "
                        "besoin) — à distinguer des filtres d'affichage ci-dessous, "
                        "qui ne font que trier ce qui a déjà été trouvé."
                    )
                    # Applique une éventuelle resynchronisation en attente (voir
                    # plus bas) AVANT de créer les curseurs : une fois un widget
                    # instancié, Streamlit interdit de réécrire sa clé d'état
                    # dans la même exécution — d'où ce détour par une clé
                    # intermédiaire, appliquée seulement au tout début du
                    # prochain script.
                    if "_pending_radius_sync" in st.session_state:
                        st.session_state["radius_comparables_widget"] = (
                            st.session_state.pop("_pending_radius_sync")
                        )
                    if "_pending_years_sync" in st.session_state:
                        st.session_state["since_years_widget"] = (
                            st.session_state.pop("_pending_years_sync")
                        )
                    # Valeurs de départ posées directement en session_state,
                    # sans jamais passer aussi un `value=` explicite au
                    # widget : fournir les deux à la fois (même si égaux) est
                    # une combinaison que Streamlit signale par un avertissement.
                    st.session_state.setdefault("radius_comparables_widget", 100)
                    st.session_state.setdefault("since_years_widget", 5)

                    col_radius, col_years = st.columns(2)
                    with col_radius:
                        radius_comparables = st.slider(
                            "Rayon", 100, 1000, step=50, format="%d m",
                            key="radius_comparables_widget",
                        )
                    with col_years:
                        since_years = st.slider(
                            "Dernières N années", 1, 15, step=1,
                            key="since_years_widget",
                            help="Ne borne que le DVF récent (2021+). Le Cerema "
                                 "DVF+ (2014-2020), quand disponible, est toujours "
                                 "inclus intégralement — sa période est fixe et ne "
                                 "recule pas avec ce curseur.",
                        )

                    col_nb, col_tri = st.columns(2)
                    with col_nb:
                        max_comparables = st.slider(
                            "Nombre cible de résultats", 5, 100, 15, step=5,
                            help="Détermine à la fois combien de lignes s'affichent "
                                 "ET jusqu'où la recherche élargit automatiquement le "
                                 "rayon/la période si elle n'en trouve pas assez près "
                                 "— une valeur élevée peut donc ramener des ventes "
                                 "bien au-delà du rayon affiché ci-dessus.",
                        )
                    with col_tri:
                        tri_label = st.selectbox(
                            "Trier par",
                            ["Distance (plus proches d'abord)", "Date (plus récentes d'abord)"],
                        )
                        tri_comparables = "date" if tri_label.startswith("Date") else "distance"

                    include_vefa_comparables = st.checkbox(
                        "Inclure les ventes en VEFA (neuf sur plan)", value=False,
                        key="include_vefa_comparables",
                        help="Prix incluant une prime 'neuf' (TVA, garanties constructeur), "
                             "pas directement comparable à une revente ancienne — exclu par défaut.",
                    )

                # Si une sélection canonique unique existe déjà (venant de
                # "Historique probable" ou d'un choix précédent ici), on la
                # passe directement à la recherche : elle élargit alors
                # rayon/période spécifiquement pour CE type (comme le fait
                # "Historique probable"), au lieu de filtrer après coup un
                # petit échantillon tous-types-confondus qui peut ne
                # contenir aucun résultat du type recherché s'il est rare
                # localement.
                canon_avant_recherche = st.session_state.get("types_bien_selection", [])
                type_local_recherche = (
                    canon_avant_recherche[0] if len(canon_avant_recherche) == 1 else None
                )
                surface_recherche = st.session_state.get("surface_bien_selection")

                resultat_auto = core.find_comparables_auto(
                    active_dept, geo["latitude"], geo["longitude"],
                    type_local=type_local_recherche,
                    radius_m=radius_comparables, since_years=since_years,
                    max_results=max_comparables, tri=tri_comparables,
                    cible_min=max_comparables,
                    include_vefa=include_vefa_comparables,
                    surface_reference=surface_recherche,
                )
                comparables = resultat_auto["df"]
                resume_comparables = resultat_auto["resume"]
                radius_utilise = resultat_auto["radius_final"]
                since_years_utilise = resultat_auto["since_years_final"]

                # Le curseur affiche la valeur DEMANDÉE, pas forcément celle
                # réellement utilisée après élargissement automatique — sans
                # ça, "Rayon" reste bloqué sur 100 m même quand la recherche
                # a dû élargir à 250 m, ce qui est trompeur. On ne peut pas
                # réécrire la clé d'un widget déjà instancié dans cette même
                # exécution (Streamlit l'interdit) : on dépose donc la valeur
                # cible dans une clé intermédiaire, appliquée au tout début
                # du prochain passage, juste avant que les curseurs soient
                # recréés (voir plus haut). Le test d'égalité empêche une
                # boucle de rerun continue.
                if (
                    radius_utilise != st.session_state.get("radius_comparables_widget")
                    or since_years_utilise != st.session_state.get("since_years_widget")
                ):
                    st.session_state["_pending_radius_sync"] = radius_utilise
                    st.session_state["_pending_years_sync"] = since_years_utilise
                    st.rerun()

                if type_local_recherche:
                    st.caption(
                        f"🎯 Recherche ciblée sur le type « {type_local_recherche} » "
                        "(présélectionné depuis l'historique de cette adresse) — "
                        "décochez le filtre dans la recherche ci-dessus pour "
                        "élargir à tous les types."
                    )
                if surface_recherche:
                    st.caption(
                        f"📐 Résultats triés en tenant compte de la surface de "
                        f"votre bien ({surface_recherche:.0f} m², sélectionnée "
                        "dans l'historique ci-dessus) pour départager les lots "
                        "d'un même immeuble à distance égale."
                    )

                if comparables.empty:
                    comparables_filtres = comparables
                else:
                    with st.expander("🎛️ Filtrer les résultats affichés", expanded=False):
                        st.caption(
                            "Laissez un champ vide pour ne pas filtrer dessus "
                            "(tout est affiché par défaut)."
                        )
                        fc1, fc2, fc3 = st.columns(3)
                        with fc1:
                            types_dispo_filtre = sorted(comparables["type_local"].dropna().unique())
                            canon = st.session_state.get("types_bien_selection", [])
                            defaut_type = [t for t in canon if t in types_dispo_filtre]
                            # Si la sélection canonique (mise à jour côté "Historique
                            # probable") a changé depuis le dernier rendu de ce
                            # multiselect, on aligne son état AVANT de l'instancier.
                            if st.session_state.get("type_bien_comparables_widget") != defaut_type:
                                st.session_state["type_bien_comparables_widget"] = defaut_type

                            def _sync_depuis_comparables():
                                st.session_state["types_bien_selection"] = (
                                    st.session_state["type_bien_comparables_widget"]
                                )

                            types_choisis = st.multiselect(
                                "Type de bien", types_dispo_filtre, default=defaut_type,
                                key="type_bien_comparables_widget",
                                on_change=_sync_depuis_comparables,
                            )
                        with fc2:
                            communes_dispo_filtre = sorted(comparables["nom_commune"].dropna().unique())
                            communes_choisies = st.multiselect("Commune", communes_dispo_filtre)
                        with fc3:
                            sources_dispo_filtre = sorted(comparables["source"].dropna().unique())
                            sources_choisies = st.multiselect("Source", sources_dispo_filtre)

                        def _pas_lisible(etendue):
                            """Choisit un pas d'arrondi 'joli' (1/2/5 x 10^n) adapté
                            à l'étendue d'une plage, pour des bornes de slider
                            lisibles plutôt que des décimales brutes. Retourne un
                            float : st.slider exige que min/max/value/step soient
                            tous du même type, et ces plages sont par nature des
                            prix/surfaces décimaux."""
                            if etendue <= 0:
                                return 1.0
                            magnitude = 10 ** math.floor(math.log10(etendue))
                            for mult in (1, 2, 5, 10):
                                if etendue / (magnitude * mult) <= 20:
                                    return float(magnitude * mult)
                            return float(magnitude * 10)

                        def _bornes_arrondies(vmin, vmax):
                            pas = _pas_lisible(vmax - vmin)
                            bas = float(math.floor(vmin / pas) * pas)
                            haut = float(math.ceil(vmax / pas) * pas)
                            if haut <= bas:
                                haut = bas + pas
                            return bas, haut, pas

                        fc4, fc5 = st.columns(2)
                        with fc4:
                            prix_min_brut = float(comparables["prix_m2"].min())
                            prix_max_brut = float(comparables["prix_m2"].max())
                            if prix_max_brut > prix_min_brut:
                                prix_bas, prix_haut, pas_prix = _bornes_arrondies(
                                    prix_min_brut, prix_max_brut)
                                plage_prix = st.slider(
                                    "Prix/m² (€)", prix_bas, prix_haut,
                                    (prix_bas, prix_haut), step=float(pas_prix),
                                )
                            else:
                                plage_prix = (prix_min_brut, prix_max_brut)
                        with fc5:
                            total_min_brut = float(comparables["valeur_fonciere"].min())
                            total_max_brut = float(comparables["valeur_fonciere"].max())
                            if total_max_brut > total_min_brut:
                                total_bas, total_haut, pas_total = _bornes_arrondies(
                                    total_min_brut, total_max_brut)
                                plage_prix_total = st.slider(
                                    "Prix total (€)", total_bas, total_haut,
                                    (total_bas, total_haut), step=float(pas_total),
                                )
                            else:
                                plage_prix_total = (total_min_brut, total_max_brut)

                        if "surface_reelle_bati" in comparables.columns:
                            surf_min_brut = float(comparables["surface_reelle_bati"].min())
                            surf_max_brut = float(comparables["surface_reelle_bati"].max())
                            if surf_max_brut > surf_min_brut:
                                surf_bas, surf_haut, pas_surf = _bornes_arrondies(
                                    surf_min_brut, surf_max_brut)
                                plage_surface = st.slider(
                                    "Surface (m²)", surf_bas, surf_haut,
                                    (surf_bas, surf_haut), step=float(pas_surf),
                                )
                            else:
                                plage_surface = (surf_min_brut, surf_max_brut)
                        else:
                            plage_surface = None

                        pieces_dispo = (
                            comparables["nombre_pieces_principales"].dropna()
                            if "nombre_pieces_principales" in comparables.columns
                            else pd.Series(dtype=float)
                        )
                        if not pieces_dispo.empty and pieces_dispo.max() > pieces_dispo.min():
                            p_bas, p_haut = int(pieces_dispo.min()), int(pieces_dispo.max())
                            plage_pieces = st.slider(
                                "Nombre de pièces", p_bas, p_haut, (p_bas, p_haut),
                                help="Absent pour les ventes Cerema DVF+ (2014-2020), "
                                     "qui ne portent pas cette information — ces lignes "
                                     "restent affichées quel que soit ce filtre.",
                            )
                        else:
                            plage_pieces = None

                        masque = comparables["prix_m2"].between(plage_prix[0], plage_prix[1])
                        masque &= comparables["valeur_fonciere"].between(
                            plage_prix_total[0], plage_prix_total[1])
                        if plage_surface is not None:
                            masque &= comparables["surface_reelle_bati"].between(
                                plage_surface[0], plage_surface[1])
                        if plage_pieces is not None:
                            masque &= (
                                comparables["nombre_pieces_principales"].isna()
                                | comparables["nombre_pieces_principales"].between(
                                    plage_pieces[0], plage_pieces[1])
                            )
                        if types_choisis:
                            masque &= comparables["type_local"].isin(types_choisis)
                        if communes_choisies:
                            masque &= comparables["nom_commune"].isin(communes_choisies)
                        if sources_choisies:
                            masque &= comparables["source"].isin(sources_choisies)
                        comparables_filtres = comparables[masque]

                with map_placeholder:
                    st.subheader("Vues du bien")
                    render_geo_views(geo["latitude"], geo["longitude"], radius_m=radius_utilise)

                if comparables.empty:
                    st.caption(
                        "Aucune transaction DVF comparable trouvée, même après "
                        "élargissement automatique jusqu'à 1000 m / 15 ans."
                    )
                else:
                    if resultat_auto["elargi"]:
                        st.info(
                            f"🔍 Recherche élargie automatiquement à {radius_utilise:.0f} m "
                            f"/ {since_years_utilise} ans (au lieu de {radius_comparables:.0f} m "
                            f"/ {since_years} ans) car moins de {max_comparables} ventes "
                            "**DVF (2021+) récentes** avaient été trouvées avec les réglages "
                            "initiaux — Cerema DVF+ peut déjà satisfaire ce nombre à lui seul "
                            "sans que ça arrête l'élargissement, le DVF récent étant priorisé "
                            "(voir infobulle du curseur ci-dessus)."
                        )
                    total = resume_comparables["total"]
                    par_source = resume_comparables["total_par_source"]
                    st.caption(
                        f"**{total} bien(s) trouvé(s) au total** dans ce rayon/cette "
                        f"période (affichage limité aux {max_comparables} premiers, "
                        f"triés par {'date' if tri_comparables == 'date' else 'distance'}) — "
                        + " · ".join(f"{v} via {k}" for k, v in par_source.items())
                    )

                    if comparables_filtres.empty:
                        st.caption("Aucun résultat ne correspond aux filtres sélectionnés.")
                    else:
                        # Prix moyen par type calculé sur les données FILTRÉES (pas
                        # sur l'ensemble complet) pour bien réagir aux filtres choisis.
                        prix_par_type = (
                            comparables_filtres.groupby("type_local")["prix_m2"]
                            .mean().round(0).to_dict()
                        )
                        if prix_par_type:
                            cols_prix = st.columns(len(prix_par_type))
                            for col, (type_bien, prix_moy) in zip(cols_prix, prix_par_type.items()):
                                col.metric(f"€/m² moyen — {type_bien}", f"{prix_moy:,.0f} €")

                        st.dataframe(comparables_filtres, use_container_width=True)
                        if len(comparables_filtres) < len(comparables):
                            st.caption(
                                f"{len(comparables_filtres)}/{len(comparables)} lignes "
                                "affichées après filtrage (le tri des colonnes reste "
                                "possible en tapant sur leur en-tête)."
                            )
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
            batiment = core.get_batiment_bdnb(geo["label"], geo.get("code_insee"))
        if batiment is None or not batiment.get("annee_construction"):
            st.caption(
                "Année de construction non trouvée automatiquement pour ce "
                "bâtiment (donnée parfois manquante ou non encore croisée "
                "dans la BDNB)."
            )
            with st.expander("🔧 Diagnostic technique (BDNB)"):
                st.caption(
                    "Le champ 'annee_construction' et l'ancienne méthode par "
                    "bbox ont été vérifiés en conditions réelles le "
                    "19/07/2026 (millésime 2026-02.a) : le champ existe bien, "
                    "mais le chemin '/bbox' n'existe plus dans le schéma "
                    "actuel, et sa géométrie est en Lambert93, pas en "
                    "latitude/longitude. La recherche se fait donc "
                    "maintenant par correspondance d'adresse — ce diagnostic "
                    "sert à voir pourquoi ELLE échoue pour cette adresse "
                    "précise, si c'est le cas."
                )
                import requests as _requests_diag
                import json as _json_diag

                _rapport_bdnb = [
                    f"Adresse : {geo['label']}",
                    f"code_insee : {geo.get('code_insee')}",
                    "",
                ]

                if not geo.get("code_insee"):
                    st.warning("Aucun code_insee disponible pour cette adresse — recherche impossible.")
                    _rapport_bdnb.append("Aucun code_insee disponible — recherche impossible.")
                else:
                    target_numero, target_rue = core._parse_address_number_street(geo["label"])
                    _mots_generiques_diag = {
                        "rue", "avenue", "boulevard", "chemin", "impasse", "allee",
                        "place", "square", "route", "sentier", "quai", "cours",
                        "villa", "cite", "passage", "voie", "chaussee",
                    }
                    _tokens_rue_diag = [t for t in target_rue.split() if len(t) > 2]
                    _tokens_distinctifs_diag = (
                        [t for t in _tokens_rue_diag if t not in _mots_generiques_diag]
                        or _tokens_rue_diag
                    )
                    mot_pivot_diag = max(_tokens_distinctifs_diag, key=len) if _tokens_distinctifs_diag else ""
                    url_diag = "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet"
                    params_diag = {
                        "code_commune_insee": f"eq.{geo['code_insee']}",
                        "libelle_adr_principale_ban": f"ilike.*{target_numero}*{mot_pivot_diag}*",
                        "select": (
                            "batiment_groupe_id,annee_construction,"
                            "libelle_adr_principale_ban,l_libelle_adr,l_parcelle_id"
                        ),
                        "limit": 200,
                    }
                    st.write(f"URL : {url_diag}")
                    st.write(
                        f"Filtre : code_commune_insee=eq.{geo['code_insee']} "
                        f"ET libelle_adr_principale_ban=ilike.*{target_numero}*{mot_pivot_diag}*"
                    )
                    st.caption(
                        "10 résultats semble être un plafond serveur strict, quel "
                        "que soit le filtre appliqué (constaté même filtré sur "
                        "commune + numéro seul, sur Maisons-Alfort) — le mot le "
                        "plus distinctif du nom de rue est donc filtré côté "
                        "serveur en plus, pour rester sous ce plafond."
                    )
                    _rapport_bdnb += [
                        f"URL : {url_diag}",
                        f"Filtre : code_commune_insee=eq.{geo['code_insee']} "
                        f"ET libelle_adr_principale_ban=ilike.*{target_numero}*{mot_pivot_diag}*",
                    ]
                    try:
                        reponse_diag = _requests_diag.get(url_diag, params=params_diag, timeout=15)
                        st.write(f"Statut HTTP : {reponse_diag.status_code}")
                        _rapport_bdnb.append(f"Statut HTTP : {reponse_diag.status_code}")
                        try:
                            data_diag = reponse_diag.json()
                            if isinstance(data_diag, list):
                                st.write(f"Nombre de bâtiments renvoyés : {len(data_diag)}")
                                _rapport_bdnb.append(
                                    f"Nombre de bâtiments renvoyés : {len(data_diag)}"
                                )
                                st.write(f"Numéro/rue recherchés (normalisés) : {target_numero} / {target_rue}")
                                _rapport_bdnb.append(
                                    f"Numéro/rue recherchés (normalisés) : {target_numero} / {target_rue}"
                                )
                                echantillon = []
                                for r in data_diag:
                                    adresses = list(r.get("l_libelle_adr") or [])
                                    if r.get("libelle_adr_principale_ban"):
                                        adresses.append(r["libelle_adr_principale_ban"])
                                    for adr in adresses:
                                        echantillon.append({
                                            "adresse_bdnb": adr,
                                            "annee_construction": r.get("annee_construction"),
                                        })
                                if echantillon:
                                    st.write(
                                        f"Adresses renvoyées par le filtre "
                                        f"(pour comparaison visuelle) :"
                                    )
                                    st.json(echantillon[:20])
                                    _rapport_bdnb.append("Adresses renvoyées par le filtre :")
                                    _rapport_bdnb.append(
                                        _json_diag.dumps(echantillon[:20], ensure_ascii=False, indent=2)
                                    )
                                else:
                                    st.warning(
                                        f"Aucune adresse de cette commune ne contient le "
                                        f"numéro '{target_numero}' — le bâtiment n'est "
                                        "probablement pas dans la BDNB pour cette adresse."
                                    )
                                    _rapport_bdnb.append(
                                        f"Aucune adresse ne contient le numéro '{target_numero}'."
                                    )
                            else:
                                st.warning("Réponse de forme inattendue :")
                                st.json(data_diag)
                                _rapport_bdnb.append("Réponse de forme inattendue :")
                                _rapport_bdnb.append(_json_diag.dumps(data_diag, ensure_ascii=False, indent=2))
                        except ValueError:
                            st.error("Réponse non-JSON :")
                            st.code(reponse_diag.text[:2000])
                            _rapport_bdnb.append("Réponse non-JSON :")
                            _rapport_bdnb.append(reponse_diag.text[:2000])
                    except _requests_diag.exceptions.RequestException as e:
                        st.error(f"Échec de l'appel réseau : {e}")
                        _rapport_bdnb.append(f"Échec de l'appel réseau : {e}")

                st.divider()
                st.markdown("**📋 Copier ce diagnostic**")
                texte_complet_bdnb = "\n".join(_rapport_bdnb)
                st.code(texte_complet_bdnb, language="text")
                st.download_button(
                    "⬇️ Télécharger ce diagnostic (.txt)",
                    texte_complet_bdnb,
                    file_name=f"diagnostic_bdnb_{geo['label'][:30].replace(' ', '_')}.txt",
                    use_container_width=True,
                )
        else:
            b = batiment["brut"]
            st.metric("Année de construction estimée", batiment["annee_construction"])
            st.caption(
                "Source : BDNB (Base de Données Nationale des Bâtiments, CSTB) — "
                "croise cadastre, BDTopo IGN et Fichiers fonciers. Peut être une "
                "estimation statistique plutôt qu'une donnée certaine selon les "
                "bâtiments — à vérifier si un doute important."
            )

            # Fiche bâtiment complémentaire — champs BDNB au-delà de l'année
            # de construction, quand renseignés (beaucoup de bâtiments n'ont
            # qu'une partie de ces champs remplis selon les sources croisées
            # disponibles pour eux).
            cb1, cb2, cb3 = st.columns(3)
            if b.get("nb_log"):
                cb1.metric("Logements dans le bâtiment", int(b["nb_log"]))
            if b.get("nb_niveau"):
                cb2.metric("Niveaux", int(b["nb_niveau"]))
            if b.get("hauteur_mean"):
                cb3.metric("Hauteur moyenne", f"{b['hauteur_mean']:.0f} m")

            details_bati = []
            if b.get("mat_mur_txt"):
                details_bati.append(f"**Murs :** {b['mat_mur_txt'].capitalize()}")
            if b.get("mat_toit_txt"):
                details_bati.append(f"**Toiture :** {b['mat_toit_txt'].capitalize()}")
            if b.get("usage_principal_bdnb_open"):
                details_bati.append(f"**Usage principal :** {b['usage_principal_bdnb_open']}")
            if b.get("alea_argile"):
                details_bati.append(f"**Aléa retrait-gonflement des argiles :** {b['alea_argile']}")
            if b.get("valeur_fonciere_m2_residentiel_rel_commune"):
                details_bati.append(
                    "**Valeur foncière/m² relative à la commune :** "
                    f"{b['valeur_fonciere_m2_residentiel_rel_commune']:.2f} "
                    "(1,0 = moyenne communale)"
                )
            if b.get("denomination_monument_historique"):
                dist = b.get("distance_monument_historique")
                dist_txt = f", à {dist:.0f} m" if dist else ""
                details_bati.append(
                    f"**Monument historique à proximité :** "
                    f"{b['denomination_monument_historique']}{dist_txt}"
                )
            if b.get("contrainte_urbanisme_ac1") or b.get("zone_plu_bati_patrimonial"):
                details_bati.append(
                    "**⚠️ Contrainte patrimoniale/urbanisme** signalée pour ce "
                    "bâtiment — à vérifier auprès du service urbanisme de la commune."
                )
            if b.get("quartier_prioritaire") or b.get("nom_qp"):
                details_bati.append(
                    f"**Quartier prioritaire de la ville (QPV) :** {b.get('nom_qp') or 'oui'}"
                )
            if b.get("batenr_favorabilite_solaire_thermique"):
                pot = b.get("batenr_potentiel_prod_solaire_thermique_annuelle")
                pot_txt = f" (potentiel estimé : {pot:.1f} kWh/m²/an)" if pot else ""
                details_bati.append(f"**Favorable au solaire thermique**{pot_txt}")
            if b.get("surface_emprise_sol"):
                details_bati.append(f"**Emprise au sol :** {b['surface_emprise_sol']:.0f} m²")

            if details_bati:
                st.markdown("  \n".join(details_bati))
                st.caption(
                    "Champs BDNB complémentaires, non tous systématiquement "
                    "renseignés selon les bâtiments — absence d'une ligne ci-"
                    "dessus = donnée non disponible pour ce bâtiment, pas "
                    "forcément une absence réelle (ex. pas de contrainte "
                    "patrimoniale)."
                )

            # Bâtiments alternatifs trouvés à la même adresse texte (cas
            # fréquent : bâtiment d'angle, plusieurs entrées d'une même
            # résidence...) — montrés plutôt qu'ignorés silencieusement.
            autres = [c for c in batiment.get("candidats", []) if c is not b]
            if autres:
                with st.expander(
                    f"🏘️ {len(autres)} autre(s) bâtiment(s) trouvé(s) à cette "
                    "même adresse"
                ):
                    st.caption(
                        "Peut correspondre à un bâtiment voisin (angle de rue), "
                        "une autre entrée de la même résidence, ou une adresse "
                        "partagée par plusieurs constructions distinctes."
                    )
                    lignes_autres = []
                    for c in autres:
                        lignes_autres.append({
                            "adresse_bdnb": c.get("libelle_adr_principale_ban"),
                            "annee_construction": c.get("annee_construction"),
                            "nb_log": c.get("nb_log"),
                            "nb_niveau": c.get("nb_niveau"),
                            "identifiant_bdnb": c.get("batiment_groupe_id"),
                        })
                    st.dataframe(pd.DataFrame(lignes_autres), use_container_width=True)

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
