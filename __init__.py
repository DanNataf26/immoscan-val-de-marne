"""
Composant Streamlit fait maison : recherche d'adresse avec suggestions en
direct pendant la frappe, sans dépendance tierce fragile (voir README pour
le contexte : streamlit-searchbox causait un plantage systématique sur
Streamlit Community Cloud).

Fonctionne en pur HTML/JS : le JavaScript appelle directement l'API Adresse
du gouvernement (BAN) depuis le navigateur, et renvoie l'adresse choisie à
Python via le protocole natif des composants Streamlit (window.postMessage).
Aucun serveur de développement, aucun build JavaScript nécessaire.
"""
import os
import streamlit.components.v1 as components

_component_dir = os.path.dirname(os.path.abspath(__file__))

address_search_component = components.declare_component(
    "address_search",
    path=_component_dir,
)
