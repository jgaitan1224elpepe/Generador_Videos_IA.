import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional
import edge_tts
from app.config import FFPROBE_BIN, AVAILABLE_VOICES, BASE_DIR
from app.models.project import Project, Scene
from app.services.storage import save_scene_audio, ensure_project_dirs

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
        return round(dur, 2)
    except Exception as e:
        print(f"Error midiendo duración de audio con ffprobe en {audio_file_path}: {e}")
        # Estimación aproximada basada en tamaño
        size = audio_file_path.stat().st_size
        return round(max(3.0, size / 16000), 2)

async def synthesize_speech_async(text: str, voice_id: str = "es-ES-AlvaroNeural", speed: float = 1.0, pitch: float = 0.0) -> bytes:
    """Sintetiza voz neuronal a partir de texto usando edge-tts."""
    # Convertir velocidad a formato edge-tts (+10%, -20%, etc.)
    speed_pct = int((speed - 1.0) * 100)
    rate_str = f"+{speed_pct}%" if speed_pct >= 0 else f"{speed_pct}%"
    
    pitch_pct = int(pitch)
    pitch_str = f"+{pitch_pct}Hz" if pitch_pct >= 0 else f"{pitch_pct}Hz"

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice_id,
        rate=rate_str,
        pitch=pitch_str
    )
    
    audio_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
            
    return b"".join(audio_chunks)

def synthesize_scene_audio(project: Project, scene: Scene) -> str:
    """Genera el audio para una escena individual y actualiza su duración."""
    paths = ensure_project_dirs(project.id)
    dest_file = paths["audio"] / f"scene_{scene.id}.mp3"
    
    # Ejecutar síntesis asíncrona en bucle de eventos
    audio_bytes = asyncio.run(
        synthesize_speech_async(
            text=scene.script_text,
            voice_id=project.settings.voice_id,
            speed=project.settings.voice_speed,
            pitch=project.settings.voice_pitch
        )
    )
    
    dest_file.write_bytes(audio_bytes)
    
    # Medir duración exacta del audio generado
    actual_duration = get_audio_duration_ffprobe(dest_file)
    
    # Asignar duración con un pequeño margen de respiración (0.3s) para transiciones
    scene.duration = max(3.0, round(actual_duration + 0.3, 2))
    web_path = f"/projects/{project.id}/audio/scene_{scene.id}.mp3"
    scene.audio_path = web_path
    scene.audio_status = "ready"
    
    return web_path

def generate_all_scene_audios(project: Project) -> None:
    """Genera el audio IA para todas las escenas del proyecto y sincroniza duraciones."""
    for scene in project.scenes:
        synthesize_scene_audio(project, scene)
        
    project.settings.audio_mode = "ai"
    project.status = "audio_ready"

def sync_custom_audio_to_scenes(project: Project, custom_audio_file: Path) -> None:
    """
    Sincroniza un archivo de audio propio cargado por el usuario con las escenas del proyecto,
    distribuyendo la duración total proporcionalmente según el conteo de palabras de cada escena.
    """
    total_duration = get_audio_duration_ffprobe(custom_audio_file)
    if total_duration <= 0 or not project.scenes:
        return
        
    total_words = sum(max(1, len(s.script_text.split())) for s in project.scenes)
    
    for scene in project.scenes:
        scene_words = max(1, len(scene.script_text.split()))
        scene_ratio = scene_words / total_words
        scene.duration = round(total_duration * scene_ratio, 2)
        scene.audio_status = "custom_synced"
        
    project.settings.audio_mode = "custom"
    project.status = "audio_ready"

