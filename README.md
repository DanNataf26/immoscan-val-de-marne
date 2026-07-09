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

## Module Potentiel caché (implémenté)

Onglet dédié, actif une fois qu'une adresse a été recherchée dans l'onglet
`Adresse + vues`. Il combine :

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
