import os
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import (
    BASE_DIR, PROJECTS_DIR, VISUAL_STYLES, ASPECT_RATIOS, AVAILABLE_VOICES,
    FFMPEG_BIN, FFPROBE_BIN, get_gemini_api_key, set_gemini_api_key
)
from app.models.project import Project, Scene, ProjectSettings
from app.services import storage, gemini_service, tts_service, video_service

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

# --- ENDPOINTS DE CONFIGURACIÓN ---

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

def shutil_check_bin(bin_path: str) -> bool:
    if os.path.isabs(bin_path):
        return Path(bin_path).exists()
    import shutil
    return bool(shutil.which(bin_path))

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
    project.status = "draft"
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
    """Actualiza datos de configuración o guion del proyecto."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
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
    """Ejecuta el análisis y división en escenas con Gemini 2.5 Flash."""
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
        
    scene = next((s for s in project.scenes if s.id == scene_id), None)
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
                print(f"Aviso en escena {scene.order}: {e}")
                
    project.current_step = max(project.current_step, 3)
    storage.save_project(project)
    return project

@app.post("/api/projects/{project_id}/scenes/{scene_id}/upload-image")
async def upload_custom_image(project_id: str, scene_id: str, file: UploadFile = File(...)):
    """Permite al usuario subir su propia imagen para una escena."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    scene = next((s for s in project.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    content = await file.read()
    ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "png"
    web_path = storage.save_scene_image(project_id, scene_id, content, ext=ext)
    
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
        
    scene = next((s for s in project.scenes if s.id == scene_id), None)
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
        
    scene = next((s for s in project.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    scene.image_prompt = req.prompt
    storage.save_project(project)
    return {"status": "ok", "scene": scene}

# --- ETAPA 4: NARRACIÓN Y AUDIO ---

@app.post("/api/projects/{project_id}/generate-narration")
def generate_narration_endpoint(project_id: str):
    """Genera la narración de audio IA para todas las escenas."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    try:
        tts_service.generate_all_scene_audios(project)
        project.current_step = max(project.current_step, 4)
        storage.save_project(project)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando narración: {str(e)}")

@app.post("/api/projects/{project_id}/scenes/{scene_id}/generate-audio")
def generate_single_scene_audio(project_id: str, scene_id: str):
    """Regenera la narración de audio para una escena individual."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    scene = next((s for s in project.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Escena no encontrada.")
        
    try:
        tts_service.synthesize_scene_audio(project, scene)
        storage.save_project(project)
        return {"status": "ok", "scene": scene}
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
    
    project.current_step = max(project.current_step, 4)
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
    project.current_step = max(project.current_step, 5)
    storage.save_project(project)
    return project

# --- ETAPA 6: EXPORTACIÓN Y RENDERIZADO ---

def run_render_task(project_id: str):
    """Función de fondo para ejecutar el renderizado FFmpeg sin bloquear la petición HTTP."""
    project = storage.get_project(project_id)
    if not project:
        return
    try:
        video_service.assemble_project_video(project)
        storage.save_project(project)
    except Exception as e:
        print(f"Error en renderizado de proyecto {project_id}: {e}")

@app.post("/api/projects/{project_id}/render")
def trigger_render(project_id: str, background_tasks: BackgroundTasks):
    """Inicia la exportación del video final en segundo plano."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    # Verificar que existan escenas e imágenes
    if not project.scenes:
        raise HTTPException(status_code=400, detail="El proyecto no tiene escenas.")
        
    for s in project.scenes:
        if not s.image_path:
            raise HTTPException(status_code=400, detail=f"La escena #{s.order} aún no tiene imagen.")

    video_service.set_render_status(project_id, "starting", 0, "Preparando motor de renderizado...")
    background_tasks.add_task(run_render_task, project_id)
    return {"status": "ok", "message": "Renderizado iniciado en segundo plano."}

@app.get("/api/projects/{project_id}/render-status")
def get_render_progress(project_id: str):
    """Consulta el porcentaje y mensaje del proceso de renderizado."""
    status_info = video_service.get_render_status(project_id)
    project = storage.get_project(project_id)
    if project and project.final_video_path:
        status_info["final_video_path"] = project.final_video_path
    return status_info

# --- RUTA PRINCIPAL ---

@app.get("/")
def serve_index():
    """Sirve la aplicación de interfaz de usuario de Studio."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return {"status": "ok", "message": "Backend listo. Instalando frontend..."}
    return FileResponse(index_file)

