import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional
from app.config import FFMPEG_BIN, ASPECT_RATIOS, BASE_DIR
from app.models.project import Project, Scene
from app.services.storage import ensure_project_dirs

# Diccionario en memoria para reportar el progreso del renderizado a la UI
RENDER_STATUS: Dict[str, Dict[str, Any]] = {}

def get_render_status(project_id: str) -> Dict[str, Any]:
    """Retorna el estado actual de renderizado del proyecto."""
    return RENDER_STATUS.get(project_id, {"status": "idle", "percent": 0, "message": ""})

def set_render_status(project_id: str, status: str, percent: int, message: str) -> None:
    """Actualiza el estado de renderizado para consulta desde el cliente."""
    RENDER_STATUS[project_id] = {
        "status": status,
        "percent": percent,
        "message": message,
        "timestamp": time.time()
    }

def render_scene_clip(
    project_id: str,
    scene: Scene,
    target_w: int,
    target_h: int,
    output_clip_path: Path,
    enable_ken_burns: bool = True
) -> None:
    """
    Renderiza un clip de video independiente para una escena individual
    a la resolución objetivo con efecto de movimiento cinematográfico (Ken Burns).
    """
    paths = ensure_project_dirs(project_id)
    
    # Determinar ruta local de la imagen
    if not scene.image_path:
        raise ValueError(f"La escena {scene.order} no tiene imagen asignada.")
        
    img_filename = scene.image_path.split("?")[0].split("/")[-1]
    local_img_path = paths["images"] / img_filename
    
    if not local_img_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de imagen en {local_img_path}")

    # Determinar duración y fps
    duration = max(2.5, scene.duration)
    fps = 30
    total_frames = int(duration * fps)

    # Configurar filtro de video:
    # 1. Escalar manteniendo aspecto y rellenar si es necesario (fit & pad o pan)
    # 2. Aplicar Ken Burns suave (zoom in o zoom out alternado según número de escena)
    if enable_ken_burns:
        # Alternar entre zoom in (1.0 a 1.12) y zoom out (1.12 a 1.0) según escena par/impar
        if scene.order % 2 == 1:
            zoom_expr = "min(pzoom+0.0008,1.15)"
        else:
            zoom_expr = "max(1.15-0.0008*on,1.0)"
            
        vf = (
            f"scale={target_w}*2:{target_h}*2:force_original_aspect_ratio=increase,"
            f"crop={target_w}*2:{target_h}*2,"
            f"zoompan=z='{zoom_expr}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={target_w}x{target_h}:fps={fps},"
            f"format=yuv420p"
        )
    else:
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"format=yuv420p"
        )

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-loop", "1",
        "-i", str(local_img_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "faster",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(output_clip_path)
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Error en FFmpeg al generar clip de escena {scene.order}: {result.stderr}")

def assemble_project_video(project: Project) -> str:
    """
    Ensambla y renderiza el video completo MP4 en 1080p con audio sincronizado
    a partir de las escenas aprobadas.
    """
    project_id = project.id
    paths = ensure_project_dirs(project_id)
    export_dir = paths["export"]
    
    dims = ASPECT_RATIOS.get(project.settings.aspect_ratio, {"width": 1920, "height": 1080})
    target_w, target_h = dims["width"], dims["height"]
    
    set_render_status(project_id, "rendering", 5, "Iniciando preparación del montaje...")

    temp_clips = []
    temp_dir = export_dir / f"temp_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        total_scenes = len(project.scenes)
        if total_scenes == 0:
            raise ValueError("El proyecto no tiene escenas para exportar.")

        # 1. Renderizar cada escena como clip de video independiente
        for idx, scene in enumerate(project.scenes, start=1):
            percent = int(10 + (idx / total_scenes) * 45)
            set_render_status(
                project_id, 
                "rendering", 
                percent, 
                f"Procesando animación y composición de escena {idx} de {total_scenes}..."
            )
            clip_path = temp_dir / f"clip_{scene.order:03d}.mp4"
            render_scene_clip(
                project_id=project_id,
                scene=scene,
                target_w=target_w,
                target_h=target_h,
                output_clip_path=clip_path,
                enable_ken_burns=project.settings.enable_ken_burns
            )
            temp_clips.append(clip_path)

        # 2. Crear archivo de lista concat para unir clips de video
        set_render_status(project_id, "rendering", 60, "Concatenando escenas de video...")
        concat_file = temp_dir / "concat_list.txt"
        concat_lines = [f"file '{clip.resolve().as_posix()}'" for clip in temp_clips]
        concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

        merged_video_path = temp_dir / "video_merged.mp4"
        cmd_merge = [
            FFMPEG_BIN,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(merged_video_path)
        ]
        res_merge = subprocess.run(cmd_merge, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_merge.returncode != 0:
            raise RuntimeError(f"Error concatenando clips de video: {res_merge.stderr}")

        # 3. Preparar pista de audio sincronizada
        set_render_status(project_id, "rendering", 75, "Sincronizando pista de audio...")
        final_audio_path = temp_dir / "audio_final.mp3"

        if project.settings.audio_mode == "custom" and project.custom_audio_path:
            # Usar audio del usuario
            custom_audio_filename = project.custom_audio_path.split("?")[0].split("/")[-1]
            source_audio = paths["audio"] / custom_audio_filename
            final_audio_path = source_audio
        else:
            # Unir los audios de cada escena en una pista continua
            audio_concat_file = temp_dir / "audio_concat.txt"
            audio_lines = []
            
            for scene in project.scenes:
                if scene.audio_path:
                    fname = scene.audio_path.split("?")[0].split("/")[-1]
                    local_audio = paths["audio"] / fname
                    if local_audio.exists():
                        audio_lines.append(f"file '{local_audio.resolve().as_posix()}'")
            
            if audio_lines:
                audio_concat_file.write_text("\n".join(audio_lines), encoding="utf-8")
                cmd_audio = [
                    FFMPEG_BIN,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(audio_concat_file),
                    "-c", "copy",
                    str(final_audio_path)
                ]
                res_audio = subprocess.run(cmd_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res_audio.returncode != 0:
                    print(f"Aviso concatenando audio con copy, reintentando con recodificación: {res_audio.stderr}")
                    cmd_audio_rec = [
                        FFMPEG_BIN,
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(audio_concat_file),
                        "-c:a", "libmp3lame",
                        str(final_audio_path)
                    ]
                    subprocess.run(cmd_audio_rec, check=True)
            else:
                final_audio_path = None

        # 4. Multiplexar video y audio en el MP4 definitivo en 1080p
        set_render_status(project_id, "rendering", 90, "Codificando video MP4 final en 1080p...")
        timestamp = int(time.time())
        output_filename = f"video_{project.id}_{timestamp}.mp4"
        final_output_path = export_dir / output_filename

        if final_audio_path and Path(final_audio_path).exists():
            cmd_final = [
                FFMPEG_BIN,
                "-y",
                "-i", str(merged_video_path),
                "-i", str(final_audio_path),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "19",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-movflags", "+faststart",
                str(final_output_path)
            ]
        else:
            cmd_final = [
                FFMPEG_BIN,
                "-y",
                "-i", str(merged_video_path),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "19",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(final_output_path)
            ]

        res_final = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_final.returncode != 0:
            raise RuntimeError(f"Error en multiplexado final MP4: {res_final.stderr}")

        web_video_path = f"/projects/{project.id}/export/{output_filename}"
        project.final_video_path = web_video_path
        project.status = "completed"
        project.current_step = 6
        
        set_render_status(project_id, "completed", 100, "¡Video MP4 exportado exitosamente!")
        return web_video_path

    except Exception as e:
        set_render_status(project_id, "failed", 0, f"Error en exportación: {str(e)}")
        raise e
    finally:
        # Limpieza de archivos temporales de clips
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

