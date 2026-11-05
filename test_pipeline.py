import sys
import os

# Configurar salida utf-8 para evitar errores de codificación en consolas Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from pathlib import Path
from app.models.project import Project, Scene, ProjectSettings
from app.services import storage, gemini_service, tts_service, video_service
from app.config import FFMPEG_BIN, FFPROBE_BIN

def test_full_flow():
    print("=" * 60)
    print("[TEST] INICIANDO PRUEBA DEL FLUJO COMPLETO MVP (GUION -> VIDEO FINAL)")
    print("=" * 60)

    # 1. Crear proyecto de prueba con un guion narrativo
    print("\n[Paso 1] Creando Proyecto de Prueba...")
    project = Project(
        name="Test Odisea Cósmica",
        video_title="Odisea Cósmica: El Viaje a Marte",
        full_script=(
            "En el año 2045, la humanidad dio su primer paso más allá de la Luna. "
            "Una tripulación de seis astronautas contemplaba el planeta rojo en el horizonte, "
            "conscientes de que estaban a punto de redefinir la historia de nuestra civilización."
        ),
        settings=ProjectSettings(
            aspect_ratio="16:9",
            visual_style="cinematic",
            voice_id="es-ES-AlvaroNeural",
            enable_ken_burns=True
        )
    )
    storage.save_project(project)
    print(f"[OK] Proyecto creado con ID: {project.id}")

    # 2. División en Escenas
    print("\n[Paso 2] Configurando Escenas del Guion...")
    # Creamos 3 escenas representativas que preservan el 100% del texto
    scenes = [
        Scene(
            order=1,
            script_text="En el año 2045, la humanidad dio su primer paso más allá de la Luna.",
            visual_description="Una nave espacial futurista alejándose de la órbita lunar hacia el espacio profundo.",
            image_prompt="Futuristic sleek spaceship departing Moon orbit towards deep cosmos, Earth in background, cinematic 8k",
            suggested_transition="fade",
            transition="fade"
        ),
        Scene(
            order=2,
            script_text="Una tripulación de seis astronautas contemplaba el planeta rojo en el horizonte,",
            visual_description="Astronautas en la cabina de mando mirando a través de una cúpula panorámica hacia el resplandor de Marte.",
            image_prompt="Astronauts inside high-tech observation deck looking at glowing red planet Mars, warm cockpit lights, dramatic shadows",
            suggested_transition="dissolve",
            transition="dissolve"
        ),
        Scene(
            order=3,
            script_text="conscientes de que estaban a punto de redefinir la historia de nuestra civilización.",
            visual_description="La nave descendiendo lentamente en la atmósfera marciana con retrocohetes activos.",
            image_prompt="Spaceship descending into red dusty Martian atmosphere with fiery retro thrusters, epic cinematic scale",
            suggested_transition="fade",
            transition="fade"
        )
    ]
    project.scenes = scenes
    project.current_step = 2
    storage.save_project(project)
    print(f"[OK] {len(scenes)} escenas registradas correctamente.")

    # 3. Generación de Imágenes para cada escena
    print("\n[Paso 3] Generando Imágenes de Escenas...")
    for s in project.scenes:
        img_path = gemini_service.generate_scene_image(project, s, use_fallback_on_error=True)
        print(f"  - Escena {s.order}: Imagen guardada en {img_path}")
    project.current_step = 3
    storage.save_project(project)
    print("[OK] Todas las imágenes generadas y aprobadas.")

    # 4. Narración y Síntesis de Audio
    print("\n[Paso 4] Sintetizando Narración de Audio Neuronal (Edge-TTS)...")
    tts_service.generate_all_scene_audios(project)
    for s in project.scenes:
        print(f"  - Escena {s.order}: Audio generado ({s.duration}s) en {s.audio_path}")
    project.current_step = 4
    storage.save_project(project)
    print("[OK] Narración completada y duraciones sincronizadas.")

    # 5. Renderizado y Montaje Final con FFmpeg
    print("\n[Paso 5] Renderizando Video Final MP4 (1080p + Ken Burns + Audio Sincronizado)...")
    video_path = video_service.assemble_project_video(project)
    storage.save_project(project)
    print(f"[OK] Video final exportado en: {video_path}")

    # 6. Verificación de archivo generado
    paths = storage.ensure_project_dirs(project.id)
    final_file = paths["export"] / video_path.split("?")[0].split("/")[-1]
    
    if final_file.exists():
        size_mb = final_file.stat().st_size / (1024 * 1024)
        print(f"\n[EXITO TOTAL DEL PIPELINE]")
        print(f"Archivo: {final_file.resolve()}")
        print(f"Tamano: {size_mb:.2f} MB")
        return True
    else:
        print("[ERROR] El archivo final no existe.")
        return False

if __name__ == "__main__":
    success = test_full_flow()
    if not success:
        sys.exit(1)
