# Évaluation de la justesse des notes — protocole et résultats

Ce dossier mesure la qualité de la transcription **sur de vrais enregistrements annotés par des
humains**. Les fichiers audio ne sont pas dans le dépôt ; `python -m evaluation.fetch_data` les
télécharge dans `evaluation/data/` (ignoré par git).

## 1. Audit du moteur v1 (avant modification)

Parcours d'un fichier : import → décodage WAV mono 22 050 Hz (librosa) → **Basic Pitch 0.4.0**
(Spotify, réseau ICASSP 2022, version ONNX, polyphonique) avec `onset=0.5`, `frame=0.3`, durée min.
80 ms → tempo `librosa.beat.beat_track` → au moment de la tablature : suppression des harmoniques
(ratio 0,8), filtre de niveau (durée/amplitude), mélodie « skyline », quantification, choix de
l'harmonica, conversion trou/souffle/bend (programmation dynamique).

Erreurs mesurées sur l'harmonica réel (partie test, ±50 ms) : **F1 0,435**, 69 erreurs d'octave,
85 notes de référence fragmentées, 42 fusions ; avec accompagnement, F1 0,313.

Causes identifiées (chacune vérifiée par une mesure) :

| Cause | Preuve | Correction v2 |
|---|---|---|
| **Latence du modèle** : attaques en retard | retard médian +30 ms (harmonica), +24 ms (voix), +14 ms (sax) | décalage −25 ms (calibré sur dev) : +0,09 de F1 à lui seul |
| **Notes courtes perdues** | 25 % des notes réelles d'harmonica durent < 100 ms ; v1 imposait 80 ms et un seuil de trame 0,3 | durée min. 35 ms, seuil de trame 0,25 (balayage sur dev) |
| **Notes impossibles** (D3, E2… sous la tessiture) prises pour des notes, et masquant de vraies notes lors du filtrage des harmoniques | erreurs d'octave vers le grave | tessiture de l'instrument appliquée si « l'enregistrement est joué avec cet instrument » |
| **Harmoniques fantômes** (octave, douzième) | confusions +12/+19 ; ex. « Hey Jude » : C6, E6, A6 faibles au-dessus de la mélodie | ratio 0,6 (dev), la note écartée est conservée comme « alternative » |
| **Attaques fragmentées** | fragment de 50-90 ms suivi de la même hauteur | fusion si fragment ≤ 100 ms et écart ≤ 30 ms (les vraies répétitions, séparées par un coup de langue, sont gardées : test dédié) |
| **Écart en cents faux** : Basic Pitch décale ses « pitch bends » d'un pas (+33 cents) | médiane +33 cents sur sons accordés ET sur notes réelles (annotations : 0) | décalage corrigé ; l'écart sert à signaler les hauteurs ambiguës |
| **Quantification** : sur collision, le fragment de glissando d'un bend remplaçait la note tenue | test bend (−3' au lieu de −3'') | on garde la note tenue seulement dans ce cas précis (garder « la plus longue » partout était moins juste sur dev) |

La **conversion en tablature n'était pas en cause** : sur les 2 050 notes jouées par les
harmonicistes, 2 045 (99,8 %) existent sur l'harmonica réellement utilisé dans les tables Richter
(84 % naturelles, 9 % bends ½ ton, 5 % bends plus profonds, 1 % overblows) ; les 5 restantes sont
sous la tessiture physique de cet harmonica (erreurs probables d'annotation). Et à partir des notes de
référence, la conversion est cohérente à 100 % (le trou indiqué produit la hauteur annoncée).

## 2. Données de référence

| Jeu | Contenu | Référence | Licence / usage |
|---|---|---|---|
| `harmonica` | 43 extraits d'**harmonica diatonique solo** réels (C, G, Bb), 9 min, 2 050 notes | annotation manuelle début/fin/fréquence, Lins et al., *Automatic transcription of diatonic harmonica recordings*, ICASSP 2019 — [dépôt](https://github.com/filipemlins/Automatic-Music-Transcription-Harmonica) | pas de licence explicite : évaluation locale uniquement, rien n'est redistribué |
| `harmonica_mix` | les mêmes extraits mélangés (−6 dB) à un **accompagnement réel** piano/basse/batterie (Filosax) | annotation harmonica inchangée | idem + Filosax (usage recherche) |
| `vocadito` | voix a cappella réelle avec **vibrato** (extrait mirdata) | notes annotées par un humain (annotateur A1) | CC BY 4.0 |
| `filosax`, `filosax_mix` | **saxophone** ténor réel (anche), seul et avec accompagnement réel | notes annotées (Filosax, extraits de test mirdata) | usage recherche |

Exclu : `OhSusanapart2GaitaC` (annotation corrompue : hauteurs négatives dans la source).

**Séparation dev/test par morceau** (`datasets.DEV_SONGS`) : tous les seuils ont été choisis sur
*dev* (23 extraits) ; les chiffres annoncés sont ceux de *test* (20 extraits d'autres morceaux),
jamais utilisés pour régler quoi que ce soit. Vocadito et Filosax sont entièrement en test.

**Réserve sur les références** : sur certains extraits en G (« Ode to Joy »), l'annotation indique G4
là où le spectre montre une énergie nettement plus forte à G3 (−15 dB contre −25 dB) : l'annotation
semble décalée d'une octave. Les références n'ont **pas** été modifiées ; un F1 « classe de hauteur »
(octave ignorée) est donné en complément.

## 3. Métriques (`metrics.py`, `tab_eval.py`)

* **Transcription** (conventions mir_eval) : une note est juste si sa hauteur MIDI est exacte et son
  début à **±50 ms** (standard MIREX) ; ±100 ms est aussi rapporté car les annotations manuelles de
  notes très courtes ont une précision limitée. Précision, rappel, F1, F1 avec fin (±20 % de la durée).
* Erreurs : octave (±12/±19/±24 d'une note de référence au même instant), demi-ton/ton (souvent un
  bend), parasites (aucune note de référence), fragmentation, fusion (notes répétées perdues).
* **Mélodie** : la ligne transmise à la tablature comparée à la ligne la plus aiguë de la référence.
* **Tablature** (±100 ms), séparée de la transcription : *conversion cohérente* (le trou/bend indiqué
  produit bien la hauteur annoncée, mesuré aussi en partant des notes humaines « reference→tab »),
  *précision des notes de la tablature* (une note réellement jouée à ce moment ?), *rappel mélodie*,
  taux de notes jouables au niveau, taux de notes incertaines et justesse des notes incertaines/sûres.

## 4. Méthodes comparées (sur dev)

| Méthode | F1 harmonica dev ±50 ms | F1 ±100 ms | Décision |
|---|---|---|---|
| Basic Pitch, réglages v1 | 0,395 | 0,606 | référence « avant » |
| Basic Pitch, meilleurs seuils seuls | 0,433 | 0,638 | gain modeste : le réglage seul ne suffit pas |
| **pYIN** (librosa, fenêtre 46 ms) + segmentation (mélodie) | 0,232 | 0,415 | **rejeté** : rappel 0,35 ; le jeu réel d'harmonica est rapide et souvent en accords |
| Basic Pitch + nettoyage v2 (sans tessiture) | 0,545 | 0,687 | retenu |
| + tessiture de l'harmonica utilisé | 0,551 | 0,695 | retenu (option) |
| + arrondi de hauteur par les cents | 0,547 | 0,682 | rejeté (neutre) |
| + fusion des glissandos de bend | ≤ 0,542 | ≤ 0,680 | rejeté (dégrade) |
| Suppression des notes peu sûres | baisse du F1 | — | rejeté : elles sont **signalées incertaines** |
| Mélodie : « la plus forte » / « la plus aiguë » / skyline pondérée | 0,450 / 0,455 / **0,461** | | skyline pondérée conservée |

Non intégrés, faute de bénéfice démontrable ou de compatibilité : modèles lourds (MT3, Omnizart,
CREPE — TensorFlow/PyTorch de plusieurs centaines de Mo) et séparation de sources (Demucs, ~1 Go,
non testable ici). La méthode PLCA spécifique à l'harmonica des auteurs du jeu de données (MATLAB) n'a
pas été portée. Basic Pitch reste le moteur : il est le meilleur des moteurs mesurés ici.

## 5. Résultats avant/après — partie TEST (jamais vue au réglage)

### Transcription (notes, ±50 ms, octave exacte)

| Jeu | v1 F1 | **v2 F1** | v1 err. octave | v2 err. octave | v1 ±100 ms | v2 ±100 ms | v1 classe de hauteur | v2 classe de hauteur |
|---|---|---|---|---|---|---|---|---|
| Harmonica solo (1 044 notes) | 0,435 | **0,587** | 69 | **12** | 0,614 | **0,723** | 0,454 | **0,598** |
| Harmonica + accompagnement | 0,313 | **0,539** | 83 | **21** | 0,437 | **0,665** | 0,331 | **0,547** |
| Voix (vocadito, 59 notes) | 0,455 | **0,491** | 0 | 0 | | | | |
| Saxophone solo (23 notes) | **0,610** | 0,531 | 0 | 0 | | | | |
| Saxophone + accompagnement | 0,316 | **0,336** | 17 | 11 | | | | |

Mélodie transmise à la tablature (±50 ms) : harmonica 0,436 → **0,451**, harmonica + accompagnement
0,318 → **0,427**, voix 0,483 → **0,510**, saxophone 0,632 → 0,557.

### Tablature d'harmonica (±100 ms, harmonica réellement utilisé)

| Jeu | Niveau | Justesse des notes affichées v1 → **v2** | F1 v1 → **v2** | Jouables v2 | Incertaines v2 | Justesse si incertaine / si sûre |
|---|---|---|---|---|---|---|
| Solo | débutant | 0,843 → **0,881** | 0,611 → **0,625** | 92 % | 1 % | 0,75 / 0,88 |
| Solo | intermédiaire | 0,801 → **0,828** | 0,671 → **0,674** | 96 % | 14 % | 0,61 / 0,86 |
| Solo | avancé | 0,801 → **0,805** | 0,671 → **0,716** | 99,6 % | 27 % | 0,64 / 0,86 |
| Solo | expert | 0,793 → 0,775 | 0,675 → **0,734** | 100 % | 31 % | 0,59 / 0,86 |
| + accomp. | débutant | 0,503 → **0,843** | 0,432 → **0,599** | 91 % | 0 % | — / 0,84 |
| + accomp. | intermédiaire | 0,480 → **0,781** | 0,486 → **0,645** | 95 % | 14 % | 0,55 / 0,82 |
| + accomp. | avancé | 0,480 → **0,746** | 0,486 → **0,678** | 99 % | 31 % | 0,56 / 0,83 |
| + accomp. | expert | 0,462 → **0,718** | 0,496 → **0,690** | 100 % | 36 % | 0,54 / 0,82 |

* Conversion trou/souffle/bend cohérente : **100 %** à tous les niveaux, v1 comme v2.
* À partir des notes humaines (conversion seule), expert : 100 % jouables, rappel mélodie 0,93.
* Choix automatique de l'harmonica (sur notes de référence, expert) : l'harmonica réellement utilisé
  dans 31/43 cas ; dans les 12 autres, l'harmonica proposé joue les **mêmes hauteurs** avec moins de
  bends/overblows (ex. « Hey Jude » joué sur un C avec un overblow, tout naturel sur un G). Il est
  donc présenté comme une **recommandation** ; l'harmonica choisi par l'utilisateur est respecté.
* Expert : la justesse baisse légèrement (0,793 → 0,775) parce que v2 garde plus de notes (rappel
  0,587 → 0,698, accords sur trous voisins) ; les notes douteuses sont signalées.

Fichiers bruts : `results/notes_test.*`, `results/tab_test.*`, `results/notes_dev.*`.

## 6. Limites

* Les notes à ±1-2 demi-tons (bends en cours, glissandos) augmentent (24 → 74 sur test) : v2 détecte
  plus de notes courtes, dont des étapes de bend. Elles sont en partie signalées incertaines.
* Saxophone solo : légère régression (23 notes : 3 notes de différence) ; les seuils ont été réglés
  sur l'harmonica, rien n'a été réglé pour d'autres instruments.
* Tempo : juste sur sons synthétiques, faux sur 3 des 4 extraits réels Filosax (5 s) ; il ne change
  que le découpage en mesures, et il est modifiable dans l'interface.
* Aucune séparation de sources ; sur un morceau complet dense, la mélodie peut être confondue avec
  l'accompagnement (F1 harmonica + accompagnement 0,54 contre 0,59 en solo).
* Évaluation guitare/piano : non faite sur de vrais enregistrements (hors priorité harmonica).

## 7. Relancer

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m evaluation.fetch_data                 # ~2 Go, une seule fois (git requis)
python -m evaluation.run --split test           # transcription, avant/après
python -m evaluation.tab_eval --split test      # tablature d'harmonica par niveau
python -m pytest tests\test_real_recordings.py  # non-régression sur enregistrements réels
```
