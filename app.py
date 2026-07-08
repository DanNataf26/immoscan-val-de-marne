#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ImmoScan Val-de-Marne — Application locale (Streamlit)
========================================================
Interface graphique pour le prototype de détection d'opportunités
immobilières sous-évaluées, basé sur les données DVF (DGFiP).

Lancement :
    streamlit run app.py

Cette app réutilise directement les fonctions de immo_scan.py (même dossier).
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import immo_scan as core  # noqa: E402


st.set_page_config(page_title="ImmoScan Val-de-Marne", page_icon="🏠", layout="wide")

DEPARTEMENTS_IDF = {
    "94 - Val-de-Marne": "94",
    "75 - Paris": "75",
    "92 - Hauts-de-Seine": "92",
    "93 - Seine-Saint-Denis": "93",
    "91 - Essonne": "91",
    "77 - Seine-et-Marne": "77",
    "78 - Yvelines": "78",
    "95 - Val-d'Oise": "95",
}

ANNEES_DISPONIBLES = [2021, 2022, 2023, 2024, 2025]


# ----------------------------------------------------------------------------
# Chargement des données de référence (mis en cache pour la session)
# ----------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_reference(dept: str):
    ref_path = core.OUTPUT_DIR / f"reference_{dept}.csv"
    trend_path = core.OUTPUT_DIR / f"tendance_{dept}.csv"
    ref = pd.read_csv(ref_path) if ref_path.exists() else None
    trend = pd.read_csv(trend_path) if trend_path.exists() else None
    return ref, trend


def reference_exists(dept: str) -> bool:
    return (core.OUTPUT_DIR / f"reference_{dept}.csv").exists()


# ----------------------------------------------------------------------------
# Barre latérale : préparation des données
# ----------------------------------------------------------------------------

st.sidebar.title("🏠 ImmoScan")
st.sidebar.caption("Détection d'opportunités immobilières — prototype personnel")

dept_label = st.sidebar.selectbox("Département", list(DEPARTEMENTS_IDF.keys()), index=0)
dept = DEPARTEMENTS_IDF[dept_label]

annees = st.sidebar.multiselect(
    "Années DVF à utiliser", ANNEES_DISPONIBLES,
    default=ANNEES_DISPONIBLES,
    help="Les données DVF sont mises à jour ~2 fois par an par la DGFiP.",
)

st.sidebar.divider()
st.sidebar.markdown("**Préparation des données**")

if st.sidebar.button("1️⃣ Télécharger les données DVF", use_container_width=True):
    with st.spinner("Téléchargement en cours (peut prendre quelques minutes)..."):
        core.download(dept, annees)
    st.sidebar.success("Téléchargement terminé.")

if st.sidebar.button("2️⃣ Construire la référence de prix", use_container_width=True):
    with st.spinner("Calcul de la référence de prix/m²..."):
        try:
            core.run_reference(dept, annees)
            load_reference.clear()
            st.sidebar.success("Référence construite.")
        except SystemExit as e:
            st.sidebar.error(str(e))

st.sidebar.divider()
if reference_exists(dept):
    st.sidebar.success(f"✅ Référence disponible pour le {dept}")
else:
    st.sidebar.warning(
        f"⚠️ Pas encore de référence pour le {dept}. "
        "Lancez les étapes 1 et 2 ci-dessus."
    )

st.sidebar.caption(
    "Source des données : DVF (Demandes de Valeurs Foncières), DGFiP, open data."
)


# ----------------------------------------------------------------------------
# Corps de l'application
# ----------------------------------------------------------------------------

st.title("ImmoScan — Détection d'opportunités immobilières")
st.caption(
    "Maisons, appartements et immeubles en Île-de-France · "
    "Comparaison au marché réel à partir des transactions DVF"
)

tab_address, tab_score, tab_batch, tab_explore = st.tabs(
    ["📍 Recherche par adresse", "🔎 Scorer un bien", "📋 Scorer plusieurs annonces",
     "📊 Explorer le marché"]
)

ref, trend = load_reference(dept) if reference_exists(dept) else (None, None)


# --- Onglet 0 : recherche par adresse (géocodage + DPE + comparables) ------
with tab_address:
    st.markdown(
        "Tapez une adresse : la commune est détectée automatiquement, et l'app "
        "cherche les ventes réelles comparables à proximité ainsi qu'un éventuel "
        "DPE enregistré à cette adresse."
    )
    address_input = st.text_input(
        "Adresse", placeholder="Ex : 12 rue de la Paix, Vincennes"
    )

    if st.button("Rechercher", type="primary") and address_input:
        with st.spinner("Géocodage de l'adresse..."):
            geo = core.geocode_address(address_input)

        if geo is None:
            st.error(
                "Adresse non reconnue par l'API Adresse (BAN). Vérifiez "
                "l'orthographe ou essayez une formulation plus simple."
            )
        else:
            st.success(f"📍 {geo['label']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Commune détectée", geo["commune"])
            c2.metric("Code postal", geo["code_postal"])
            c3.metric("Code INSEE", geo["code_insee"])

            st.session_state["adresse_commune_detectee"] = geo["commune"]
            st.session_state["adresse_lat"] = geo["latitude"]
            st.session_state["adresse_lon"] = geo["longitude"]

            if ref is None:
                st.info(
                    "Construisez la référence de prix (barre latérale) pour "
                    "voir aussi les ventes comparables à proximité."
                )
            else:
                st.markdown("**Ventes comparables à proximité (rayon 500 m)**")
                try:
                    comparables = core.find_comparables(
                        dept, geo["latitude"], geo["longitude"], radius_m=500
                    )
                    if comparables.empty:
                        st.caption(
                            "Aucune transaction DVF trouvée dans un rayon de 500 m. "
                            "Essayez d'élargir la recherche en modifiant le rayon "
                            "dans le code, ou la zone est peu couverte par le DVF."
                        )
                    else:
                        st.dataframe(comparables, use_container_width=True)
                except SystemExit as e:
                    st.warning(str(e))

            st.markdown("**DPE enregistré à cette adresse (si disponible)**")
            with st.spinner("Recherche DPE (ADEME)..."):
                dpe = core.find_dpe(address_input, geo.get("code_postal"))
            if dpe is None or dpe.empty:
                st.caption(
                    "Aucun DPE trouvé automatiquement pour cette adresse. Cela "
                    "peut vouloir dire qu'il n'y en a pas, ou que l'adresse "
                    "enregistrée au DPE diffère légèrement (vérifiez manuellement "
                    "sur observatoire-dpe-audit.ademe.fr en cas de doute)."
                )
            else:
                st.dataframe(dpe, use_container_width=True)

    st.divider()
    if st.session_state.get("adresse_commune_detectee"):
        st.caption(
            f"Commune détectée disponible pour le scoring : "
            f"**{st.session_state['adresse_commune_detectee']}** — "
            "allez dans l'onglet 'Scorer un bien' pour l'utiliser."
        )


# --- Onglet 1 : scorer un bien unique ---------------------------------------
with tab_score:
    if ref is None:
        st.info("Construisez d'abord la référence de prix via la barre latérale.")
    else:
        communes_dispo = sorted(ref["nom_commune"].unique())
        types_dispo = sorted(ref["type_local"].unique())

        detected = st.session_state.get("adresse_commune_detectee")
        default_idx = communes_dispo.index(detected) if detected in communes_dispo else 0

        col1, col2 = st.columns(2)
        with col1:
            commune = st.selectbox("Commune", communes_dispo, index=default_idx)
            type_local = st.selectbox("Type de bien", types_dispo)
        with col2:
            surface = st.number_input("Surface (m²)", min_value=1.0, value=90.0, step=1.0)
            prix = st.number_input("Prix affiché (€)", min_value=1000.0, value=450_000.0,
                                    step=1000.0)

        if st.button("Analyser ce bien", type="primary"):
            result = core.score_property(commune, type_local, surface, prix, dept=dept)

            if "erreur" in result:
                st.error(result["erreur"])
            else:
                ecart = result["ecart_pct"]
                diagnostic = result["diagnostic"]

                color = "🟢" if ecart <= -15 else "🟡" if ecart < 5 else \
                        "🟠" if ecart < 15 else "🔴"

                st.subheader(f"{color} {diagnostic}")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Prix/m² de l'annonce", f"{result['prix_m2_annonce']:,} €")
                c2.metric(f"Référence {commune}", f"{result['prix_m2_reference_commune']:,} €")
                c3.metric("Écart au marché", f"{ecart:+.1f} %")
                c4.metric("Transactions de référence", result["nb_transactions_reference"])

                st.caption(
                    "⚠️ Ce score compare uniquement le prix au m². Il ne tient pas "
                    "compte de l'état du bien, des travaux nécessaires ni du DPE."
                )


# --- Onglet 2 : scorer un lot d'annonces ------------------------------------
with tab_batch:
    if ref is None:
        st.info("Construisez d'abord la référence de prix via la barre latérale.")
    else:
        st.markdown(
            "Déposez un CSV avec les colonnes : `adresse, commune, type_local, "
            "surface, prix`"
        )
        exemple = pd.DataFrame([
            {"adresse": "12 rue de la Paix", "commune": "Vincennes",
             "type_local": "Maison", "surface": 90, "prix": 480000},
        ])
        st.download_button(
            "Télécharger un exemple de CSV",
            exemple.to_csv(index=False),
            file_name="exemple_annonces.csv",
        )

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
                    res = core.score_property(
                        r["commune"], r["type_local"], r["surface"], r["prix"], dept=dept
                    )
                    res["adresse"] = r.get("adresse", "")
                    results.append(res)

                out = pd.DataFrame(results)
                if "ecart_pct" in out.columns:
                    out = out.sort_values("ecart_pct")

                st.dataframe(out, use_container_width=True)
                st.download_button(
                    "Télécharger les résultats",
                    out.to_csv(index=False),
                    file_name="opportunites_scorees.csv",
                )


# --- Onglet 3 : explorer le marché ------------------------------------------
with tab_explore:
    if ref is None:
        st.info("Construisez d'abord la référence de prix via la barre latérale.")
    else:
        type_filter = st.selectbox(
            "Type de bien à afficher", sorted(ref["type_local"].unique()), key="explore_type"
        )
        subset = ref[ref["type_local"] == type_filter].sort_values(
            "prix_m2_median", ascending=False
        )

        st.markdown(f"**Prix médian au m² par commune — {type_filter}**")
        st.bar_chart(subset.set_index("nom_commune")["prix_m2_median"])
        st.dataframe(subset, use_container_width=True)

        if trend is not None:
            st.markdown("**Évolution des prix (entre la première et la dernière année chargée)**")
            trend_subset = trend[trend["type_local"] == type_filter]
            if "evolution_pct" in trend_subset.columns:
                trend_subset = trend_subset.sort_values("evolution_pct", ascending=False)
            st.dataframe(trend_subset, use_container_width=True)
            st.caption(
                "Une commune avec une évolution forte peut signaler une zone en "
                "rattrapage — à croiser avec vos propres critères d'investissement."
            )
