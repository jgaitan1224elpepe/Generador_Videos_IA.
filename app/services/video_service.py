import os
import signal
import subprocess
import tempfile
import time
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.config import FFMPEG_BIN, ASPECT_RATIOS, BASE_DIR
from app.models.project import Project, Scene, TaskStatus
from app.services.storage import ensure_project_dirs, save_project
from app.services.subtitle_service import generate_project_ass_subtitles, escape_ffmpeg_filter_path
from app.services.gemini_service import generate_youtube_metadata_file

logger = logging.getLogger(__name__)

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


class VideoService:
    def __init__(self):
        # Registro de subprocesos activos por project_id
        self._active_processes: Dict[str, subprocess.Popen] = {}
        # Registro de banderas de cancelación solicitadas
        self._cancellation_requested: Dict[str, bool] = {}

    def register_process(self, project_id: str, proc: subprocess.Popen):
        self._active_processes[project_id] = proc

    def unregister_process(self, project_id: str):
        self._active_processes.pop(project_id, None)

    def request_cancellation(self, project_id: str) -> bool:
        """Marca la tarea como cancelada e interrumpe inmediatamente los procesos FFmpeg."""
        self._cancellation_requested[project_id] = True
        proc = self._active_processes.get(project_id)
        
        if proc and proc.poll() is None:
            logger.info(f"Cancelando proceso FFmpeg para el proyecto {project_id} (PID: {proc.pid})")
            try:
                if os.name == 'nt':
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        check=False
                    )
                else:
                    proc.send_signal(signal.SIGKILL)
            except Exception as e:
                logger.error(f"Error finalizando proceso {proc.pid}: {e}")
            return True
        return False

    def is_cancelled(self, project_id: str) -> bool:
        return self._cancellation_requested.get(project_id, False)

    def clear_cancellation_flag(self, project_id: str):
        self._cancellation_requested.pop(project_id, None)

    def run_ffmpeg_command(self, project_id: str, cmd: List[str], temp_dir: Optional[Path] = None) -> bool:
        """Ejecuta comandos FFmpeg registrando PID y comprobando cancelaciones."""
        if self.is_cancelled(project_id):
            self.cleanup_temp_dir(temp_dir)
            return False

        try:
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags
            )
            
            self.register_process(project_id, proc)
            _, stderr = proc.communicate()
            self.unregister_process(project_id)

            if self.is_cancelled(project_id):
                logger.warning(f"Operación cancelada durante ejecución FFmpeg para {project_id}")
                self.cleanup_temp_dir(temp_dir)
                return False

            if proc.returncode != 0:
                logger.error(f"FFmpeg falló con código {proc.returncode}: {stderr.decode('utf-8', errors='ignore')}")
                return False

            return True

        except Exception as e:
            self.unregister_process(project_id)
            logger.error(f"Excepción en comando FFmpeg: {e}")
            self.cleanup_temp_dir(temp_dir)
            return False

    @staticmethod
    def cleanup_temp_dir(temp_dir: Optional[Path]):
        """Elimina el directorio de trabajo temporal en caso de fallo o cancelación."""
        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Directorio temporal limpiado: {temp_dir}")
            except Exception as e:
                logger.warning(f"No se pudo eliminar el directorio temporal {temp_dir}: {e}")


video_service = VideoService()


def render_scene_clip(
    project_id: str,
    scene: Scene,
    target_w: int,
    target_h: int,
    output_clip_path: Path,
    enable_ken_burns: bool = True
) -> None:
    """Renderiza un clip de video independiente para una escena con Ken Burns."""
    if video_service.is_cancelled(project_id):
        raise RuntimeError("Proceso cancelado por el usuario.")

    paths = ensure_project_dirs(project_id)
    
    if not scene.image_path:
        raise ValueError(f"La escena {scene.order} no tiene imagen asignada.")
        
    img_filename = scene.image_path.split("?")[0].split("/")[-1]
    local_img_path = paths["images"] / img_filename
    
    if not local_img_path.exists():
        raise FileNotFoundError(f"No se encontró la imagen en {local_img_path}")

    duration = max(2.5, scene.duration)
    fps = 30
    total_frames = int(duration * fps)

    if enable_ken_burns:
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

    success = video_service.run_ffmpeg_command(project_id, cmd)
    if not success:
        raise RuntimeError(f"Error o cancelación al generar clip de escena {scene.order}")


def render_vertical_short_stub(project: Project) -> str:
    """
    STUB DE ARQUITECTURA (FASE FUTURA):
    Preparado para el renderizado vertical 9:16 (1080x1920) orientado a YouTube Shorts,
    TikTok e Instagram Reels con reencuadre dinámico (smart crop) y subtítulos centrados.
    Por decisión de diseño del MVP actual, la exportación activa opera exclusivamente en 16:9 (1920x1080).
    """
    raise NotImplementedError(
        "El modo vertical 9:16 está reservado para una fase posterior. El MVP exporta en 16:9 Full HD (1920x1080)."
    )


def assemble_project_video(project: Project) -> str:
    """Ensambla y renderiza el video completo MP4 en 16:9 Full HD con audio sincronizado y control de cancelación."""
    project_id = project.id
    video_service.clear_cancellation_flag(project_id)

    paths = ensure_project_dirs(project_id)
    export_dir = paths["export"]
    
    # MVP: Exportación fijada en formato horizontal 16:9 Full HD (1920x1080)
    project.settings.aspect_ratio = "16:9"
    target_w, target_h = 1920, 1080
    
    set_render_status(project_id, "processing", 5, "Iniciando preparación del montaje 16:9...")

    temp_clips = []
    temp_dir = export_dir / f"temp_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        total_scenes = len(project.scenes)
        if total_scenes == 0:
            raise ValueError("El proyecto no tiene escenas para exportar.")

        # 1. Renderizar cada escena
        for idx, scene in enumerate(project.scenes, start=1):
            if video_service.is_cancelled(project_id):
                raise RuntimeError("Cancelado por el usuario.")

            percent = int(10 + (idx / total_scenes) * 45)
            set_render_status(
                project_id, 
                "processing", 
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

        # 2. Concatenar clips de video
        if video_service.is_cancelled(project_id):
            raise RuntimeError("Cancelado por el usuario.")

        set_render_status(project_id, "processing", 60, "Concatenando escenas de video...")
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
        
        if not video_service.run_ffmpeg_command(project_id, cmd_merge, temp_dir):
            raise RuntimeError("Error o cancelación concatenando clips de video.")

        # 3. Preparar pista de audio sincronizada (Priorizando "Una Sola Toma" continua)
        if video_service.is_cancelled(project_id):
            raise RuntimeError("Cancelado por el usuario.")

        set_render_status(project_id, "processing", 75, "Sincronizando pista maestra de audio...")
        final_audio_path: Optional[Path] = temp_dir / "audio_final.mp3"
        single_take_master = paths["audio"] / "full_narration.mp3"
        if project.full_audio_path:
            master_fname = project.full_audio_path.split("?")[0].split("/")[-1]
            candidate_master = paths["audio"] / master_fname
            if candidate_master.exists():
                single_take_master = candidate_master

        if project.settings.audio_mode == "custom" and project.custom_audio_path:
            custom_audio_filename = project.custom_audio_path.split("?")[0].split("/")[-1]
            source_audio = paths["audio"] / custom_audio_filename
            final_audio_path = source_audio if source_audio.exists() else None
        elif single_take_master.exists():
            # Usar directamente la narración continua de "Una Sola Toma"
            final_audio_path = single_take_master
        else:
            # Fallback para proyectos antiguos con audios fragmentados por escena
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
                if not video_service.run_ffmpeg_command(project_id, cmd_audio):
                    cmd_audio_rec = [
                        FFMPEG_BIN,
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(audio_concat_file),
                        "-c:a", "libmp3lame",
                        str(final_audio_path)
                    ]
                    video_service.run_ffmpeg_command(project_id, cmd_audio_rec)
            else:
                final_audio_path = None

        # 3.5 Generar subtítulos dinámicos .ass (estilo Casually Finance) si están habilitados
        if video_service.is_cancelled(project_id):
            raise RuntimeError("Cancelado por el usuario.")

        vf_final_args: List[str] = []
        if getattr(project.settings, "enable_subtitles", True):
            set_render_status(project_id, "processing", 82, "Generando subtítulos dinámicos (.ass)...")
            ass_path = temp_dir / "subtitles.ass"
            generate_project_ass_subtitles(project, ass_path)
            escaped_ass_path = escape_ffmpeg_filter_path(ass_path)
            vf_final_args = ["-vf", f"ass='{escaped_ass_path}'"]

        # 4. Multiplexar video, subtítulos quemados y audio
        if video_service.is_cancelled(project_id):
            raise RuntimeError("Cancelado por el usuario.")

        set_render_status(project_id, "processing", 90, "Codificando video MP4 final en 1080p...")
        timestamp = int(time.time())
        output_filename = f"video_{project.id}_{timestamp}.mp4"
        final_output_path = export_dir / output_filename

        if final_audio_path and Path(final_audio_path).exists():
            cmd_final = [
                FFMPEG_BIN,
                "-y",
                "-i", str(merged_video_path),
                "-i", str(final_audio_path),
                *vf_final_args,
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
                *vf_final_args,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "19",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(final_output_path)
            ]

        if not video_service.run_ffmpeg_command(project_id, cmd_final, temp_dir):
            raise RuntimeError("Error o cancelación en el multiplexado final MP4.")

        # 5. Generar y empaquetar metadatos.txt para YouTube con tiempos exactos de capítulos (MM:SS)
        set_render_status(project_id, "processing", 96, "Empaquetando metadatos SEO para YouTube (metadatos.txt)...")
        metadata_web_path = generate_youtube_metadata_file(project)
        project.metadata_file_path = metadata_web_path

        web_video_path = f"/projects/{project.id}/export/{output_filename}"
        project.final_video_path = web_video_path
        project.status = TaskStatus.COMPLETED.value
        project.progress = 100
        project.step_message = "¡Video MP4 y metadatos.txt exportados exitosamente!"
        project.current_step = 6
        save_project(project)
        
        set_render_status(project_id, "completed", 100, "¡Video MP4 y metadatos.txt exportados exitosamente!")
        return web_video_path

    except Exception as e:
        if video_service.is_cancelled(project_id):
            set_render_status(project_id, "cancelled", 0, "Generación cancelada por el usuario.")
        else:
            set_render_status(project_id, "failed", 0, f"Error en exportación: {str(e)}")
        raise e
    finally:
        video_service.cleanup_temp_dir(temp_dir)