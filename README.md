# TabMaker — tablatures à partir d'un morceau

Application web qui transforme un fichier audio (MP3/WAV) ou un lien YouTube en **tablature** pour
**harmonica diatonique** (priorité), **harmonica chromatique**, **guitare** et **piano**, avec 4 niveaux
(débutant, intermédiaire, avancé, expert).

Parcours : importer → choisir l'instrument et le niveau → **Générer ma tablature** → écouter et jouer.

## Fonctionnement

```
audio (MP3/WAV/YouTube)
   │  backend/app/audio_input.py     validation, décodage en WAV mono 22 kHz, yt-dlp
   ▼
transcription (notes + confiance, cents, provenance)
   │  backend/app/transcription.py   modèle Basic Pitch (Spotify), version ONNX, latence corrigée + tempo
   ▼
nettoyage des erreurs de détection
   │  backend/app/note_cleanup.py    tessiture, fragments d'attaque, harmoniques fantômes, confiance
   ▼
préparation selon le niveau
   │  backend/app/music.py           simplification par niveau, mélodie ou accords, quantification
   ▼
conversion en tablature
      backend/app/instruments/*.py   un module par instrument (doigté optimisé par programmation dynamique)
```

* La **transcription** (audio → notes) et la **conversion** (notes → tablature) sont séparées : changer
  d'instrument, de niveau, de tonalité d'harmonica ou de tempo recalcule la tablature instantanément sans
  réanalyser l'audio.
* Le modèle utilisé est [Basic Pitch](https://github.com/spotify/basic-pitch) (réseau de neurones de
  transcription audio → MIDI). Aucune note n'est inventée : chaque note de la tablature vient du modèle, et
  les notes non jouables sont **signalées** (orange / « ? ») au lieu d'être cachées ou remplacées.

### Harmonica diatonique (10 trous, Richter)
* `4` = souffler trou 4, `-4` = aspirer, `'` = bend d'½ ton (`-3''` = bend d'un ton), `8'` = bend soufflé,
  `4o` / `-7o` = overblow / overdraw.
* Tonalités G, Ab, A, Bb, B, C, Db, D, Eb, E, F, F#. En mode **Automatique**, l'application choisit
  l'harmonica (et si besoin une transposition d'octave, signalée) qui rend le plus de notes jouables
  au niveau choisi.
* Techniques autorisées par niveau : débutant = notes naturelles ; intermédiaire = + bends d'½ ton ;
  avancé = tous les bends ; expert = + overblows/overdraws.
* Le trou est choisi pour limiter les déplacements (ex. G4 = `-2` ou `3` selon le contexte).
* Aux niveaux avancé et expert, les **accords** sont gardés s'ils se jouent vraiment : trous voisins,
  même sens de souffle, sans bend — noté `(4 5 6)`. Sinon la note la plus aiguë est gardée et le
  retrait est signalé.
* En mode **Automatique**, l'harmonica proposé est une *recommandation* (le moins de techniques
  difficiles pour les mêmes hauteurs). Choisissez votre harmonica dans la liste pour l'imposer.

### Autres instruments
* **Harmonica chromatique** 12 trous en Do : `5`, `-5`, `5<` (bouton enfoncé).
* **Guitare** accordage standard : tablature 6 lignes + cartes « corde:case ». Accords à partir du
  niveau avancé (cordes distinctes, écart de cases ≤ 4). Cases max : 7 / 12 / 15 / 20 selon le niveau.
* **Piano** : noms des notes (Do4 = do central) et main conseillée (MD/MG).
* Ajouter un instrument : créer une classe dans `backend/app/instruments/` et l'enregistrer dans
  `instruments/__init__.py`.

### Lecture et export
* Lecteur de l'audio original avec vitesse réglable (50 % à 125 %, sans changer la hauteur) et
  surlignage de la note en cours.
* « Écouter la tablature » : synthèse des notes de la tablature au tempo choisi.
* Tempo modifiable si l'estimation automatique est fausse.
* **Confiance** affichée pour chaque note (jauge) ; les notes **incertaines** (son faible ou très court,
  hauteur entre deux demi-tons) sont marquées « ? » en pointillés.
* Cliquer sur une note : détail (confiance, écart en cents, notes concurrentes), **écoute du passage
  isolé** dans l'original, **correction** de la hauteur ou suppression d'une note parasite ; la note
  corrigée apparaît en vert avec « détectée X → corrigée Y », et la tablature est recalculée sans
  réanalyser l'audio (comme pour les changements d'instrument, de tonalité ou de niveau).
* Option « L'enregistrement est joué avec cet instrument » : écarte les notes hors tessiture comme
  erreurs de détection (à décocher pour transcrire une voix ou un autre instrument).
* Export PDF (tablature texte + légende + avertissements).

## Installation sous Windows (PowerShell)

Prérequis :
* **Python 3.11 ou 3.12** (testé avec 3.12) : https://www.python.org/downloads/ (cocher « Add to PATH »).
* **Node.js 20 ou plus** (testé avec 22) : https://nodejs.org/
* *(Optionnel, uniquement pour les liens YouTube)* **FFmpeg** :
  ```powershell
  winget install --id Gyan.FFmpeg -e
  ```
  puis fermer et rouvrir PowerShell.

### 1. Backend (Python)
```powershell
cd backend
py -3.12 -m venv .venv
# Si l'activation est refusée : Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
# Basic Pitch sans ses dépendances : on utilise le modèle ONNX, pas TensorFlow
pip install --no-deps basic-pitch==0.4.0
```

> Pourquoi `--no-deps` ? Avec Python ≥ 3.11, le paquet `basic-pitch` réclame TensorFlow 2.14 (≈ 500 Mo,
> souvent incompatible). Le modèle ONNX fourni dans le paquet fonctionne avec `onnxruntime`, déjà installé
> par `requirements.txt`.

### 2. Frontend (React)
Dans un **second** PowerShell :
```powershell
cd frontend
npm install
```

## Lancer l'application

### Mode simple (un seul serveur)
```powershell
cd frontend
npm run build
cd ..\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Ouvrir http://127.0.0.1:8000

### Mode développement (rechargement automatique)
PowerShell n°1 :
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```
PowerShell n°2 :
```powershell
cd frontend
npm run dev
```
Ouvrir http://localhost:5173 (les appels `/api` sont redirigés vers le port 8000).

## Justesse des notes — mesurée sur de vrais enregistrements

Le moteur est évalué sur **43 enregistrements réels d'harmonica diatonique annotés à la main**
(ICASSP 2019), seuls et avec un accompagnement réel, plus de la voix et du saxophone réels. Résultats
sur la partie *test* (jamais utilisée pour le réglage), F1 des notes à ±50 ms :

| | v1 | v2 |
|---|---|---|
| Harmonica solo | 0,435 | **0,587** (erreurs d'octave 69 → 12) |
| Harmonica + accompagnement | 0,313 | **0,539** |
| Justesse des notes de la tablature, débutant (solo / accompagné) | 0,84 / 0,50 | **0,88 / 0,84** |

Protocole complet, causes des erreurs, méthodes comparées et limites :
[`backend/evaluation/README.md`](backend/evaluation/README.md).

## Tester

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python scripts\make_reference_audio.py   # crée tests\fixtures\*.wav + notes attendues (.json)
python -m pytest -v
```

Les tests couvrent :
* **Chaîne complète sur audio de référence** (notes connues) : le modèle retrouve ≥ 95 % des notes au
  bon moment et à la bonne hauteur ; « Au clair de la lune » (air traditionnel) donne exactement
  `4 4 4 -4 5 -4 4 5 -4 -4 4` sur un harmonica en Do, à tous les niveaux ; une phrase avec bends donne
  `3 -3' -3'' -2 -2'' -1`.
* **Harmonica diatonique** : table de référence écrite à la main pour les 38 notes d'un harmonica en Do
  (C4 → C#7, bends, overblows), nombre de bends par trou, transposition dans les 12 tonalités, et pour
  chaque tonalité, vérification que chaque notation produite sonne bien la note voulue.
* Niveaux (bends signalés hors niveau), notes hors tessiture marquées « ? », harmonica chromatique,
  guitare (cordes/cases exactes, accords sur cordes distinctes, tablature texte), piano.
* API : validation des entrées (format, fichier corrompu, lien invalide, droits non confirmés), audio
  servi, export PDF.

Vous pouvez aussi importer `tests\fixtures\au_clair_de_la_lune.wav` dans l'interface.

Tests sur enregistrements réels (ignorés tant que les données ne sont pas téléchargées) :
```powershell
python -m evaluation.fetch_data      # ~2 Go via git, une seule fois
python -m pytest -v                  # inclut tests\test_real_recordings.py
python -m evaluation.run --split test
python -m evaluation.tab_eval --split test
```

## Limitations connues

* **YouTube** : nécessite FFmpeg, et ne doit servir qu'à des vidéos dont vous avez les droits (case à
  cocher obligatoire). YouTube bloque souvent les téléchargements automatisés ; yt-dlp peut aussi demander
  une mise à jour (`pip install -U yt-dlp`) ou un moteur JavaScript comme Deno
  (`winget install DenoLand.Deno`). En cas d'échec, un message invite à importer un fichier MP3/WAV,
  solution recommandée.
* La transcription reste **imparfaite** : sur l'harmonica réel, environ 6 notes sur 10 sont retrouvées
  exactement (F1 0,59 ; 0,54 avec accompagnement). Les erreurs restantes sont surtout des notes à ½ ton
  ou un ton (bends en cours) et des notes très courtes. Les notes douteuses sont signalées et
  corrigibles ; vérifiez à l'oreille. Aucune séparation de sources (type Demucs) n'est intégrée.
* Le **tempo** est estimé automatiquement et peut être faux (souvent ×1,5 ou ×2) : corrigez-le dans le
  champ « Tempo ». Il n'influence que le découpage en mesures, pas les notes.
* Mesures en 4/4 uniquement ; pas de détection de tonalité du morceau ni de position d'harmonica
  (1re/2e position) affichée.
* Durée maximale : 10 minutes, 40 Mo (variables d'environnement `TAB_MAX_DURATION_S`, `TAB_MAX_UPLOAD_MB`).
* L'analyse tourne sur le CPU (environ 5 à 30 s par morceau) ; les fichiers temporaires sont effacés
  après 3 heures.
