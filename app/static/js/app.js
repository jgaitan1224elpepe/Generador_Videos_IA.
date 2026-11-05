// Video Studio AI - Main Frontend Controller (Studio Pro Edition)

let appState = {
  config: null,
  project: null,
  currentStep: 1,
  renderInterval: null
};

// --- INICIALIZACIÓN ---
document.addEventListener("DOMContentLoaded", async () => {
  if (window.lucide) lucide.createIcons();
  await loadSystemConfig();
  await loadLastProjectOrCreateDefault();
  setupScriptCounter();
});

// Cargar configuración global del backend
async function loadSystemConfig() {
  try {
    const res = await fetch("/api/config");
    appState.config = await res.json();
    
    // Actualizar indicador de API Key con estilo Studio
    const badge = document.getElementById("api-status-badge");
    if (appState.config.has_gemini_key) {
      badge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-royal-800/80 text-gold-300 border border-gold-500/30 cursor-pointer shadow-sm hover:border-gold-400/50 transition";
      badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 shadow-sm shadow-emerald-400/50"></span><span>Gemini API: Conectada</span>`;
    } else {
      badge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-royal-800/80 text-gold-400 border border-gold-500/25 cursor-pointer shadow-sm hover:border-gold-400/50 transition";
      badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-gold-400 animate-pulse shadow-sm shadow-gold-400/50"></span><span>Configurar Gemini API Key</span>`;
    }

    renderVisualStyles();
    renderVoicesDropdown();
  } catch (err) {
    showToast("Error conectando con el servidor", "error");
  }
}

// Cargar el último proyecto o crear uno nuevo por defecto
async function loadLastProjectOrCreateDefault() {
  try {
    const res = await fetch("/api/projects");
    const projects = await res.json();
    if (projects.length > 0) {
      await loadProject(projects[0].id);
    } else {
      await createNewProject("Nuevo Video Narrativo");
    }
  } catch (err) {
    console.error("Error cargando proyectos:", err);
  }
}

// Cargar proyecto por ID
async function loadProject(projectId) {
  try {
    const res = await fetch(`/api/projects/${projectId}`);
    if (!res.ok) throw new Error("No se pudo cargar el proyecto");
    appState.project = await res.json();
    
    document.getElementById("current-project-label").innerText = appState.project.name || "Proyecto";
    populateProjectData();
    switchStep(appState.project.current_step || 1, false);
    showToast(`Proyecto '${appState.project.name}' cargado`, "info");
  } catch (err) {
    showToast("Error cargando proyecto", "error");
  }
}

// Crear nuevo proyecto
async function createNewProject(defaultName = "Nuevo Proyecto") {
  const newProj = {
    name: defaultName,
    video_title: defaultName,
    full_script: "",
    status: "draft",
    current_step: 1,
    settings: {
      aspect_ratio: "16:9",
      visual_style: "cinematic",
      narration_language: "es",
      voice_id: "es-ES-AlvaroNeural",
      voice_speed: 1.0,
      voice_pitch: 0.0,
      audio_mode: "ai",
      enable_ken_burns: true
    },
    scenes: []
  };

  const res = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(newProj)
  });
  appState.project = await res.json();
  document.getElementById("current-project-label").innerText = appState.project.name;
  populateProjectData();
  switchStep(1, false);
  showToast("Nuevo proyecto creado", "success");
}

function createNewProjectPrompt() {
  const name = prompt("Introduce el nombre del nuevo proyecto:", "Documental Histórico");
  if (name && name.trim()) {
    createNewProject(name.trim());
    closeProjectsModal();
  }
}

// Rellenar campos del proyecto en la UI
function populateProjectData() {
  if (!appState.project) return;
  const p = appState.project;

  document.getElementById("project-name").value = p.name || "";
  document.getElementById("video-title").value = p.video_title || "";
  document.getElementById("full-script").value = p.full_script || "";

  selectAspectRatio(p.settings.aspect_ratio || "16:9", false);
  selectVisualStyle(p.settings.visual_style || "cinematic", false);

  if (p.settings.voice_id) {
    document.getElementById("voice-select").value = p.settings.voice_id;
  }
  if (p.settings.voice_speed) {
    document.getElementById("voice-speed").value = p.settings.voice_speed;
    document.getElementById("voice-speed-val").innerText = p.settings.voice_speed + "x";
  }
  if (p.settings.voice_pitch) {
    document.getElementById("voice-pitch").value = p.settings.voice_pitch;
    document.getElementById("voice-pitch-val").innerText = p.settings.voice_pitch + "Hz";
  }

  updateScriptStats();
  renderScenesViews();
}

// Guardar datos básicos del proyecto
async function saveProjectBasicInfo() {
  if (!appState.project) return;
  appState.project.name = document.getElementById("project-name").value.trim() || "Sin Título";
  appState.project.video_title = document.getElementById("video-title").value.trim() || "Video";
  appState.project.full_script = document.getElementById("full-script").value.trim();

  await fetch(`/api/projects/${appState.project.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(appState.project)
  });
}

// --- NAVEGACIÓN DE PASOS (STEPPER) ---
function switchStep(stepNumber, save = true) {
  if (save) saveProjectBasicInfo();
  appState.currentStep = stepNumber;

  // Actualizar botones de stepper con estilo contemporáneo
  for (let i = 1; i <= 6; i++) {
    const btn = document.getElementById(`step-btn-${i}`);
    const view = document.getElementById(`step-${i}`);
    
    if (i === stepNumber) {
      btn.className = "step-item active py-3 px-2 text-xs font-semibold flex items-center gap-2.5 transition";
      btn.querySelector(".step-num").className = "step-num w-6 h-6 rounded-full bg-gold-500 text-royal-950 flex items-center justify-center font-bold text-[11px] shadow-sm";
      view.classList.remove("hidden");
    } else {
      btn.className = "step-item py-3 px-2 text-xs font-semibold flex items-center gap-2.5 text-slate-400 hover:text-slate-200 transition";
      btn.querySelector(".step-num").className = "step-num w-6 h-6 rounded-full bg-royal-800 border border-slate-700 flex items-center justify-center font-bold text-[11px] text-slate-400";
      view.classList.add("hidden");
    }
  }

  renderScenesViews();
  if (window.lucide) lucide.createIcons();
}

// --- ESTILOS VISUALES Y FORMATO ---
function renderVisualStyles() {
  const container = document.getElementById("visual-style-container");
  if (!container || !appState.config) return;

  container.innerHTML = appState.config.visual_styles.map(style => `
    <div onclick="selectVisualStyle('${style.id}')" id="style-${style.id}" class="style-card p-3.5 rounded-xl transition cursor-pointer">
      <div class="font-bold text-xs text-white">${style.name}</div>
      <div class="text-[11px] text-slate-400 truncate mt-1 leading-snug">${style.prompt_suffix}</div>
    </div>
  `).join("");
}

function selectVisualStyle(styleId, updateState = true) {
  if (updateState && appState.project) {
    appState.project.settings.visual_style = styleId;
  }
  document.querySelectorAll(".style-card").forEach(el => {
    el.classList.remove("border-gold-400", "selected");
  });
  const target = document.getElementById(`style-${styleId}`);
  if (target) {
    target.classList.add("border-gold-400", "selected");
  }
}

function selectAspectRatio(ratio, updateState = true) {
  if (updateState && appState.project) {
    appState.project.settings.aspect_ratio = ratio;
  }
  document.querySelectorAll(".aspect-card").forEach(el => el.classList.remove("selected"));
  const target = document.getElementById(`aspect-${ratio.replace(":", "-")}`);
  if (target) target.classList.add("selected");
  
  // Actualizar etiqueta de exportación
  const dimLabel = document.getElementById("export-dim-label");
  if (dimLabel) {
    const map = { "16:9": "1920x1080 (16:9)", "9:16": "1080x1920 (9:16)", "1:1": "1080x1080 (1:1)" };
    dimLabel.innerText = map[ratio] || ratio;
  }
}

function renderVoicesDropdown() {
  const select = document.getElementById("voice-select");
  if (!select || !appState.config) return;
  select.innerHTML = appState.config.available_voices.map(v => `
    <option value="${v.id}">${v.name}</option>
  `).join("");
}

function setupScriptCounter() {
  const textarea = document.getElementById("full-script");
  textarea.addEventListener("input", updateScriptStats);
}

function updateScriptStats() {
  const text = document.getElementById("full-script").value.trim();
  const words = text ? text.split(/\s+/).length : 0;
  const estimatedSeconds = Math.round(words / 2.5); // ~150 palabras por minuto
  document.getElementById("word-count").innerText = `${words} palabras`;
  document.getElementById("estimated-time").innerText = `~${estimatedSeconds}s estimado`;
}

// --- ETAPA 2: ANÁLISIS DE GUION ---
async function analyzeScript() {
  const scriptText = document.getElementById("full-script").value.trim();
  if (!scriptText) {
    showToast("Por favor pega o introduce un guion antes de analizar", "error");
    return;
  }

  await saveProjectBasicInfo();
  
  const btn = document.getElementById("btn-analyze-script");
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin mr-2">⚙️</span> Analizando con Gemini 3.5 Flash...`;

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/analyze`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error en el análisis");
    }
    appState.project = await res.json();
    showToast(`¡Guion dividido en ${appState.project.scenes.length} escenas con éxito!`, "success");
    switchStep(2);
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="sparkles" class="w-4 h-4 text-royal-950 stroke-[2.5]"></i><span>Analizar y Dividir con Gemini 3.5 Flash</span>`;
    if (window.lucide) lucide.createIcons();
  }
}

// Renderizado de las vistas de escenas según el paso activo
function renderScenesViews() {
  if (!appState.project || !appState.project.scenes) return;

  if (appState.currentStep === 2) renderStep2Scenes();
  if (appState.currentStep === 3) renderStep3Gallery();
  if (appState.currentStep === 4) renderStep4Audio();
  if (appState.currentStep === 5) renderStep5Timeline();
  if (appState.currentStep === 6) renderStep6Export();
}

// Paso 2: Tarjetas de escenas analizadas
function renderStep2Scenes() {
  const container = document.getElementById("scenes-list-container");
  if (!container) return;

  if (appState.project.scenes.length === 0) {
    container.innerHTML = `<div class="text-center py-12 text-slate-400 font-medium">Aún no se han generado escenas. Vuelve a la etapa 1 y analiza el guion.</div>`;
    return;
  }

  container.innerHTML = appState.project.scenes.map(s => `
    <div class="scene-card rounded-2xl p-5 space-y-3.5 shadow-lg">
      <div class="flex items-center justify-between border-b border-white/10 pb-3">
        <div class="flex items-center gap-2.5">
          <span class="px-2.5 py-1 rounded-lg bg-gold-500/15 border border-gold-500/30 text-gold-300 font-bold text-xs">Escena #${s.order}</span>
          <span class="text-xs text-slate-400 font-medium">Duración: ${s.duration}s</span>
        </div>
        <span class="text-xs px-2.5 py-1 rounded-lg bg-royal-950 text-slate-300 font-medium border border-white/10">Transición: ${s.suggested_transition}</span>
      </div>

      <div>
        <span class="text-[11px] font-semibold text-gold-300 uppercase tracking-wider">Narración exacta del guion:</span>
        <p class="text-sm text-slate-100 mt-1 font-normal bg-royal-950/80 p-3.5 rounded-xl border border-white/10 leading-relaxed">"${s.script_text}"</p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
        <div>
          <span class="text-[11px] font-semibold text-slate-300 uppercase tracking-wider">Descripción visual:</span>
          <p class="text-slate-200 mt-1 leading-relaxed">${s.visual_description}</p>
        </div>
        <div>
          <span class="text-[11px] font-semibold text-gold-400 uppercase tracking-wider">Prompt técnico (Imagen):</span>
          <p class="text-slate-300 mt-1 text-[11px] leading-relaxed bg-royal-950/60 p-2.5 rounded-lg border border-white/5 font-mono">${s.image_prompt}</p>
        </div>
      </div>
    </div>
  `).join("");
}

// Paso 3: Galería de imágenes y aprobación
function renderStep3Gallery() {
  const container = document.getElementById("images-gallery-container");
  if (!container) return;

  container.innerHTML = appState.project.scenes.map(s => {
    const isApproved = s.image_status === "approved";
    const statusBadge = isApproved 
      ? `<span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40">✓ Aprobada</span>`
      : `<span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-400/40">⏳ Pendiente</span>`;

    const imgPreview = s.image_path 
      ? `<img src="${s.image_path}" alt="Escena ${s.order}" class="w-full h-48 object-cover rounded-xl border border-white/10 shadow-sm">`
      : `<div class="w-full h-48 bg-royal-950 border-2 border-dashed border-white/10 rounded-xl flex flex-col items-center justify-center text-slate-400 text-xs">
           <i data-lucide="image" class="w-7 h-7 mb-2 opacity-50"></i>
           <span>Sin imagen generada</span>
         </div>`;

    return `
      <div class="scene-card rounded-2xl p-4 flex flex-col justify-between space-y-3 shadow-lg">
        <div>
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-bold text-white">Escena #${s.order}</span>
            ${statusBadge}
          </div>
          ${imgPreview}
          <div class="mt-2 text-xs text-slate-300 line-clamp-2 leading-relaxed" title="${s.script_text}">
            "${s.script_text}"
          </div>
        </div>

        <div class="space-y-2 pt-2 border-t border-white/10">
          <textarea id="prompt-edit-${s.id}" rows="2" class="w-full bg-royal-950 border border-white/10 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-gold-400">${s.image_prompt}</textarea>
          
          <div class="grid grid-cols-2 gap-2">
            <button onclick="regenerateSceneImage('${s.id}')" id="btn-regen-${s.id}" class="btn-luxury-secondary flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl text-xs text-slate-200 font-medium transition">
              <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-gold-400"></i>
              <span>Regenerar</span>
            </button>

            <button onclick="approveSceneImage('${s.id}')" class="btn-gold flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl text-xs font-bold text-royal-950 transition shadow-sm">
              <i data-lucide="check" class="w-3.5 h-3.5 text-royal-950 stroke-[2.5]"></i>
              <span>${isApproved ? 'Aprobada' : 'Aprobar'}</span>
            </button>
          </div>

          <label class="block text-center py-2 px-3 rounded-xl bg-royal-950 hover:bg-royal-850 text-[11px] text-slate-300 hover:text-white border border-white/10 cursor-pointer transition font-medium">
            <input type="file" accept="image/png,image/jpeg,image/webp" class="hidden" onchange="uploadSceneCustomImage('${s.id}', this)">
            <span>📁 Subir imagen propia...</span>
          </label>
        </div>
      </div>
    `;
  }).join("");

  if (window.lucide) lucide.createIcons();
}

async function regenerateSceneImage(sceneId) {
  const promptInput = document.getElementById(`prompt-edit-${sceneId}`);
  if (promptInput) {
    const updatedPrompt = promptInput.value.trim();
    await fetch(`/api/projects/${appState.project.id}/scenes/${sceneId}/prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: updatedPrompt })
    });
  }

  const btn = document.getElementById(`btn-regen-${sceneId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin text-xs">⚙️</span>`;
  }

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/scenes/${sceneId}/generate-image`, { method: "POST" });
    if (!res.ok) throw new Error("Error generando imagen");
    const data = await res.json();
    
    // Actualizar escena local
    const idx = appState.project.scenes.findIndex(s => s.id === sceneId);
    if (idx !== -1) appState.project.scenes[idx] = data.scene;
    
    showToast("Imagen generada con éxito", "success");
    renderStep3Gallery();
  } catch (err) {
    showToast("Error generando imagen: " + err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function approveSceneImage(sceneId) {
  try {
    const res = await fetch(`/api/projects/${appState.project.id}/scenes/${sceneId}/approve`, { method: "POST" });
    if (!res.ok) throw new Error("No se pudo aprobar");
    const data = await res.json();
    const idx = appState.project.scenes.findIndex(s => s.id === sceneId);
    if (idx !== -1) appState.project.scenes[idx] = data.scene;
    renderStep3Gallery();
    showToast("Escena aprobada", "success");
  } catch (err) {
    showToast("Error aprobando imagen", "error");
  }
}

async function uploadSceneCustomImage(sceneId, input) {
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/scenes/${sceneId}/upload-image`, {
      method: "POST",
      body: formData
    });
    if (!res.ok) throw new Error("Error al subir archivo");
    const data = await res.json();
    const idx = appState.project.scenes.findIndex(s => s.id === sceneId);
    if (idx !== -1) appState.project.scenes[idx] = data.scene;
    showToast("Imagen propia cargada y aprobada", "success");
    renderStep3Gallery();
  } catch (err) {
    showToast("Error subiendo imagen", "error");
  }
}

async function generateAllPendingImages() {
  const btn = document.getElementById("btn-gen-all-images");
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin mr-2">⚙️</span> Generando lote...`;

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/generate-all-images`, { method: "POST" });
    if (!res.ok) throw new Error("Error en lote");
    appState.project = await res.json();
    showToast("¡Lote de imágenes procesado!", "success");
    renderStep3Gallery();
  } catch (err) {
    showToast("Error procesando lote de imágenes: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="wand-2" class="w-4 h-4 text-gold-400"></i><span>Generar Todas las Pendientes</span>`;
    if (window.lucide) lucide.createIcons();
  }
}

// --- ETAPA 4: NARRACIÓN Y AUDIO ---
function setAudioTab(mode) {
  const tabAi = document.getElementById("tab-audio-ai");
  const tabCustom = document.getElementById("tab-audio-custom");
  const panelAi = document.getElementById("audio-panel-ai");
  const panelCustom = document.getElementById("audio-panel-custom");

  if (mode === "ai") {
    tabAi.className = "py-3 px-6 text-sm font-semibold border-b-2 border-gold-400 text-gold-300 flex items-center gap-2 transition";
    tabCustom.className = "py-3 px-6 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2 transition";
    panelAi.classList.remove("hidden");
    panelCustom.classList.add("hidden");
  } else {
    tabCustom.className = "py-3 px-6 text-sm font-semibold border-b-2 border-gold-400 text-gold-300 flex items-center gap-2 transition";
    tabAi.className = "py-3 px-6 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2 transition";
    panelCustom.classList.remove("hidden");
    panelAi.classList.add("hidden");
  }
}

function renderStep4Audio() {
  const container = document.getElementById("scenes-audio-container");
  if (!container || !appState.project) return;

  container.innerHTML = appState.project.scenes.map(s => `
    <div class="scene-card rounded-xl p-4 flex flex-col md:flex-row items-center justify-between gap-4 shadow-sm">
      <div class="flex items-center gap-3 w-full md:w-1/2">
        <span class="w-7 h-7 rounded-lg bg-gold-500/15 border border-gold-500/25 text-gold-300 font-bold text-xs flex items-center justify-center shrink-0">#${s.order}</span>
        <div class="truncate">
          <p class="text-xs font-semibold text-slate-100 truncate">${s.script_text}</p>
          <p class="text-[11px] text-slate-400 font-medium">Duración: ${s.duration}s</p>
        </div>
      </div>

      <div class="flex items-center gap-3 w-full md:w-1/2 justify-end">
        ${s.audio_path ? `
          <audio controls src="${s.audio_path}" class="h-8 max-w-[240px]"></audio>
        ` : `
          <span class="text-xs text-amber-400">Audio no generado</span>
        `}

        <button onclick="regenerateSceneAudio('${s.id}')" id="btn-audio-${s.id}" class="btn-luxury-secondary px-3 py-1.5 rounded-lg text-xs text-slate-200 font-medium transition shrink-0" title="Regenerar audio para esta escena">
          <i data-lucide="refresh-cw" class="w-3.5 h-3.5 inline text-gold-400"></i>
        </button>
      </div>
    </div>
  `).join("");

  if (window.lucide) lucide.createIcons();
}

async function generateAllNarration() {
  // Guardar configuración de voz seleccionada
  appState.project.settings.voice_id = document.getElementById("voice-select").value;
  appState.project.settings.voice_speed = parseFloat(document.getElementById("voice-speed").value);
  appState.project.settings.voice_pitch = parseFloat(document.getElementById("voice-pitch").value);
  await saveProjectBasicInfo();

  const btn = document.getElementById("btn-gen-all-audio");
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin mr-2">⚙️</span> Sintetizando voces neuronales...`;

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/generate-narration`, { method: "POST" });
    if (!res.ok) throw new Error("Error sintetizando audio");
    appState.project = await res.json();
    showToast("¡Narración sintetizada con éxito!", "success");
    renderStep4Audio();
  } catch (err) {
    showToast("Error en narración: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="volume-2" class="w-4 h-4 text-gold-400"></i><span>Sintetizar Narración Completa</span>`;
    if (window.lucide) lucide.createIcons();
  }
}

async function regenerateSceneAudio(sceneId) {
  const btn = document.getElementById(`btn-audio-${sceneId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin text-xs">⚙️</span>`;
  }

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/scenes/${sceneId}/generate-audio`, { method: "POST" });
    if (!res.ok) throw new Error("Error al regenerar");
    const data = await res.json();
    const idx = appState.project.scenes.findIndex(s => s.id === sceneId);
    if (idx !== -1) appState.project.scenes[idx] = data.scene;
    showToast("Audio de escena actualizado", "success");
    renderStep4Audio();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleCustomAudioUpload(input) {
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/upload-custom-audio`, {
      method: "POST",
      body: formData
    });
    if (!res.ok) throw new Error("Error subiendo audio");
    appState.project = await res.json();
    
    // Mostrar reproductor de audio propio
    const playerContainer = document.getElementById("custom-audio-player-container");
    const audioElem = document.getElementById("custom-audio-elem");
    audioElem.src = appState.project.custom_audio_path;
    playerContainer.classList.remove("hidden");

    showToast("Audio propio cargado y sincronizado proporcionalmente", "success");
    renderStep4Audio();
  } catch (err) {
    showToast("Error subiendo archivo de audio propio: " + err.message, "error");
  }
}

// --- ETAPA 5: EDICIÓN Y MONTAJE ---
function renderStep5Timeline() {
  const container = document.getElementById("timeline-scenes-container");
  if (!container || !appState.project) return;

  let totalDur = 0;
  container.innerHTML = appState.project.scenes.map((s, idx) => {
    totalDur += parseFloat(s.duration || 4.0);
    const thumb = s.image_path 
      ? `<img src="${s.image_path}" class="w-20 h-14 object-cover rounded-lg border border-white/10 shadow-sm">`
      : `<div class="w-20 h-14 bg-royal-950 border border-white/10 rounded-lg flex items-center justify-center text-[10px] text-slate-500">Sin img</div>`;

    return `
      <div class="scene-card rounded-xl p-3.5 flex flex-col md:flex-row items-center justify-between gap-4 shadow-sm">
        <div class="flex items-center gap-3.5 w-full md:w-1/2">
          <div class="flex flex-col gap-1">
            <button onclick="moveSceneOrder(${idx}, -1)" ${idx === 0 ? 'disabled class="opacity-25"' : 'class="hover:text-gold-300 transition"'} title="Mover arriba">▲</button>
            <button onclick="moveSceneOrder(${idx}, 1)" ${idx === appState.project.scenes.length - 1 ? 'disabled class="opacity-25"' : 'class="hover:text-gold-300 transition"'} title="Mover abajo">▼</button>
          </div>
          ${thumb}
          <div class="truncate">
            <span class="text-xs font-bold text-white">Escena #${s.order}</span>
            <p class="text-xs text-slate-300 truncate font-normal">${s.script_text}</p>
          </div>
        </div>

        <div class="flex items-center gap-4 w-full md:w-1/2 justify-end">
          <div class="flex items-center gap-2">
            <label class="text-xs text-slate-400 font-medium">Duración:</label>
            <input type="number" step="0.5" min="2.0" max="60.0" value="${s.duration}" id="dur-scene-${s.id}" class="w-16 bg-royal-950 border border-white/10 rounded-lg px-2 py-1 text-xs text-white text-center font-bold" onchange="updateSceneDuration('${s.id}', this.value)">
            <span class="text-xs text-slate-400">s</span>
          </div>

          <div class="flex items-center gap-2">
            <label class="text-xs text-slate-400 font-medium">Transición:</label>
            <select id="trans-scene-${s.id}" class="bg-royal-950 border border-white/10 rounded-lg px-2.5 py-1 text-xs text-white" onchange="updateSceneTransition('${s.id}', this.value)">
              <option value="fade" ${s.transition === 'fade' ? 'selected' : ''}>Fade</option>
              <option value="dissolve" ${s.transition === 'dissolve' ? 'selected' : ''}>Dissolve</option>
              <option value="zoom_in" ${s.transition === 'zoom_in' ? 'selected' : ''}>Zoom In</option>
              <option value="pan_left" ${s.transition === 'pan_left' ? 'selected' : ''}>Pan</option>
              <option value="cut" ${s.transition === 'cut' ? 'selected' : ''}>Corte Directo</option>
            </select>
          </div>
        </div>
      </div>
    `;
  }).join("");

  document.getElementById("timeline-total-duration").innerText = `${totalDur.toFixed(1)}s`;
}

function updateSceneDuration(sceneId, val) {
  const scene = appState.project.scenes.find(s => s.id === sceneId);
  if (scene) {
    scene.duration = Math.max(2.0, parseFloat(val) || 3.0);
    renderStep5Timeline();
  }
}

function updateSceneTransition(sceneId, val) {
  const scene = appState.project.scenes.find(s => s.id === sceneId);
  if (scene) scene.transition = val;
}

function moveSceneOrder(idx, delta) {
  const targetIdx = idx + delta;
  if (targetIdx < 0 || targetIdx >= appState.project.scenes.length) return;
  const item = appState.project.scenes.splice(idx, 1)[0];
  appState.project.scenes.splice(targetIdx, 0, item);
  
  // Renumerar orden
  appState.project.scenes.forEach((s, i) => s.order = i + 1);
  renderStep5Timeline();
}

async function saveScenesAdjustments() {
  try {
    const res = await fetch(`/api/projects/${appState.project.id}/scenes`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenes: appState.project.scenes })
    });
    if (!res.ok) throw new Error("Error guardando ajustes");
    appState.project = await res.json();
    showToast("Ajustes de edición guardados correctamente", "success");
  } catch (err) {
    showToast("Error guardando ajustes", "error");
  }
}

// --- ETAPA 6: EXPORTACIÓN Y RENDERIZADO FINAL ---
function renderStep6Export() {
  if (appState.project.final_video_path) {
    showFinalVideo(appState.project.final_video_path);
  }
}

async function startVideoRender() {
  // Asegurar que las escenas estén guardadas
  await saveScenesAdjustments();

  const preBox = document.getElementById("render-pre-box");
  const progressBox = document.getElementById("render-progress-box");
  const resultBox = document.getElementById("render-result-box");

  preBox.classList.add("hidden");
  progressBox.classList.remove("hidden");
  resultBox.classList.add("hidden");

  try {
    const res = await fetch(`/api/projects/${appState.project.id}/render`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error iniciando render");
    }

    // Comenzar polling de estado
    if (appState.renderInterval) clearInterval(appState.renderInterval);
    appState.renderInterval = setInterval(pollRenderProgress, 1500);
  } catch (err) {
    preBox.classList.remove("hidden");
    progressBox.classList.add("hidden");
    showToast(`Error: ${err.message}`, "error");
  }
}

async function pollRenderProgress() {
  try {
    const res = await fetch(`/api/projects/${appState.project.id}/render-status`);
    const status = await res.json();

    const progressBar = document.getElementById("render-progress-bar");
    const statusMsg = document.getElementById("render-status-msg");
    const statusPct = document.getElementById("render-status-pct");

    progressBar.style.width = `${status.percent}%`;
    statusMsg.innerText = status.message || "Procesando...";
    statusPct.innerText = `${status.percent}%`;

    if (status.status === "completed") {
      clearInterval(appState.renderInterval);
      showToast("¡Video renderizado con éxito!", "success");
      showFinalVideo(status.final_video_path);
    } else if (status.status === "failed") {
      clearInterval(appState.renderInterval);
      document.getElementById("render-pre-box").classList.remove("hidden");
      document.getElementById("render-progress-box").classList.add("hidden");
      showToast(`Fallo en renderizado: ${status.message}`, "error");
    }
  } catch (err) {
    console.error("Error en polling:", err);
  }
}

function showFinalVideo(videoPath) {
  const preBox = document.getElementById("render-pre-box");
  const progressBox = document.getElementById("render-progress-box");
  const resultBox = document.getElementById("render-result-box");
  const videoElem = document.getElementById("final-video-player");
  const downloadBtn = document.getElementById("btn-download-video");

  preBox.classList.remove("hidden");
  progressBox.classList.add("hidden");
  resultBox.classList.remove("hidden");

  videoElem.src = videoPath;
  downloadBtn.href = videoPath;
  downloadBtn.setAttribute("download", `video_${appState.project.name || 'proyecto'}.mp4`);
}

// --- MODAL DE PROYECTOS ---
document.getElementById("btn-projects-modal").addEventListener("click", openProjectsModal);

async function openProjectsModal() {
  const modal = document.getElementById("projects-modal");
  const container = document.getElementById("projects-list-container");
  modal.classList.remove("hidden");

  try {
    const res = await fetch("/api/projects");
    const projects = await res.json();

    if (projects.length === 0) {
      container.innerHTML = `<div class="text-center py-6 text-slate-400 text-xs">No hay proyectos guardados.</div>`;
      return;
    }

    container.innerHTML = projects.map(p => `
      <div class="p-3.5 rounded-xl bg-royal-950/90 border border-white/10 hover:border-gold-400/40 flex items-center justify-between transition shadow-sm">
        <div>
          <h4 class="font-bold text-sm text-white">${p.name || 'Sin título'}</h4>
          <p class="text-xs text-slate-400">${p.scene_count || 0} escenas • Estado: <span class="text-gold-300 font-semibold uppercase">${p.status}</span></p>
        </div>

        <div class="flex items-center gap-2">
          <button onclick="loadProject('${p.id}'); closeProjectsModal();" class="btn-gold px-3.5 py-1.5 rounded-lg text-royal-950 text-xs font-bold shadow-sm">Abrir</button>
          <button onclick="deleteProject('${p.id}')" class="p-1.5 rounded-lg bg-red-900/30 hover:bg-red-900/60 text-red-300 text-xs border border-red-500/20">🗑️</button>
        </div>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<div class="text-red-400 text-xs text-center font-medium">Error al listar proyectos</div>`;
  }
}

function closeProjectsModal() {
  document.getElementById("projects-modal").classList.add("hidden");
}

async function deleteProject(id) {
  if (!confirm("¿Estás seguro de que deseas eliminar este proyecto y todos sus archivos?")) return;
  try {
    await fetch(`/api/projects/${id}`, { method: "DELETE" });
    showToast("Proyecto eliminado", "info");
    openProjectsModal();
    if (appState.project && appState.project.id === id) {
      loadLastProjectOrCreateDefault();
    }
  } catch (err) {
    showToast("Error eliminando proyecto", "error");
  }
}

// --- MODAL DE API KEY ---
function openApiKeyModal() {
  document.getElementById("apikey-modal").classList.remove("hidden");
}

function closeApiKeyModal() {
  document.getElementById("apikey-modal").classList.add("hidden");
}

async function saveApiKey() {
  const key = document.getElementById("input-api-key").value.trim();
  if (!key) {
    showToast("Introduce una clave válida", "error");
    return;
  }

  try {
    const res = await fetch("/api/config/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key })
    });
    if (!res.ok) throw new Error("Error guardando clave");
    showToast("Clave guardada exitosamente", "success");
    closeApiKeyModal();
    await loadSystemConfig();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

// --- UTILIDADES ---
function showToast(message, type = "info") {
  const toast = document.getElementById("toast");
  const msgElem = document.getElementById("toast-msg");
  const iconElem = document.getElementById("toast-icon");

  msgElem.innerText = message;
  iconElem.innerText = type === "success" ? "✓" : type === "error" ? "✕" : "ℹ";

  toast.classList.remove("hidden");
  setTimeout(() => {
    toast.classList.add("hidden");
  }, 4000);
}
