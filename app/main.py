import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import logging

from app.models.project import Project, Scene, ProjectSettings, TaskStatus, ProjectStatusUpdate
from app.services import storage, gemini_service, tts_service
from app.services.video_service import video_service, assemble_project_video, get_render_status, set_render_status
from app.config import (
    BASE_DIR, PROJECTS_DIR, VISUAL_STYLES, ASPECT_RATIOS, AVAILABLE_VOICES,
    FFMPEG_BIN, FFPROBE_BIN, get_gemini_api_key, set_gemini_api_key
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Generador de Videos IA - Studio",
    description="Aplicación profesional para convertir guiones en videos narrativos completos con IA.",
    version="1.0.0"
)

# CORS para permitir desarrollo ágil
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos de medios generados de proyectos y estáticos de la UI
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/projects", StaticFiles(directory=str(PROJECTS_DIR)), name="projects")

STATIC_DIR = BASE_DIR / "app" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Modelos auxiliares para peticiones
class ApiKeyRequest(BaseModel):
    api_key: str

class UpdatePromptRequest(BaseModel):
    prompt: str

class UpdateScenesRequest(BaseModel):
    scenes: List[Scene]

class GenerateNarrationRequest(BaseModel):
    voice_id: Optional[str] = None
    voice_speed: Optional[float] = None
    voice_pitch: Optional[float] = None

# --- ENDPOINTS DE CONFIGURACIÓN ---

def shutil_check_bin(bin_path: str) -> bool:
    if os.path.isabs(bin_path):
        return Path(bin_path).exists()
    return bool(shutil.which(bin_path))

@app.get("/api/config")
def get_system_config():
    """Retorna la configuración global del sistema y capacidades disponibles."""
    gemini_key = get_gemini_api_key()
    return {
        "has_gemini_key": bool(gemini_key and len(gemini_key) > 5),
        "ffmpeg_available": bool(shutil_check_bin(FFMPEG_BIN)),
        "visual_styles": VISUAL_STYLES,
        "aspect_ratios": list(ASPECT_RATIOS.values()),
        "available_voices": AVAILABLE_VOICES,
    }

@app.post("/api/config/api-key")
def update_api_key(req: ApiKeyRequest):
    """Guarda la clave de API de Gemini de forma segura."""
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="La clave de API no puede estar vacía.")
    set_gemini_api_key(req.api_key.strip())
    return {"status": "ok", "message": "Clave API de Gemini configurada exitosamente."}

# --- ENDPOINTS DE PROYECTOS ---

@app.get("/api/projects")
def list_all_projects():
    """Lista todos los proyectos guardados localmente."""
    return storage.list_projects()

@app.post("/api/projects")
def create_new_project(project: Project):
    """Crea y persiste un nuevo proyecto."""
    project.current_step = 1
    project.status = TaskStatus.IDLE.value
    storage.save_project(project)
    return project

@app.get("/api/projects/{project_id}")
def get_project_details(project_id: str):
    """Obtiene los detalles completos de un proyecto."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return project

@app.put("/api/projects/{project_id}")
def update_project_details(project_id: str, updated: Project):
    """Actualiza datos de configuración o guion del proyecto sincronizando la voz."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    if updated.settings and updated.settings.voice_id:
        updated.voice = updated.settings.voice_id
    elif updated.voice:
        updated.settings.voice_id = updated.voice
    storage.save_project(updated)
    return updated

@app.delete("/api/projects/{project_id}")
def delete_project_endpoint(project_id: str):
    """Elimina el proyecto y todos sus archivos asociados."""
    ok = storage.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado para eliminar.")
    return {"status": "ok", "message": "Proyecto eliminado correctamente."}

# --- ETAPA 2: ANÁLISIS DE GUION ---

@app.post("/api/projects/{project_id}/analyze")
def analyze_script_endpoint(project_id: str):
    """Ejecuta el análisis y división en escenas con Gemini Flash."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    if not project.full_script.strip():
        raise HTTPException(status_code=400, detail="El guion está vacío.")
        
    try:
        scenes = gemini_service.analyze_script_with_gemini(project)
        project.scenes = scenes
        project.status = "analyzed"
        project.current_step = 2
        storage.save_project(project)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analizando guion con Gemini: {str(e)}")

# --- ETAPA 3: GENERACIÓN DE IMÁGENES ---

@app.post("/api/projects/{project_id}/scenes/{scene_id}/generate-image")
def generate_single_scene_image(project_id: str, scene_id: str):
    """Genera o regenera la imagen de una escena individual con Imagen 3."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    scene = next((s for s in project.scenes if s.id == scene_id or str(s.order) == str(scene_id)), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    try:
        gemini_service.generate_scene_image(project, scene)
        storage.save_project(project)
        return {"status": "ok", "scene": scene}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando imagen: {str(e)}")

@app.post("/api/projects/{project_id}/generate-all-images")
def generate_all_images(project_id: str):
    """Genera imágenes para todas las escenas pendientes."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    for scene in project.scenes:
        if not scene.image_path or scene.image_status == "pending":
            try:
                gemini_service.generate_scene_image(project, scene)
            except Exception as e:
                logger.warning(f"Aviso en escena {scene.order}: {e}")
                
    project.current_step = max(int(project.current_step), 3)
    storage.save_project(project)
    return project

@app.post("/api/projects/{project_id}/scenes/{scene_id}/upload-image")
async def upload_custom_image(project_id: str, scene_id: str, file: UploadFile = File(...)):
    """Permite al usuario subir su propia imagen para una escena."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    scene = next((s for s in project.scenes if s.id == scene_id or str(s.order) == str(scene_id)), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    content = await file.read()
    ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "png"
    web_path = storage.save_scene_image(project_id, scene.id, content, ext=ext)
    
    scene.image_path = web_path
    scene.image_status = "approved"
    storage.save_project(project)
    return {"status": "ok", "scene": scene}

@app.post("/api/projects/{project_id}/scenes/{scene_id}/approve")
def approve_scene_image(project_id: str, scene_id: str):
    """Marca la imagen de una escena como aprobada por el usuario."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    scene = next((s for s in project.scenes if s.id == scene_id or str(s.order) == str(scene_id)), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    scene.image_status = "approved"
    storage.save_project(project)
    return {"status": "ok", "scene": scene}

@app.post("/api/projects/{project_id}/scenes/{scene_id}/prompt")
def update_scene_prompt(project_id: str, scene_id: str, req: UpdatePromptRequest):
    """Actualiza el prompt de una escena antes de regenerar."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    scene = next((s for s in project.scenes if s.id == scene_id or str(s.order) == str(scene_id)), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    scene.image_prompt = req.prompt
    storage.save_project(project)
    return {"status": "ok", "scene": scene}

# --- ETAPA 4: NARRACIÓN Y AUDIO (FLUJO EN UNA SOLA TOMA) ---

@app.post("/api/projects/{project_id}/generate-narration")
def generate_narration_endpoint(project_id: str, req: Optional[GenerateNarrationRequest] = None):
    """
    Genera la narración de audio IA en UNA SOLA TOMA continua para todo el guion,
    aplicando inmediatamente cualquier cambio de voz, velocidad o tono enviado.
    """
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    if req:
        if req.voice_id:
            project.voice = req.voice_id
            project.settings.voice_id = req.voice_id
        if req.voice_speed is not None:
            project.settings.voice_speed = req.voice_speed
        if req.voice_pitch is not None:
            project.settings.voice_pitch = req.voice_pitch
        storage.save_project(project)

    try:
        tts_service.generate_all_scene_audios(project)
        gemini_service.generate_youtube_metadata_file(project)
        project.current_step = max(int(project.current_step), 4)
        storage.save_project(project)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando narración: {str(e)}")

@app.post("/api/projects/{project_id}/scenes/{scene_id}/generate-audio")
def generate_single_scene_audio(project_id: str, scene_id: str, req: Optional[GenerateNarrationRequest] = None):
    """
    Por compatibilidad con el principio de 'Una Sola Toma', regenera la pista maestra
    completa con la voz actual seleccionada y actualiza todos los recortes de escena.
    """
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    if req:
        if req.voice_id:
            project.voice = req.voice_id
            project.settings.voice_id = req.voice_id
        if req.voice_speed is not None:
            project.settings.voice_speed = req.voice_speed
        if req.voice_pitch is not None:
            project.settings.voice_pitch = req.voice_pitch
        storage.save_project(project)

    scene = next((s for s in project.scenes if s.id == scene_id or str(s.order) == str(scene_id)), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    try:
        tts_service.generate_all_scene_audios(project)
        storage.save_project(project)
        updated_scene = next((s for s in project.scenes if s.id == scene.id), scene)
        return {"status": "ok", "scene": updated_scene, "project": project}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sintetizando audio: {str(e)}")

@app.post("/api/projects/{project_id}/upload-custom-audio")
async def upload_custom_audio(project_id: str, file: UploadFile = File(...)):
    """Permite al usuario subir un archivo de audio MP3 o WAV propio."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    content = await file.read()
    web_path = storage.save_custom_audio(project_id, content, file.filename or "audio.mp3")
    project.custom_audio_path = web_path
    
    # Sincronizar proporcionalmente con las escenas
    paths = storage.ensure_project_dirs(project_id)
    local_audio = paths["audio"] / web_path.split("?")[0].split("/")[-1]
    tts_service.sync_custom_audio_to_scenes(project, local_audio)
    
    project.current_step = max(int(project.current_step), 4)
    storage.save_project(project)
    return project

# --- ETAPA 5: EDICIÓN Y AJUSTES ---

@app.put("/api/projects/{project_id}/scenes")
def update_project_scenes(project_id: str, req: UpdateScenesRequest):
    """Actualiza la lista de escenas (orden, duraciones, transiciones)."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    project.scenes = req.scenes
    project.current_step = max(int(project.current_step), 5)
    storage.save_project(project)
    return project


# --- ETAPA 6: GENERACIÓN EN SEGUNDO PLANO (THREADPOOL NO BLOQUEANTE) Y CANCELACIÓN ---

def process_video_background(project_id: str):
    """
    Tarea síncrona ejecutada por FastAPI BackgroundTasks en un ThreadPool independiente.
    IMPORTANTE: Al ser 'def' (y no 'async def'), NO bloquea el Event Loop de Uvicorn,
    permitiendo que GET /status y POST /cancel respondan en tiempo real mientras FFmpeg renderiza.
    """
    video_service.clear_cancellation_flag(project_id)
    project = storage.get_project(project_id)
    
    if not project:
        return

    try:
        project.status = TaskStatus.PROCESSING.value
        project.progress = 5
        project.step_message = "Iniciando preparación del montaje..."
        project.error_message = None
        storage.save_project(project)
        
        # Ejecutar renderizado completo de video (actualiza RENDER_STATUS y guarda final_video_path)
        assemble_project_video(project)

    except Exception as e:
        logger.error(f"Error procesando el proyecto {project_id}: {e}")
        project = storage.get_project(project_id)
        if project:
            if video_service.is_cancelled(project_id):
                project.status = TaskStatus.CANCELLED.value
                project.progress = 0
                project.step_message = "Generación cancelada por el usuario."
                project.error_message = "Generación cancelada por el usuario."
            else:
                project.status = TaskStatus.FAILED.value
                project.progress = 0
                project.step_message = "Error en exportación."
                project.error_message = str(e)
            storage.save_project(project)


@app.post("/api/projects/{project_id}/generate")
@app.post("/api/projects/{project_id}/render")
def start_video_generation(project_id: str, background_tasks: BackgroundTasks):
    """Inicia el renderizado FFmpeg en segundo plano sin bloquear el servidor."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
        
    render_info = get_render_status(project_id)
    if render_info.get("status") == "processing":
        raise HTTPException(status_code=400, detail="El proyecto ya está en proceso de generación.")

    # Verificar que existan escenas e imágenes
    if not project.scenes:
        raise HTTPException(status_code=400, detail="El proyecto no tiene escenas.")
        
    for s in project.scenes:
        if not s.image_path:
            raise HTTPException(status_code=400, detail=f"La escena #{s.order} aún no tiene imagen.")

    # Inicializar estado en memoria antes de lanzar el hilo para respuesta inmediata al primer polling
    video_service.clear_cancellation_flag(project_id)
    set_render_status(project_id, "processing", 2, "Preparando motor de renderizado FFmpeg...")
    project.status = TaskStatus.PROCESSING.value
    project.progress = 2
    project.step_message = "Preparando motor de renderizado FFmpeg..."
    project.error_message = None
    storage.save_project(project)

    # Lanzar renderizado en segundo plano (threadpool)
    background_tasks.add_task(process_video_background, project_id)
    
    return {"message": "Proceso iniciado en segundo plano", "status": TaskStatus.PROCESSING}


@app.get("/api/projects/{project_id}/status", response_model=ProjectStatusUpdate)
@app.get("/api/projects/{project_id}/render-status")
def get_project_status(project_id: str):
    """Consulta el estado y progreso en tiempo real de la tarea de video."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    
    render_info = get_render_status(project_id)
    raw_status = render_info.get("status", "idle")
    
    # Normalizar estado hacia TaskStatus válido para el polling
    status_map = {
        "starting": TaskStatus.PROCESSING,
        "rendering": TaskStatus.PROCESSING,
        "processing": TaskStatus.PROCESSING,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
        "cancelled": TaskStatus.CANCELLED,
        "idle": TaskStatus.IDLE,
    }
    mapped_status = status_map.get(raw_status, TaskStatus.IDLE)
    
    # Si RENDER_STATUS está en idle (ej. tras reinicio), usar estado del proyecto si corresponde
    if raw_status == "idle" and project.status in status_map:
        mapped_status = status_map[project.status]

    return ProjectStatusUpdate(
        status=mapped_status,
        progress=int(render_info.get("percent", project.progress or 0)),
        current_step=str(render_info.get("message") or project.step_message or ""),
        error_message=project.error_message,
        final_video_path=project.final_video_path,
        metadata_file_path=project.metadata_file_path
    )


@app.get("/api/projects/{project_id}/metadata")
def get_or_generate_project_metadata(project_id: str):
    """Genera o actualiza 'metadatos.txt' con los tiempos reales de capítulos y retorna su contenido."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    web_path = gemini_service.generate_youtube_metadata_file(project)
    storage.save_project(project)

    paths = storage.ensure_project_dirs(project_id)
    meta_file = paths["export"] / "metadatos.txt"
    content = meta_file.read_text(encoding="utf-8") if meta_file.exists() else ""

    return {
        "status": "ok",
        "metadata_file_path": web_path,
        "youtube_metadata": project.youtube_metadata,
        "content": content,
    }


@app.get("/api/projects/{project_id}/metadata/download")
def download_project_metadata_txt(project_id: str):
    """Sirve el archivo 'metadatos.txt' listo para ver en el navegador o descargar."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    gemini_service.generate_youtube_metadata_file(project)
    storage.save_project(project)

    paths = storage.ensure_project_dirs(project_id)
    meta_file = paths["export"] / "metadatos.txt"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="Archivo metadatos.txt no encontrado")

    return FileResponse(
        meta_file,
        media_type="text/plain; charset=utf-8",
        filename=f"metadatos_{project.id}.txt",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


@app.post("/api/projects/{project_id}/cancel")
def cancel_project_task(project_id: str):
    """Interrumpe forzosamente cualquier proceso de renderizado FFmpeg en curso."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    # Solicitar la cancelación inmediata a FFmpeg (taskkill /F /T /PID en Windows)
    cancelled = video_service.request_cancellation(project_id)
    set_render_status(project_id, "cancelled", 0, "Generación cancelada por el usuario.")
    
    project.status = TaskStatus.CANCELLED.value
    project.progress = 0
    project.step_message = "Generación cancelada por el usuario."
    project.error_message = "Generación cancelada por el usuario."
    storage.save_project(project)
    
    return {"message": "Solicitud de cancelación enviada", "cancelled": cancelled, "status": TaskStatus.CANCELLED}


# --- RUTA PRINCIPAL UI ---

@app.get("/")
def serve_index():
    """Sirve la aplicación de interfaz de usuario de Studio sin caché obsoleta."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return {"status": "ok", "message": "Backend listo. Instalando frontend..."}
    return FileResponse(
        index_file,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )
