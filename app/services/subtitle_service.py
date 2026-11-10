import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional

from app.config import ASPECT_RATIOS
from app.models.project import Project, Scene
from app.services.storage import ensure_project_dirs
from app.services.tts_service import get_audio_duration_ffprobe

logger = logging.getLogger(__name__)


def escape_ffmpeg_filter_path(path: Path) -> str:
    """
    Escapa una ruta de archivo en Windows 11 para ser utilizada de forma segura
    dentro del filtro de FFmpeg: -vf "ass='C\\:/Users/.../subtitles.ass'"
    1. Convierte todas las barras invertidas (\\) a barras normales (/).
    2. Escapa los dos puntos de la unidad (C: -> C\\:) y comillas simples.
    """
    posix_path = path.resolve().as_posix()
    escaped = posix_path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return escaped


def format_ass_timestamp(seconds: float) -> str:
    """
    Convierte segundos (float) al formato de tiempo de Advanced SubStation Alpha:
    H:MM:SS.cc (horas, minutos, segundos, centésimas).
    """
    seconds = max(0.0, float(seconds))
    total_cs = int(round(seconds * 100))
    hours = total_cs // 360000
    rem = total_cs % 360000
    minutes = rem // 6000
    rem = rem % 6000
    secs = rem // 100
    cs = rem % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def clean_subtitle_text(raw_text: str) -> str:
    """
    Limpia acotaciones escénicas entre corchetes [...] y normaliza espacios
    para que solo aparezca en pantalla el texto efectivamente narrado.
    """
    if not raw_text:
        return ""
    cleaned = re.sub(r"\[.*?\]", " ", raw_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else raw_text.strip()


def escape_ass_text(text: str) -> str:
    """Escapa llaves y barras especiales para no romper tags de formato ASS."""
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _try_whisper_word_timestamps(audio_path: Path, start_offset: float = 0.0) -> Optional[List[Dict]]:
    """
    Si 'faster-whisper' está instalado en el entorno, extrae word-level timestamps reales
    sobre el archivo de audio continuo o de escena.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
        words_out: List[Dict] = []
        for seg in segments:
            if not seg.words:
                continue
            for w in seg.words:
                token = w.word.strip()
                if token:
                    words_out.append({
                        "word": token,
                        "start": round(start_offset + float(w.start), 3),
                        "end": round(start_offset + float(w.end), 3),
                    })
        return words_out if words_out else None
    except Exception:
        return None


def _load_saved_word_timings(audio_dir: Path) -> Optional[List[Dict]]:
    """
    Carga las marcas de tiempo exactas generadas en una sola toma por EdgeTTSEngine
    desde 'word_timings.json' si están disponibles.
    """
    timings_file = audio_dir / "word_timings.json"
    if not timings_file.exists():
        return None
    try:
        data = json.loads(timings_file.read_text(encoding="utf-8"))
        words = data.get("words", [])
        return words if isinstance(words, list) and len(words) > 0 else None
    except Exception as e:
        logger.warning(f"No se pudo leer word_timings.json: {e}")
        return None


def _compute_weighted_word_timestamps(
    text: str,
    start_offset: float,
    duration: float
) -> List[Dict]:
    """
    Motor de alineación temporal ponderada por longitud fonética y puntuación.
    Calcula tiempos de inicio y fin exactos por palabra sincronizados con la
    duración real del archivo de audio medida con ffprobe.
    """
    cleaned = clean_subtitle_text(text)
    tokens = [t for t in cleaned.split(" ") if t.strip()]
    if not tokens:
        return []

    lead_in = min(0.08, duration * 0.03)
    tail_out = min(0.12, duration * 0.04)
    effective_duration = max(0.4, duration - lead_in - tail_out)

    weights: List[float] = []
    for tok in tokens:
        base_len = max(2, len(re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", tok)))
        punct_pause = 0.0
        if tok.endswith((",", ";", ":")):
            punct_pause = 2.2
        elif tok.endswith((".", "!", "?", "…")):
            punct_pause = 3.5
        weights.append(float(base_len) + punct_pause)

    total_weight = sum(weights) or 1.0
    cursor = start_offset + lead_in
    word_timings: List[Dict] = []

    for idx, (tok, w) in enumerate(zip(tokens, weights)):
        word_dur = effective_duration * (w / total_weight)
        w_start = cursor
        w_end = (start_offset + lead_in + effective_duration) if idx == len(tokens) - 1 else (cursor + word_dur)
        word_timings.append({
            "word": tok,
            "start": round(w_start, 3),
            "end": round(max(w_start + 0.05, w_end), 3),
        })
        cursor = w_end

    return word_timings


def group_words_into_chunks(words: List[Dict], max_words: int = 4) -> List[List[Dict]]:
    """
    Agrupa la lista de palabras con tiempos en bloques dinámicos de 4 a 5 palabras
    (estilo Casually Finance), cortando también al encontrar punto, cierre de frase
    o cambio de escena.
    """
    chunks: List[List[Dict]] = []
    current_chunk: List[Dict] = []

    for w in words:
        if current_chunk and w.get("scene_order") is not None and current_chunk[-1].get("scene_order") is not None:
            if w["scene_order"] != current_chunk[-1]["scene_order"]:
                chunks.append(current_chunk)
                current_chunk = []

        current_chunk.append(w)
        token_text = w["word"]
        ends_sentence = token_text.endswith((".", "!", "?", ":", ";"))
        if len(current_chunk) >= max_words or (ends_sentence and len(current_chunk) >= 2):
            chunks.append(current_chunk)
            current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def build_ass_header(play_res_x: int, play_res_y: int) -> str:
    """
    Construye la cabecera .ass con tipografía gruesa (Arial Black / Montserrat ExtraBold),
    contorno negro sólido de 4px, sombra suave y posicionamiento en el tercio inferior.
    """
    is_vertical = play_res_y > play_res_x
    font_size = 58 if is_vertical else 60
    margin_v = 220 if is_vertical else 110
    margin_h = 70 if is_vertical else 120

    return f"""[Script Info]
Title: Video Studio AI - Dynamic Financial Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{font_size},&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,-1,0,0,0,100,100,0.5,0,1,4.0,2.0,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _append_chunks_to_ass(ass_lines: List[str], chunks: List[List[Dict]]) -> None:
    """Añade los eventos Dialogue con resaltado karaoke activo dorado (#FFD700)."""
    GOLD_ACTIVE_TAG = r"{\1c&H0000D7FF&\fscx106\fscy106}"
    WHITE_BASE_TAG = r"{\1c&H00FFFFFF&\fscx100\fscy100}"

    for chunk in chunks:
        for active_idx, active_word in enumerate(chunk):
            start_ts = format_ass_timestamp(active_word["start"])
            if active_idx < len(chunk) - 1:
                end_sec = chunk[active_idx + 1]["start"]
            else:
                end_sec = active_word["end"]
            end_ts = format_ass_timestamp(max(active_word["start"] + 0.05, end_sec))

            rendered_tokens: List[str] = []
            for idx, w_item in enumerate(chunk):
                safe_word = escape_ass_text(w_item["word"])
                if idx == active_idx:
                    rendered_tokens.append(f"{GOLD_ACTIVE_TAG}{safe_word}{WHITE_BASE_TAG}")
                else:
                    rendered_tokens.append(safe_word)

            dialogue_text = " ".join(rendered_tokens)
            ass_lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{dialogue_text}"
            )


def generate_project_ass_subtitles(project: Project, output_ass_path: Path) -> Path:
    """
    Genera el archivo completo de subtítulos '.ass' con resaltado karaoke activo
    palabra por palabra en dorado (#FFD700 -> ASS &H0000D7FF&) sobre bloques de
    4 palabras en blanco (#FFFFFF -> ASS &H00FFFFFF&).
    Prioriza la pista continua de "Una Sola Toma" (full_narration.mp3 + word_timings.json / Whisper).
    """
    paths = ensure_project_dirs(project.id)
    dims = ASPECT_RATIOS.get(project.settings.aspect_ratio, {"width": 1920, "height": 1080})
    play_res_x, play_res_y = dims["width"], dims["height"]

    ass_lines: List[str] = [build_ass_header(play_res_x, play_res_y)]

    full_audio_file = paths["audio"] / "full_narration.mp3"
    global_words: Optional[List[Dict]] = None

    # 1. Intentar usar la toma continua única (Whisper sobre full_narration.mp3 o word_timings.json nativo)
    if project.settings.audio_mode != "custom" and full_audio_file.exists():
        global_words = _try_whisper_word_timestamps(full_audio_file, 0.0)
        if not global_words:
            global_words = _load_saved_word_timings(paths["audio"])

    if global_words:
        chunks = group_words_into_chunks(global_words, max_words=4)
        _append_chunks_to_ass(ass_lines, chunks)
    else:
        # 2. Fallback por escena (para proyectos existentes o audio personalizado)
        audio_timeline_offset = 0.0
        for scene in project.scenes:
            local_audio: Optional[Path] = None
            if scene.audio_path:
                fname = scene.audio_path.split("?")[0].split("/")[-1]
                candidate = paths["audio"] / fname
                if candidate.exists():
                    local_audio = candidate

            if local_audio and project.settings.audio_mode != "custom":
                scene_audio_dur = get_audio_duration_ffprobe(local_audio)
                if scene_audio_dur <= 0:
                    scene_audio_dur = max(2.5, float(scene.duration))
            else:
                scene_audio_dur = max(2.5, float(scene.duration))

            words = None
            if local_audio and project.settings.audio_mode != "custom":
                words = _try_whisper_word_timestamps(local_audio, audio_timeline_offset)

            if not words:
                words = _compute_weighted_word_timestamps(
                    text=scene.script_text,
                    start_offset=audio_timeline_offset,
                    duration=scene_audio_dur,
                )

            chunks = group_words_into_chunks(words, max_words=4)
            _append_chunks_to_ass(ass_lines, chunks)
            audio_timeline_offset += scene_audio_dur

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.write_text("\n".join(ass_lines) + "\n", encoding="utf-8-sig")
    logger.info(f"Archivo de subtítulos .ass generado en: {output_ass_path}")
    return output_ass_path
