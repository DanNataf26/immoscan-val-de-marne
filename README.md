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

1. Choisir le département dans la barre latérale — les données DVF se
   téléchargent et la référence de prix se construit **automatiquement** en
   arrière-plan (plus besoin de cliquer sur des boutons "Télécharger" / "Construire").
2. Aller dans `🔍 Rechercher un bien` : tapez une adresse, et toutes les
   informations disponibles (historique, comparables, DPE, potentiel caché,
   score vs marché) s'affichent à la suite sur la même page.

La première préparation pour un département prend une à quelques minutes
(téléchargement des fichiers DVF officiels). Elle ne se refait pas tant que
le département et les années sélectionnées ne changent pas. Un bouton
"🔄 Forcer un nouveau téléchargement + recalcul" reste disponible dans
"Options avancées" de la barre latérale si vous voulez rafraîchir les
données (ex. après une mise à jour DVF par la DGFiP).

## Structure de l'application

Trois onglets, organisés par type d'usage :

- **🔍 Rechercher un bien** : le flux principal. Une seule recherche
  d'adresse, puis tout s'affiche à la suite — vues géographiques, historique
  probable, comparables, DPE, puis une section unique **"Analyser ce bien"**
  qui combine score vs marché et potentiel caché (une seule saisie de
  surface/prix, un seul bouton). La commune/type/surface se resynchronisent
  automatiquement à chaque nouvelle recherche d'adresse, tout en restant
  modifiables manuellement entre-temps.
- **📋 Scorer plusieurs annonces** : import d'un CSV pour scorer un lot
  d'annonces d'un coup (usage différent : plusieurs biens, pas une recherche
  d'adresse précise).
- **📊 Explorer le marché** : parcourir les prix de référence par commune,
  sans adresse précise.

## Section "Analyser ce bien" (score marché + potentiel caché fusionnés)

Une seule saisie (surface + prix optionnel) alimente les deux analyses,
affichées l'une après l'autre au clic sur "Analyser ce bien" :

**Score vs marché** (nécessite un prix) :
- Écart % par rapport au prix médian/m² de la commune
- **Note DPE qualitative** : si un DPE a été trouvé pour l'adresse, une note
  contextuelle s'affiche (bon DPE → prime probable ; DPE F/G → décote et
  travaux probables) — volontairement qualitatif, pas un ajustement chiffré
  du prix (les données DVF ne permettent pas de calibrer un coefficient fiable).

**Potentiel caché** (nécessite juste la surface) :
- **Liens de vérification manuelle** vers Cadastre, Géoportail de l'Urbanisme,
  Géorisques et Pappers Immo (carte interactive gratuite).
- **Cadastre automatique** (API Carto IGN) : parcelle, section, numéro,
  contenance (surface officielle du terrain — additionnée si plusieurs
  parcelles adjacentes sont détectées, ex. maison + jardin sur des parcelles
  séparées).
- **Zone PLU automatique** (API Carto IGN — module GPU) : libellé de zone
  (ex. 'UD', 'UC'), destination dominante.
- **Transports en commun à proximité** (OpenStreetMap/Overpass API) : gares,
  stations de métro/RER/tramway les plus proches avec distance — gratuit,
  sans clé, couverture très bonne en Île-de-France.
- **Risques automatiques** (API Géorisques) : rapport de risques naturels et
  technologiques au point recherché.
- **Estimation indicative de réserve foncière** : compare la contenance de la
  parcelle à la surface bâtie renseignée, pour donner un ordre de grandeur de
  réserve foncière théorique — à but de priorisation uniquement.

**Pappers Immo n'est pas intégré automatiquement** : son API nécessite une clé
payante au-delà de 100 crédits gratuits (elle est très complète : DVF,
cadastre, DPE, permis de construire — voir immobilier.pappers.fr). Le lien
proposé permet une vérification manuelle gratuite sans clé.

**Piste non retenue pour l'instant** : les permis de construire récents à
proximité (signal de dynamisme d'un quartier) nécessiteraient l'API Sitadel
(data.gouv.fr) ou Pappers Immo — à explorer plus tard si utile.

## Limites importantes

**Suggestions automatiques pendant la frappe : composant maison (`st_address_search/`).**
`streamlit-searchbox` provoquait un plantage systématique (`Segmentation
fault`) sur Streamlit Community Cloud, avant même le démarrage du serveur —
testé avec plusieurs versions de Streamlit (1.38.0 et 1.47.1), sans succès.
À la place, l'app utilise un composant Streamlit fait maison, en HTML/JS pur
(pas de dépendance tierce, pas de build JavaScript) : le navigateur appelle
directement l'API Adresse du gouvernement pendant la frappe, et renvoie
l'adresse choisie à Python via le protocole natif des composants Streamlit
(`window.postMessage`). Voir `st_address_search/index.html`.

**Point de vigilance non vérifié en conditions réelles** : ce composant
suppose que l'API Adresse (`api-adresse.data.gouv.fr`) autorise les appels
directs depuis un navigateur (CORS). Cela n'a pas pu être confirmé dans
l'environnement de développement (pas d'accès réseau navigateur). Si les
suggestions ne s'affichent jamais et qu'un message d'erreur apparaît sous le
champ de recherche, c'est probablement la cause — utilisez alors la
recherche manuelle repliée juste en dessous, qui fonctionne indépendamment
(elle passe par le serveur Python, pas par le navigateur).

L'estimation de réserve foncière est indicative et grossière. Elle ne
remplace ni la lecture du règlement de zone PLU complet (hauteur autorisée,
emprise au sol maximale, reculs, coefficient de biotope...), ni un certificat
d'urbanisme officiel demandé en mairie. Le PLU, les servitudes, l'avis de
l'Architecte des Bâtiments de France, la copropriété, le stationnement,
l'accès pompiers, les réseaux, ou des risques naturels peuvent réduire ou
annuler le potentiel réel.

Les fonctions cadastre/PLU/Géorisques appellent des API publiques externes ;
elles n'ont pas pu être testées en conditions réelles au moment de l'écriture
(pas d'accès réseau dans l'environnement de développement). La logique suit
la documentation officielle de ces API, mais à vérifier au premier usage
réel — leurs schémas de réponse évoluent de temps en temps. Chaque fonction
échoue silencieusement plutôt que de faire planter l'app en cas de souci.
