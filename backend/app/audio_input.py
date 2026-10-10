"""Récupération et validation de l'audio : fichier importé ou lien YouTube."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np

from .transcription import SAMPLE_RATE

STORAGE = Path(os.environ.get("TAB_STORAGE", Path(tempfile.gettempdir()) / "tablatures-audio"))
MAX_UPLOAD_MB = int(os.environ.get("TAB_MAX_UPLOAD_MB", "40"))
MAX_DURATION_S = int(os.environ.get("TAB_MAX_DURATION_S", "600"))
KEEP_SECONDS = 3 * 3600
ALLOWED_EXT = {".mp3", ".wav"}

YOUTUBE_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com/(watch\?.*v=|shorts/|embed/)|youtu\.be/)[\w-]{11}",
    re.IGNORECASE,
)


class InputError(ValueError):
    """Erreur affichable telle quelle à l'utilisateur."""


def new_job() -> tuple[str, Path]:
    cleanup()
    job_id = uuid.uuid4().hex
    d = STORAGE / job_id
    d.mkdir(parents=True, exist_ok=True)
    return job_id, d


def job_audio(job_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        return None
    p = STORAGE / job_id / "audio.wav"
    return p if p.exists() else None


def cleanup() -> None:
    if not STORAGE.exists():
        return
    now = time.time()
    for d in STORAGE.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > KEEP_SECONDS:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def decode_to_wav(src: Path, dest: Path) -> np.ndarray:
    """Décode n'importe quel format lisible en WAV mono 22 050 Hz."""
    import librosa
    import soundfile as sf

    try:
        y, _ = librosa.load(str(src), sr=SAMPLE_RATE, mono=True, duration=MAX_DURATION_S + 1)
    except Exception as exc:
        raise InputError(
            "Impossible de lire ce fichier audio. Vérifiez qu'il s'agit bien d'un MP3 ou WAV valide."
        ) from exc
    if y.size == 0:
        raise InputError("Le fichier audio est vide.")
    duration = y.size / SAMPLE_RATE
    if duration > MAX_DURATION_S:
        raise InputError(f"Le morceau dépasse la durée maximale de {MAX_DURATION_S // 60} minutes. "
                         "Coupez un extrait plus court.")
    if duration < 1.0:
        raise InputError("Le morceau est trop court (moins d'une seconde).")
    if float(np.max(np.abs(y))) < 1e-3:
        raise InputError("Le fichier semble silencieux : aucun son détecté.")
    sf.write(str(dest), y, SAMPLE_RATE, subtype="PCM_16")
    return y


def save_upload(filename: str, data: bytes, job_dir: Path) -> np.ndarray:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise InputError("Format non pris en charge. Importez un fichier .mp3 ou .wav.")
    if len(data) == 0:
        raise InputError("Le fichier importé est vide.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise InputError(f"Fichier trop volumineux (maximum {MAX_UPLOAD_MB} Mo).")
    src = job_dir / f"source{ext}"
    src.write_bytes(data)
    return decode_to_wav(src, job_dir / "audio.wav")


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_RE.match(url.strip()))


def youtube_status() -> dict:
    try:
        import yt_dlp  # noqa: F401
        has_ytdlp = True
    except ImportError:
        has_ytdlp = False
    has_ffmpeg = shutil.which("ffmpeg") is not None
    return {"available": has_ytdlp and has_ffmpeg, "yt_dlp": has_ytdlp, "ffmpeg": has_ffmpeg}


def download_youtube(url: str, job_dir: Path) -> tuple[np.ndarray, str]:
    """Télécharge la piste audio d'une vidéo avec yt-dlp.

    À n'utiliser que pour des contenus dont l'utilisateur a les droits
    (sa propre vidéo, licence libre, autorisation de l'auteur).
    """
    url = url.strip()
    if not is_youtube_url(url):
        raise InputError("Ce lien ne ressemble pas à une vidéo YouTube (ex. https://www.youtube.com/watch?v=…).")
    status = youtube_status()
    if not status["yt_dlp"]:
        raise InputError("Le module yt-dlp n'est pas installé sur le serveur. Importez plutôt un fichier audio.")
    if not status["ffmpeg"]:
        raise InputError("FFmpeg n'est pas installé : impossible de décoder l'audio YouTube. "
                         "Installez FFmpeg (voir README) ou importez un fichier MP3/WAV.")
    import yt_dlp

    def too_long(info, *, incomplete):
        d = info.get("duration")
        if d and d > MAX_DURATION_S:
            return f"Vidéo trop longue ({int(d) // 60} min)"
        return None

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "youtube.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "match_filter": too_long,
        "max_filesize": MAX_UPLOAD_MB * 4 * 1024 * 1024,
        "socket_timeout": 20,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        msg = str(exc)
        raise InputError(
            "Impossible de récupérer l'audio de cette vidéo (vidéo privée, protégée, restreinte, "
            "ou YouTube bloque le téléchargement). Importez plutôt un fichier MP3 ou WAV dont vous avez les droits."
            + (f" Détail : {msg[:200]}" if msg else "")
        ) from exc
    files = [p for p in job_dir.glob("youtube.*") if p.suffix not in (".part", ".ytdl")]
    if not files:
        raise InputError("La vidéo a été ignorée (trop longue ou sans piste audio). Importez un fichier audio.")
    y = decode_to_wav(files[0], job_dir / "audio.wav")
    return y, (info or {}).get("title") or "Vidéo YouTube"
