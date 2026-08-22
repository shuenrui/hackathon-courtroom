"""Local transcription helpers for short YouTube demos and MP4 files."""
import pathlib
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_model = None

def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


def validate_youtube_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")):
        raise ValueError("demo video must be an HTTPS YouTube URL")


def transcribe_youtube(url: str, timeout: int = 120) -> str:
    """Download a short YouTube video's audio and transcribe it locally."""
    validate_youtube_url(url)
    with tempfile.TemporaryDirectory() as tmp:
        audio = f"{tmp}/audio.wav"
        yt_dlp = shutil.which("yt-dlp") or str(REPO_ROOT / ".venv" / "bin" / "yt-dlp")
        cmd = [
            yt_dlp,
            "--no-playlist",
            "--match-filter", "duration <= 300",
            "--max-filesize", "100M",
            "--socket-timeout", "20",
            "--retries", "2",
            "--remote-components", "ejs:github",
            "--js-runtimes", "node",
            "--extractor-args", "youtube:player_client=android",
            "-x", "--audio-format", "wav", "--audio-quality", "0",
            "-o", audio,
            url,
        ]
        subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
        wavs = list(pathlib.Path(tmp).glob("*.wav"))
        if not wavs:
            raise RuntimeError("yt-dlp produced no wav")
        wav = wavs[0]
        model = get_model()
        segments, _info = model.transcribe(str(wav), language=None, beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text


def transcribe_mp4(path: str) -> str:
    """Local MP4 file -> transcript."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = f"{tmp}/audio.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ar", "16000", "-ac", "1", wav], check=True, timeout=30)
        model = get_model()
        segments, _info = model.transcribe(wav, beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
