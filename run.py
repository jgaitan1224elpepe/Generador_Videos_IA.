import os
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import uvicorn
from app.config import FFMPEG_BIN, FFPROBE_BIN, get_gemini_api_key

def main():
    print("=" * 60)
    print("[STUDIO] Iniciando Video Studio AI (FastAPI + Gemini + FFmpeg)")
    print("=" * 60)
    print(f"[*] Binario FFmpeg : {FFMPEG_BIN}")
    print(f"[*] Binario FFprobe: {FFPROBE_BIN}")
    
    key = get_gemini_api_key()
    if key:
        print("[OK] Gemini API Key: Detectada y configurada")
    else:
        print("[AVISO] Gemini API Key: No detectada (podrás configurarla desde la interfaz o en .env)")
        
    print("[URL] Interfaz Web disponible en: http://127.0.0.1:8000")
    print("=" * 60)
    
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
