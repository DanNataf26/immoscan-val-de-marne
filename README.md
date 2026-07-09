# ImmoScan France — Prototype v3

Application Streamlit personnelle pour repérer des opportunités immobilières à partir des ventes réelles DVF.

## Fonctionnalités principales

- France entière, département par département.
- Téléchargement DVF et construction d'une référence prix/m² par commune.
- Recherche par adresse avec géocodage, carte, vue satellite/Google Earth et Street View.
- Historique probable des ventes du bien ou de l'adresse.
- Comparables DVF proches, filtrés par type de bien.
- DPE ADEME lorsque disponible.
- Score opportunité basé sur décote/surcote, comparables, historique et DPE.
- **Nouveau v3 : module Potentiel caché** : cadastre, PLU, Pappers Immo, Géorisques, estimation de réserve foncière et surface théorique créable.

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Déploiement Streamlit Cloud

Fichier principal à indiquer :

```text
app.py
```

Fichiers nécessaires dans GitHub :

```text
app.py
immo_scan.py
requirements.txt
README.md
mes_annonces_exemple.csv
```

## Utilisation recommandée

1. Choisir le département dans la barre latérale.
2. Télécharger les données DVF.
3. Construire la référence de prix.
4. Aller dans `Adresse + vues` pour analyser un bien.
5. Aller dans `Potentiel caché` pour analyser la parcelle, le PLU et la réserve foncière.

## Module Potentiel caché v3

Ce module génère des liens directs vers :

- Cadastre
- Géoportail de l'Urbanisme / PLU
- Pappers Immobilier
- Géorisques
- Google satellite

Il calcule ensuite :

- surface terrain connue ou saisie manuellement ;
- surface bâtie actuelle ;
- emprise actuelle ;
- surface théorique encore créable selon l'emprise PLU saisie ;
- valeur théorique de la surface créée selon les comparables locaux ;
- score foncier indicatif sur 100.

## Limites importantes

Le score foncier est indicatif. Il ne remplace pas une vérification juridique ou technique. Le PLU, les servitudes, ABF, copropriété, stationnement, accès pompiers, réseaux, carrières, inondation ou contraintes de voisinage peuvent réduire ou annuler le potentiel réel.

Le module Pappers Immo est proposé comme lien de vérification manuelle. Une intégration automatique complète nécessiterait un accès API adapté.
