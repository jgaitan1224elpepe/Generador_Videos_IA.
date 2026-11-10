import asyncio
import json
import logging
import re
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import edge_tts
from app.config import FFMPEG_BIN, FFPROBE_BIN, AVAILABLE_VOICES
from app.models.project import Project, Scene
from app.services.storage import ensure_project_dirs

logger = logging.getLogger(__name__)

TICKS_PER_SECOND = 10_000_000.0


def clean_narration_text(raw_text: str) -> str:
    """
    Elimina acotaciones visuales entre corchetes [...] para que el motor TTS
    solo pronuncie el guion hablado manteniendo respiración y pausas naturales.
    """
    if not raw_text:
        return ""
    cleaned = re.sub(r"\[.*?\]", " ", raw_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else raw_text.strip()


def get_audio_duration_ffprobe(audio_file_path: Path) -> float:
    """Obtiene la duración exacta en segundos de un archivo de audio usando ffprobe."""
    if not audio_file_path.exists():
        return 0.0
    try:
        cmd = [
            FFPROBE_BIN,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_file_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        dur = float(result.stdout.strip())
        return round(dur, 3)
    except Exception as e:
        logger.warning(f"Error midiendo duración de audio con ffprobe en {audio_file_path}: {e}")
        size = audio_file_path.stat().st_size
        return round(max(3.0, size / 16000), 2)


# =====================================================================
# PATRÓN STRATEGY + FACTORY PARA MOTORES TTS
# =====================================================================

class BaseTTSEngine(ABC):
    """Interfaz base abstracta para cualquier proveedor de síntesis de voz."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str,
        speed: float = 1.0,
        pitch: float = 0.0
    ) -> List[Dict]:
        """
        Sintetiza el texto en 'output_path' y retorna una lista de diccionarios
        con marcas de tiempo por palabra: [{"word": str, "start": float, "end": float}].
        """
        pass


class EdgeTTSEngine(BaseTTSEngine):
    """
    Motor activo gratuito basado en Microsoft Azure Neural Voices (edge-tts).
    Genera locución continua en una sola toma y extrae marcas de tiempo nativas
    mediante eventos WordBoundary.
    """

    async def _synthesize_async(
        self,
        text: str,
        output_path: Path,
        voice_id: str,
        speed: float = 1.10,
        pitch: float = -2.0
    ) -> List[Dict]:
        # Si el proyecto viene con valores neutros antiguos (1.0 / 0.0), aplicar tuning dinámico (+10% / -2Hz)
        effective_speed = 1.10 if abs(float(speed) - 1.0) < 0.01 else float(speed)
        effective_pitch = -2.0 if abs(float(pitch) - 0.0) < 0.1 else float(pitch)

        speed_pct = int(round((effective_speed - 1.0) * 100))
        rate_str = f"+{speed_pct}%" if speed_pct >= 0 else f"{speed_pct}%"

        pitch_pct = int(round(effective_pitch))
        pitch_str = f"+{pitch_pct}Hz" if pitch_pct >= 0 else f"{pitch_pct}Hz"

        logger.info(f"[EdgeTTSEngine] voice={voice_id}, rate={rate_str}, pitch={pitch_str}")

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_id,
            rate=rate_str,
            pitch=pitch_str,
            boundary="WordBoundary"
        )

        audio_chunks: List[bytes] = []
        word_boundaries: List[Dict] = []

        async for chunk in communicate.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk_type == "WordBoundary":
                start_sec = float(chunk.get("offset", 0)) / TICKS_PER_SECOND
                dur_sec = float(chunk.get("duration", 0)) / TICKS_PER_SECOND
                end_sec = start_sec + max(0.05, dur_sec)
                word_text = str(chunk.get("text", "")).strip()
                if word_text:
                    word_boundaries.append({
                        "word": word_text,
                        "start": round(start_sec, 3),
                        "end": round(end_sec, 3),
                    })

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"".join(audio_chunks))
        return word_boundaries

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str,
        speed: float = 1.0,
        pitch: float = 0.0
    ) -> List[Dict]:
        return asyncio.run(
            self._synthesize_async(
                text=text,
                output_path=output_path,
                voice_id=voice_id,
                speed=speed,
                pitch=pitch
            )
        )


class PiperTTSEngine(BaseTTSEngine):
    """Stub preparado para síntesis neural offline local con Piper TTS."""

    def synthesize(self, text: str, output_path: Path, voice_id: str, speed: float = 1.0, pitch: float = 0.0) -> List[Dict]:
        raise NotImplementedError("El motor Piper TTS está preparado como extensión futura.")


class ElevenLabsTTSEngine(BaseTTSEngine):
    """Stub preparado para futura integración comercial con ElevenLabs API."""

    def synthesize(self, text: str, output_path: Path, voice_id: str, speed: float = 1.0, pitch: float = 0.0) -> List[Dict]:
        raise NotImplementedError("El motor ElevenLabs está preparado para una fase futura.")


class OpenAITTSEngine(BaseTTSEngine):
    """Stub preparado para futura integración comercial con OpenAI Audio API."""

    def synthesize(self, text: str, output_path: Path, voice_id: str, speed: float = 1.0, pitch: float = 0.0) -> List[Dict]:
        raise NotImplementedError("El motor OpenAI TTS está preparado para una fase futura.")


class TTSFactory:
    """Fábrica centralizada para instanciar el motor de voz configurado."""

    _ENGINES = {
        "edge_tts": EdgeTTSEngine,
        "piper": PiperTTSEngine,
        "elevenlabs": ElevenLabsTTSEngine,
        "openai": OpenAITTSEngine,
    }

    @classmethod
    def get_engine(cls, provider: str = "edge_tts") -> BaseTTSEngine:
        engine_cls = cls._ENGINES.get(provider.lower(), EdgeTTSEngine)
        return engine_cls()


# =====================================================================
# FLUJO DE "UNA SOLA TOMA" (SINGLE-TAKE) Y SINCRONIZACIÓN DE ESCENAS
# =====================================================================

def _align_scene_tokens_with_boundaries(
    scenes: List[Scene],
    raw_boundaries: List[Dict],
    total_duration: float
) -> Tuple[List[Dict], List[Tuple[float, float]]]:
    """
    Alinea las palabras con signos de puntuación de cada escena contra las marcas
    de tiempo WordBoundary del audio continuo en una sola toma.
    Retorna:
      1. Lista global de palabras con {"word", "start", "end", "scene_order"}
      2. Lista de tuplas (scene_start_sec, scene_end_sec) para cada escena.
    """
    scene_tokens_list: List[List[str]] = []
    for s in scenes:
        cleaned = clean_narration_text(s.script_text)
        tokens = [t for t in cleaned.split(" ") if t.strip()]
        scene_tokens_list.append(tokens)

    total_script_words = sum(len(toks) for toks in scene_tokens_list)
    if total_script_words == 0:
        return [], [(0.0, total_duration) for _ in scenes]

    all_aligned_words: List[Dict] = []
    scene_spans: List[Tuple[float, float]] = []

    # Si tenemos suficientes WordBoundaries de Edge-TTS, mapeamos proporcionalmente por índice
    n_bounds = len(raw_boundaries)
    global_word_idx = 0

    for scene_idx, (scene, tokens) in enumerate(zip(scenes, scene_tokens_list)):
        if not tokens:
            prev_end = scene_spans[-1][1] if scene_spans else 0.0
            scene_spans.append((prev_end, prev_end + 3.0))
            continue

        scene_words: List[Dict] = []
        for tok in tokens:
            if n_bounds > 0:
                # Mapear índice de palabra del guion al índice correspondiente en raw_boundaries
                b_idx = min(n_bounds - 1, int(round((global_word_idx / max(1, total_script_words - 1)) * (n_bounds - 1)))) if total_script_words > 1 else 0
                w_start = raw_boundaries[b_idx]["start"]
                w_end = raw_boundaries[b_idx]["end"]
            else:
                # Fallback proporcional si no hubiera eventos WordBoundary
                ratio_start = global_word_idx / total_script_words
                ratio_end = (global_word_idx + 1) / total_script_words
                w_start = round(total_duration * ratio_start, 3)
                w_end = round(total_duration * ratio_end, 3)

            item = {
                "word": tok,
                "start": w_start,
                "end": max(w_start + 0.06, w_end),
                "scene_order": scene.order,
            }
            scene_words.append(item)
            all_aligned_words.append(item)
            global_word_idx += 1

        # Asegurar monotonía estricta dentro de la escena
        for i in range(1, len(scene_words)):
            if scene_words[i]["start"] < scene_words[i - 1]["start"]:
                scene_words[i]["start"] = scene_words[i - 1]["end"]
            if scene_words[i]["end"] <= scene_words[i]["start"]:
                scene_words[i]["end"] = round(scene_words[i]["start"] + 0.08, 3)

        s_start = 0.0 if scene_idx == 0 else scene_spans[-1][1]
        s_end = total_duration if scene_idx == len(scenes) - 1 else round(scene_words[-1]["end"] + 0.08, 3)
        s_end = min(total_duration, max(s_start + 1.5, s_end))
        scene_spans.append((round(s_start, 3), round(s_end, 3)))

    return all_aligned_words, scene_spans


def _slice_scene_preview_audio(
    full_audio_path: Path,
    dest_scene_audio: Path,
    start_sec: float,
    end_sec: float
) -> None:
    """
    Extrae sin pérdida y de forma instantánea el segmento de audio de una escena
    a partir del archivo maestro de una sola toma para previsualización en la UI.
    """
    duration = max(1.0, round(end_sec - start_sec, 3))
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-ss", str(round(start_sec, 3)),
        "-t", str(duration),
        "-i", str(full_audio_path),
        "-c", "copy",
        str(dest_scene_audio)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # Fallback con recodificación rápida si el corte en frame MP3 requiere re-encode
        cmd_re = [
            FFMPEG_BIN,
            "-y",
            "-ss", str(round(start_sec, 3)),
            "-t", str(duration),
            "-i", str(full_audio_path),
            "-c:a", "libmp3lame",
            "-q:a", "2",
            str(dest_scene_audio)
        ]
        subprocess.run(cmd_re, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def generate_all_scene_audios(project: Project, provider: str = "edge_tts") -> None:
    """
    Genera la narración completa del proyecto en UNA SOLA TOMA continua ('full_narration.mp3')
    para garantizar respiración, entonación y prosodia natural de nivel documental.
    Además, guarda las marcas de tiempo exactas en 'word_timings.json' y sincroniza
    las duraciones y previsualizaciones de cada escena.
    """
    if not project.scenes:
        return

    paths = ensure_project_dirs(project.id)
    engine = TTSFactory.get_engine(provider)

    # 1. Construir el guion continuo limpio inyectando puntuación de pausa de respiración entre escenas
    cleaned_fragments: List[str] = []
    for scene in project.scenes:
        frag = clean_narration_text(scene.script_text)
        if frag:
            frag = frag.rstrip(" ,;:")
            if not frag.endswith((".", "!", "?", "…")):
                frag = frag + "."
            cleaned_fragments.append(frag)

    # Unir escenas con punto y seguido + pausa natural para forzar respiración orgánica en la toma única
    full_continuous_text = "  ".join(cleaned_fragments)

    # Limpiar archivos de audio versionados previos para no acumular archivos ni usar caché
    for old_mp3 in paths["audio"].glob("full_narration_*.mp3"):
        try:
            old_mp3.unlink()
        except Exception:
            pass
    for old_scene_mp3 in paths["audio"].glob("scene_*_*.mp3"):
        try:
            old_scene_mp3.unlink()
        except Exception:
            pass

    active_voice = project.settings.voice_id or project.voice or "es-ES-AlvaroNeural"
    project.voice = active_voice
    project.settings.voice_id = active_voice

    ts = int(time.time() * 1000)
    voice_tag = active_voice.replace("-", "")
    versioned_full_audio = paths["audio"] / f"full_narration_{voice_tag}_{ts}.mp3"
    full_audio_file = paths["audio"] / "full_narration.mp3"
    timings_file = paths["audio"] / "word_timings.json"

    # 2. Sintetizar en una sola toma continua y capturar WordBoundaries nativos
    logger.info(f"[TTS Single-Take] Sintetizando proyecto {project.id} con voz: {active_voice} (speed={project.settings.voice_speed}, pitch={project.settings.voice_pitch})")
    raw_boundaries = engine.synthesize(
        text=full_continuous_text,
        output_path=versioned_full_audio,
        voice_id=active_voice,
        speed=project.settings.voice_speed,
        pitch=project.settings.voice_pitch,
    )

    # Mantener copia en full_narration.mp3 estándar para compatibilidad con video_service y subtitle_service
    try:
        import shutil
        shutil.copyfile(versioned_full_audio, full_audio_file)
    except Exception as e:
        logger.warning(f"No se pudo copiar full_narration.mp3 base: {e}")

    # 3. Medir duración exacta total del archivo maestro con ffprobe
    total_audio_duration = get_audio_duration_ffprobe(versioned_full_audio)
    if total_audio_duration <= 0 and raw_boundaries:
        total_audio_duration = round(raw_boundaries[-1]["end"] + 0.25, 3)

    # 4. Alinear palabras y calcular el segmento temporal exacto de cada escena
    aligned_words, scene_spans = _align_scene_tokens_with_boundaries(
        scenes=project.scenes,
        raw_boundaries=raw_boundaries,
        total_duration=total_audio_duration,
    )

    # Guardar marcas de tiempo exactas para el motor de subtítulos .ass
    timings_payload = {
        "project_id": project.id,
        "voice_id": active_voice,
        "total_duration": total_audio_duration,
        "updated_at": time.time(),
        "words": aligned_words,
    }
    timings_file.write_text(json.dumps(timings_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # 5. Actualizar duración exacta de cada escena y cortar clip de previsualización UI con nombre único
    for scene, (s_start, s_end) in zip(project.scenes, scene_spans):
        scene_dur = max(2.5, round(s_end - s_start, 2))
        scene.duration = scene_dur

        versioned_scene_file = paths["audio"] / f"scene_{scene.id}_{voice_tag}_{ts}.mp3"
        _slice_scene_preview_audio(versioned_full_audio, versioned_scene_file, s_start, s_end)

        scene.audio_path = f"/projects/{project.id}/audio/scene_{scene.id}_{voice_tag}_{ts}.mp3"
        scene.audio_status = "ready"

    project.full_audio_path = f"/projects/{project.id}/audio/full_narration_{voice_tag}_{ts}.mp3"
    project.settings.audio_mode = "ai"
    project.status = "audio_ready"


def synthesize_scene_audio(project: Project, scene: Scene) -> str:
    """
    Cuando el usuario solicita regenerar una escena desde la UI, regenera la toma
    continua maestra para no romper la prosodia ni la sincronización global, y retorna
    la ruta del audio de esa escena.
    """
    generate_all_scene_audios(project)
    return scene.audio_path or ""


def sync_custom_audio_to_scenes(project: Project, custom_audio_file: Path) -> None:
    """
    Sincroniza un archivo de audio propio cargado por el usuario con las escenas del proyecto,
    distribuyendo la duración total proporcionalmente según el conteo de palabras de cada escena.
    """
    total_duration = get_audio_duration_ffprobe(custom_audio_file)
    if total_duration <= 0 or not project.scenes:
        return

    total_words = sum(max(1, len(clean_narration_text(s.script_text).split())) for s in project.scenes)

    for scene in project.scenes:
        scene_words = max(1, len(clean_narration_text(s.script_text).split()))
        scene_ratio = scene_words / total_words
        scene.duration = round(total_duration * scene_ratio, 2)
        scene.audio_status = "custom_synced"

    project.settings.audio_mode = "custom"
    project.status = "audio_ready"
