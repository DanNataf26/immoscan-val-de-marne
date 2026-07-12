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
  probable, comparables, DPE, potentiel caché (cadastre/PLU/Géorisques), et
  score vs marché. La commune du score se resynchronise automatiquement à
  chaque nouvelle recherche d'adresse, tout en restant modifiable manuellement
  entre-temps.
- **📋 Scorer plusieurs annonces** : import d'un CSV pour scorer un lot
  d'annonces d'un coup (usage différent : plusieurs biens, pas une recherche
  d'adresse précise).
- **📊 Explorer le marché** : parcourir les prix de référence par commune,
  sans adresse précise.

## Module Potentiel caché (implémenté)

Section de l'onglet `🔍 Rechercher un bien`, active une fois qu'une adresse a
été recherchée. Elle combine :

- **Liens de vérification manuelle** vers Cadastre, Géoportail de l'Urbanisme,
  Géorisques et Pappers Immo (carte interactive gratuite).
- **Cadastre automatique** (API Carto IGN) : parcelle, section, numéro,
  contenance (surface officielle du terrain).
- **Zone PLU automatique** (API Carto IGN — module GPU) : libellé de zone
  (ex. 'UD', 'UC'), destination dominante.
- **Risques automatiques** (API Géorisques) : rapport de risques naturels et
  technologiques au point recherché.
- **Estimation indicative de réserve foncière** : compare la contenance de la
  parcelle à la surface bâtie que vous renseignez, pour donner un ordre de
  grandeur de réserve foncière théorique — à but de priorisation uniquement.

**Pappers Immo n'est pas intégré automatiquement** : son API nécessite une clé
payante au-delà de 100 crédits gratuits (elle est très complète : DVF,
cadastre, DPE, permis de construire — voir immobilier.pappers.fr). Le lien
proposé permet une vérification manuelle gratuite sans clé.

## Limites importantes

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
