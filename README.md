# ImmoScan France — Prototype v0.1

Outil personnel pour repérer des maisons, appartements et immeubles à fort potentiel de
valorisation ou sous-estimés, sur toute la France, département par département, pour des projets d'investissement patrimonial ou de marchand
de biens.


## Nouveautés v0.2

- Extension à toute la France : sélection de n'importe quel département métropolitain ou DROM dans la barre latérale.
- Détection automatique du département à partir d'une adresse saisie.
- Historique probable des ventes DVF autour du bien recherché.
- Trois vues géographiques pour l'adresse : carte géolocalisée, vue satellite/Google Earth, et vue Google Street View.

⚠️ Pour des raisons de volume, l'application travaille département par département : choisissez le département, téléchargez les DVF, puis construisez la référence.

## Principe

1. On télécharge les vraies transactions immobilières (DVF, données
   officielles de la DGFiP, gratuites) des dernières années.
2. On calcule le prix médian au m² par commune et par type de bien
   (maison, appartement, immeuble vendu en bloc).
3. On compare une annonce ou un bien repéré à cette référence pour estimer
   s'il est sous-évalué, dans le marché, ou surévalué.

Ce prototype ne va PAS chercher les annonces en ligne à votre place (voir
"Limites et prochaines étapes" plus bas). Vous lui donnez un bien (à la main
ou via un CSV), il vous dit où il se situe par rapport au marché réel de sa
commune.

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation en application (recommandé)

Une interface graphique locale est disponible via Streamlit :

```bash
streamlit run app.py
```

Cela ouvre une page dans votre navigateur (`http://localhost:8501`), avec :
- une barre latérale pour télécharger les données DVF et construire la
  référence de prix (les étapes 1 et 2 ci-dessous, en un clic) ;
- un onglet **Scorer un bien** pour analyser une adresse précise ;
- un onglet **Scorer plusieurs annonces** pour déposer un CSV et obtenir un
  classement des biens les plus sous-évalués ;
- un onglet **Explorer le marché** avec un graphique des prix/m² par commune
  et les tendances d'évolution.

L'app tourne uniquement sur votre machine — aucune donnée n'est envoyée à un
serveur externe (à part le téléchargement initial depuis data.gouv.fr).

## Utilisation en ligne de commande (alternative)

Les mêmes traitements sont aussi disponibles en CLI, utile pour scripter ou
automatiser :

## Étape 1 — Télécharger les données DVF

```bash
python immo_scan.py download --dept 94 --years 2021 2022 2023 2024 2025
```

Télécharge les fichiers officiels dans `data/`. Vous pouvez élargir à
d'autres départements franciliens plus tard (75, 92, 93, 91, 77, 78, 95) en
changeant `--dept`.

## Étape 2 — Construire la référence de prix

```bash
python immo_scan.py reference --dept 94 --years 2021 2022 2023 2024 2025
```

Génère dans `output/` :
- `reference_94.csv` : prix médian/moyen au m² par commune et type de bien
- `tendance_94.csv` : évolution du prix médian par commune entre la première
  et la dernière année chargée (utile pour repérer les zones en forte hausse)
- `transactions_nettoyees_94.csv` : cache des transactions nettoyées

## Étape 3 — Scorer un bien précis

```bash
python immo_scan.py score --commune "Vincennes" --type Maison --surface 90 --prix 480000
```

Retourne l'écart en % par rapport au prix médian/m² de la commune, et un
diagnostic (sous-évalué / dans le marché / surévalué).

## Nouveau — Recherche par adresse (onglet dédié dans l'app)

Tapez une adresse et l'app :
1. La géocode automatiquement (API Adresse du gouvernement — BAN, gratuite,
   sans clé) pour détecter la commune, le code postal et les coordonnées GPS.
2. Cherche les ventes réelles (DVF) dans un rayon de 500 m — les vraies
   transactions comparables les plus proches, pas des estimations.
3. Cherche un DPE éventuellement enregistré à cette adresse (API ouverte de
   l'ADEME) — étiquette énergie, surface, année si disponible.

Cela nécessite d'avoir construit la référence de prix au préalable (étape 2)
pour avoir le cache de transactions à interroger pour les comparables.

**Limites à connaître** :
- La correspondance DPE se fait par recherche textuelle sur l'adresse ; en
  copropriété, plusieurs lots peuvent partager la même adresse — vérifiez
  toujours manuellement en cas de doute important.
- Le nom exact du jeu de données / des champs sur l'API ADEME peut évoluer :
  si la recherche DPE ne retourne jamais rien, vérifiez le nom du dataset sur
  https://data.ademe.fr/datasets/dpe-v2-logements-existants (bouton API).
- Ces deux fonctionnalités appellent des API externes ; elles nécessitent une
  connexion internet au moment de l'utilisation (contrairement au scoring de
  base, qui fonctionne hors ligne une fois la référence construite).

## Étape 4 — Scorer plusieurs annonces d'un coup

Créez un CSV `mes_annonces.csv` avec les colonnes `adresse,commune,type_local,surface,prix`
(voir `mes_annonces_exemple.csv` fourni), puis :

```bash
python immo_scan.py batch --input mes_annonces.csv --dept 94
```

Génère `output/opportunites_scorees.csv`, trié des biens les plus sous-évalués
aux plus surévalués.

## Limites connues de ce prototype

- **Pas d'état du bien** : le score ne connaît ni l'état ni les travaux
  nécessaires. Deux biens au même prix/m² peuvent être dans un état très
  différent. À enrichir avec le DPE (base ADEME, open data) dans une v2.
- **Immeubles reconstitués par approximation** : les ventes en bloc sont
  détectées via plusieurs lots "Appartement" sous le même identifiant de
  mutation. À affiner avec le champ `nombre_lots` du fichier source si vous
  avez besoin de plus de précision.
- **Décalage temporel** : les données DVF ont quelques mois de retard sur le
  marché réel (mise à jour 2x/an, avril et octobre).
- **Pas de collecte automatique d'annonces** : pour l'usage personnel, vous
  alimentez le CSV à la main à partir de ce que vous repérez (SeLoger,
  LeBonCoin, notaires, etc.). Avant d'automatiser cette collecte (scraping),
  vérifiez les CGU des portails — la plupart l'interdisent explicitement.
  C'est le point le plus sensible à sécuriser avant toute commercialisation.

## Obtenir un lien permanent, accessible depuis votre téléphone

Pour avoir une URL fixe (type `https://immoscan-vdm.streamlit.app`) sans
jamais lancer quoi que ce soit sur votre ordinateur, vous pouvez déployer
gratuitement sur **Streamlit Community Cloud**. Tout se fait depuis un
navigateur, aucune ligne de commande :

1. Créez un compte gratuit sur [github.com](https://github.com) si vous n'en
   avez pas.
2. Créez un nouveau repository (par ex. `immoscan-val-de-marne`), et via
   l'interface web de GitHub ("Add file" → "Upload files"), déposez tous les
   fichiers de ce dossier (`app.py`, `immo_scan.py`, `requirements.txt`).
3. Allez sur [share.streamlit.io](https://share.streamlit.io), connectez-vous
   avec votre compte GitHub.
4. Cliquez sur "New app", sélectionnez votre repository, la branche `main`,
   et indiquez `app.py` comme fichier principal.
5. Cliquez sur "Deploy". Au bout de quelques minutes, vous obtenez une URL
   publique que vous pouvez ouvrir depuis votre téléphone, en un clic, sans
   jamais rien installer.

**À savoir** : au premier lancement, l'app devra télécharger les données DVF
(bouton "Télécharger les données DVF" dans la barre latérale) — cela prend
quelques minutes une seule fois. Pensez aussi à définir la visibilité du
repository GitHub en "Private" si vous ne souhaitez pas rendre le code public
(l'app peut rester utilisable en privé sur Streamlit Cloud selon l'offre).

## Prochaines étapes possibles

- Intégrer le DPE (ADEME) pour pondérer le score par la performance
  énergétique et son potentiel de correction.
- Intégrer le PLU / cadastre pour détecter les fonciers sous-exploités
  (potentiel de division ou d'extension).
- Étendre à toute l'Île-de-France (`--dept 75 92 93 91 77 78 95`).
- Ajouter une carte interactive des écarts de prix par quartier.
