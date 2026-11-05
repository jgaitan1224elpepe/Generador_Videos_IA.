# 🎬 Video Studio AI — Generador de Videos Narrativos con IA

Aplicación integral desarrollada con **FastAPI**, **Google Gemini (Gemini 2.5 Flash / Imagen 3)**, **Edge-TTS** y **FFmpeg 9.0**, diseñada para transformar guiones terminados en videos cinematográficos completos en resolución **1080p**, con imágenes generadas por IA, narración de voz sincronizada y montaje audiovisual automático.

---

## 🌟 Características Principales

1. **Gestión de Proyectos Local & Persistente**:
   - Creación, guardado atómico y reanudación de proyectos en cualquier momento sin pérdida de datos.
   - Formatos compatibles: **16:9** (Horizontal para YouTube/TV), **9:16** (Vertical para TikTok/Reels/Shorts) y **1:1** (Cuadrado para Feed).
   - Presets de estilo visual (Cinematográfico Realista, Anime Studio Ghibli, Animación 3D Pixar, Cyberpunk Neón, Acuarela, Documental Histórico).

2. **Análisis de Guion Inteligente (Gemini 2.5 Flash)**:
   - División cronológica en escenas estructuradas mediante el SDK oficial `google-genai`.
   - **Regla Suprema de Integridad**: Conserva el 100% del texto original palabra por palabra, sin resúmenes ni omisiones.
   - Inclusión de descripciones visuales, prompts técnicos optimizados para Imagen 3, tiempos de lectura y notas de continuidad.

3. **Generación Visual & Control de Calidad (Imagen 3)**:
   - Integración con el modelo `imagen-3.0-generate-002`.
   - Coherencia estilística gracias a modificadores ancla según el estilo seleccionado.
   - Sistema de revisión y aprobación escena por escena.
   - Posibilidad de regenerar individualmente, editar prompts y subir imágenes propias (JPG/PNG).

4. **Narración Sincronizada (Doble Modo)**:
   - **Opción A (Voz IA Neuronal)**: Catálogo de voces neuronales en español (España, México, Colombia, Argentina) e inglés con modulación de velocidad y tono. Síntesis escena a escena con medición exacta por `ffprobe`.
   - **Opción B (Voz Propia)**: Carga de archivos MP3/WAV con detección de duración y sincronización proporcional automática.

5. **Editor Visual & Timeline**:
   - Ajuste manual de duración de planos.
   - Reordenación interactiva de escenas (subir/bajar).
   - Selector de transiciones (Fade, Dissolve, Zoom In, Pan, Corte Directo).
   - Previsualización en tiempo real de imagen y fragmento sonoro.

6. **Exportación 1080p con FFmpeg**:
   - Movimiento de cámara dinámico (Efecto **Ken Burns**: slow pan y zoom cinematográfico).
   - Códec H.264 / AAC en contenedor MP4 estándar.
   - Barra de progreso en vivo y reproductor integrado con descarga directa.

---

## 🚀 Inicio Rápido

### 1. Iniciar la Aplicación
Simplemente haz doble clic en el archivo:
```bash
start.bat
```
O ejecuta desde tu terminal:
```bash
.\.venv\Scripts\python.exe run.py
```

Abre tu navegador en:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🔑 Configuración de la Clave de Google Gemini

Puedes configurar tu clave de API de dos maneras muy sencillas:

1. **Desde la Interfaz Gráfica**:
   - Haz clic en el botón superior derecho con el icono de llave o el indicador amarillo **"Configurar Gemini API Key"**.
   - Pega tu clave de API obtenida en [Google AI Studio](https://aistudio.google.com/).
   - Haz clic en **Guardar Clave**.

2. **Mediante archivo `.env`**:
   - Crea un archivo `.env` en la raíz del proyecto con la siguiente línea:
     ```env
     GEMINI_API_KEY=tu_clave_aqui
     ```

> **Nota**: El sistema incluye un modo de prueba/reserva (fallback) visual que permite probar el flujo completo del editor y exportador FFmpeg incluso antes de configurar la clave de API.

---

## 📁 Estructura del Proyecto

```
Generador_Videos_IA/
├── start.bat                  # Lanzador rápido para Windows
├── run.py                     # Servidor FastAPI / Uvicorn
├── requirements.txt           # Dependencias de Python
├── test_pipeline.py           # Script de prueba automatizada end-to-end
├── app/
│   ├── config.py              # Detección de FFmpeg, estilos, formatos y API keys
│   ├── main.py                # Endpoints REST y rutas de medios
│   ├── models/
│   │   └── project.py         # Modelos Pydantic (Proyecto, Escena, Configuración)
│   ├── services/
│   │   ├── storage.py         # Persistencia local atómica en JSON y gestión de medios
│   │   ├── gemini_service.py  # Análisis de guion (Gemini 2.5) y generación (Imagen 3)
│   │   ├── tts_service.py     # Síntesis neuronal de audio y sincronización con ffprobe
│   │   └── video_service.py   # Motor de montaje FFmpeg (Ken Burns, audio muxing, 1080p MP4)
│   └── static/
│       ├── css/style.css      # Estilos Dark Mode Studio
│       ├── js/app.js          # Controlador reactivo del frontend
│       └── index.html         # Interfaz Studio moderna en 6 etapas
└── projects/                  # Directorio local con los proyectos y medios generados
```

---

## 🧪 Verificación Automatizada

El flujo completo ha sido probado y verificado exitosamente mediante `test_pipeline.py`, generando un video MP4 en resolución **1920x1080 a 30 FPS** con audio sincronizado y movimiento de cámara continuo.

