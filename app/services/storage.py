import json
import os
import shutil
import time
from pathlib import Path
from typing import List, Optional
from app.config import PROJECTS_DIR
from app.models.project import Project

def ensure_project_dirs(project_id: str) -> dict:
    """Crea y devuelve las rutas de directorios para un proyecto."""
    p_dir = PROJECTS_DIR / project_id
    img_dir = p_dir / "images"
    audio_dir = p_dir / "audio"
    export_dir = p_dir / "export"
    
    p_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    
    return {
        "root": p_dir,
        "images": img_dir,
        "audio": audio_dir,
        "export": export_dir,
        "json": p_dir / "project.json"
    }

def list_projects() -> List[dict]:
    """Lista todos los proyectos guardados localmente con un resumen."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    
    for item in PROJECTS_DIR.iterdir():
        if item.is_dir():
            json_file = item / "project.json"
            if json_file.exists():
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    projects.append({
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "video_title": data.get("video_title"),
                        "status": data.get("status"),
                        "current_step": data.get("current_step", 1),
                        "scene_count": len(data.get("scenes", [])),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at")
                    })
                except Exception:
                    continue
                    
    # Ordenar por fecha de actualización descendente
    projects.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return projects

def get_project(project_id: str) -> Optional[Project]:
    """Carga un proyecto desde su archivo project.json."""
    json_file = PROJECTS_DIR / project_id / "project.json"
    if not json_file.exists():
        return None
        
    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        return Project(**data)
    except Exception as e:
        print(f"Error cargando proyecto {project_id}: {e}")
        return None

def save_project(project: Project) -> Project:
    """Guarda atómicamente el proyecto en disco para evitar corrupción."""
    paths = ensure_project_dirs(project.id)
    project.updated_at = time.time()
    
    target_file = paths["json"]
    temp_file = target_file.with_suffix(".tmp")
    
    # Escritura atómica
    data = project.model_dump()
    temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # En Windows, si el destino ya existe, se debe reemplazar
    if target_file.exists():
        target_file.unlink()
    temp_file.rename(target_file)
    
    return project

def delete_project(project_id: str) -> bool:
    """Elimina la carpeta completa de un proyecto."""
    p_dir = PROJECTS_DIR / project_id
    if p_dir.exists():
        shutil.rmtree(p_dir)
        return True
    return False

def save_scene_image(project_id: str, scene_id: str, image_bytes: bytes, ext: str = "png") -> str:
    """Guarda una imagen para una escena específica y retorna su ruta relativa."""
    paths = ensure_project_dirs(project_id)
    filename = f"scene_{scene_id}.{ext}"
    dest_path = paths["images"] / filename
    dest_path.write_bytes(image_bytes)
    return f"/projects/{project_id}/images/{filename}?t={int(time.time())}"

def save_scene_audio(project_id: str, scene_id: str, audio_bytes: bytes, ext: str = "mp3") -> str:
    """Guarda un fragmento de audio para una escena y retorna su ruta relativa."""
    paths = ensure_project_dirs(project_id)
    filename = f"audio_{scene_id}.{ext}"
    dest_path = paths["audio"] / filename
    dest_path.write_bytes(audio_bytes)
    return f"/projects/{project_id}/audio/{filename}?t={int(time.time())}"

def save_custom_audio(project_id: str, file_bytes: bytes, filename: str) -> str:
    """Guarda un archivo de audio subido por el usuario."""
    paths = ensure_project_dirs(project_id)
    ext = filename.split(".")[-1].lower() if "." in filename else "mp3"
    dest_name = f"custom_narration.{ext}"
    dest_path = paths["audio"] / dest_name
    dest_path.write_bytes(file_bytes)
    return f"/projects/{project_id}/audio/{dest_name}?t={int(time.time())}"

