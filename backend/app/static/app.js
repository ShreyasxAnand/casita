    import * as THREE from 'three';
    import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

    const API_BASE = window.location.protocol === 'file:'
      ? 'http://127.0.0.1:8010'
      : (window.location.origin || 'http://127.0.0.1:8010');
    const FT_TO_M = 0.3048;
    const M2_TO_FT2 = 10.7639104167;
    const REAL3D_CONTEXT_PAD_M = 15;
    function getSelectedCity() {
      const el = document.getElementById('citySelect');
      const v = (el && el.value || '').trim().toLowerCase();
      return v || 'san_jose';
    }

    const els = {
      app: document.getElementById('app'),
      sidebarToggle: document.getElementById('sidebarToggle'),
      form: document.getElementById('siteForm'),
      citySelect: document.getElementById('citySelect'),
      address: document.getElementById('address'),
      aduTypeSeg: document.getElementById('aduTypeSeg'),
      aduTypeHint: document.getElementById('aduTypeHint'),
      aduWidth: document.getElementById('aduWidth'),
      aduDepth: document.getElementById('aduDepth'),
      loadBtn: document.getElementById('loadBtn'),
      snapBtn: document.getElementById('snapBtn'),
      unitToggle: document.getElementById('unitToggle'),
      debugToggle: document.getElementById('debugToggle'),
      rotation: document.getElementById('rotation'),
      height: document.getElementById('height'),
      statusDot: document.getElementById('statusDot'),
      statusText: document.getElementById('statusText'),
      stageList: document.getElementById('stageList'),
      stageLog: document.getElementById('stageLog'),
      checklistSummary: document.getElementById('checklistSummary'),
      sidebarWidth: document.getElementById('sidebarWidth'),
      sidebarDepth: document.getElementById('sidebarDepth'),
      sidebarHeight: document.getElementById('sidebarHeight'),
      sidebarHeightLabel: document.getElementById('sidebarHeightLabel'),
      sidebarHeightVal: document.getElementById('sidebarHeightVal'),
      sidebarSizeStat: document.getElementById('sidebarSizeStat'),
      sidebarRequirements: document.getElementById('sidebarRequirements'),
      metrics: document.getElementById('metrics'),
      phase1Checklist: document.getElementById('phase1Checklist'),
      phase2Checklist: document.getElementById('phase2Checklist'),
      phase2Section: document.getElementById('phase2Section'),
      phase2Title: document.getElementById('phase2Title'),
      sizeRecommendation: document.getElementById('sizeRecommendation'),
      aduTypeCards: document.getElementById('aduTypeCards'),
      debug: document.getElementById('debug'),
      view: document.getElementById('view3d'),
      floorMode: document.getElementById('floorMode'),
      checklistTab: document.getElementById('checklistTab'),
      modelTab: document.getElementById('modelTab'),
      real3dTab: document.getElementById('real3dTab'),
      financingTab: document.getElementById('financingTab'),
      checklistPanel: document.getElementById('checklistPanel'),
      modelPanel: document.getElementById('modelPanel'),
      real3dPanel: document.getElementById('real3dPanel'),
      financingPanel: document.getElementById('financingPanel'),
      rentCards: document.getElementById('rentCards'),
      financingNote: document.getElementById('financingNote'),
      cesiumContainer: document.getElementById('cesiumContainer'),
      real3dLightingOverlay: document.getElementById('real3dLightingOverlay'),
      googleTilesKey: document.getElementById('googleTilesKey'),
      loadReal3dBtn: document.getElementById('loadReal3dBtn'),
      syncReal3dBtn: document.getElementById('syncReal3dBtn'),
      focusReal3dBtn: document.getElementById('focusReal3dBtn'),
      streetReal3dBtn: document.getElementById('streetReal3dBtn'),
      aduWindowReal3dBtn: document.getElementById('aduWindowReal3dBtn'),
      lockReal3dBtn: document.getElementById('lockReal3dBtn'),
      real3dTimeOfDay: document.getElementById('real3dTimeOfDay'),
      real3dTimeLabel: document.getElementById('real3dTimeLabel'),
      real3dStatus: document.getElementById('real3dStatus'),
      aduWallColor: document.getElementById('aduWallColor'),
      aduRoofColor: document.getElementById('aduRoofColor'),
      aduDoorColor: document.getElementById('aduDoorColor'),
      aduWindowColor: document.getElementById('aduWindowColor'),
      aduRoofType: document.getElementById('aduRoofType'),
      aduDoorSide: document.getElementById('aduDoorSide'),
      aduWindowCount: document.getElementById('aduWindowCount'),
      aduWindowCountLabel: document.getElementById('aduWindowCountLabel'),
      parcelHud: document.getElementById('parcelHud'),
      buildableHud: document.getElementById('buildableHud'),
      aduHud: document.getElementById('aduHud'),
      imageryHud: document.getElementById('imageryHud'),
      houseRot: document.getElementById('houseRot'),
      houseResetBtn: document.getElementById('houseResetBtn'),
      showHousesBtn: document.getElementById('showHousesBtn'),
      hideStructureBtn: document.getElementById('hideStructureBtn'),
      houseEditBtn: document.getElementById('houseEditBtn'),
      houseHelp: document.getElementById('houseHelp'),
      helpHint: document.getElementById('helpHint'),
      // Add Plans (manual plan library)
      addPlansBtn: document.getElementById('addPlansBtn'),
      stepAddPlans: document.getElementById('stepAddPlans'),
      addPlansCloseBtn: document.getElementById('addPlansCloseBtn'),
      addPlanForm: document.getElementById('addPlanForm'),
      addPlanError: document.getElementById('addPlanError'),
      addPlanSubmit: document.getElementById('addPlanSubmit'),
      addPlansList: document.getElementById('addPlansList'),
      addPlansEmpty: document.getElementById('addPlansEmpty'),
      addPlansCityFilter: document.getElementById('addPlansCityFilter'),
    };

    let renderer, scene, camera, controls, raycaster, sun;
    let siteModel = null;
    let propertyStats = null;
    let zipContext = null;
    let financing = null;
    let aduTypeVal = 'detached'; // 'detached' | 'attached' | 'jadu'
    let standardsVal = 'city';  // 'city' | 'state'
    let displayUnit = localStorage.getItem('aduMvpUnit') || 'ft'; // 'ft' | 'm'
    let parcelGroup, buildingGroup, buildableGroup, imageryGroup, aduMesh;
    let imageryPlane = null;
    // House (existing building) drag state — translation+rotation applied as a
    // group transform; original ring data lives in siteModel.buildings[].
    let houseGroup = null;
    let hiddenHouseCount = 0;
    const DEBUG = (() => {
      try { return /(\?|&)debug=1\b/.test(location.search); }
      catch { return false; }
    })();
    function debugWarn(...args) { if (DEBUG) console.warn(...args); }
    function debugLog(...args) { if (DEBUG) console.log(...args); }
    if (DEBUG) {
      const dbgSec = document.getElementById('sidebarDebugSection');
      if (dbgSec) dbgSec.hidden = false;
    }
    let hideStructureMode = false;
    let floorMaterial = null;
    const floorTextureCache = new Map();
    let floorModeReady = new Set();
    let cesiumViewer = null;
    let googleTileset = null;
    // Long-lived Real-3D entity refs. Wrapping each in `{ entity }` lets
    // upsertGroundPolygon / upsertGroundOutline mutate the binding in place
    // without needing to re-import `let`s across many call sites.
    const floorRef = { entity: null };
    const contextFloorRef = { entity: null };
    const contextOutlineRef = { entity: null };
    const parcelFillRef = { entity: null };
    const parcelOutlineRef = { entity: null };
    let real3dAduFootprintEntity = null;
    let real3dKeyLoaded = null;
    let real3dCameraClampInstalled = false;
    let real3dSyncToken = 0;
    // Both heights stay `NaN` until a successful mesh sample produces a
    // real value. Renderers gate on `Number.isFinite(...)` so we never
    // anchor overlays at sea level by mistake.
    let real3dAduBaseHeightM = NaN;
    let real3dFloorHeightM = NaN;
    let real3dFloorReady = false;
    let real3dFloorSampleInFlight = false;

    let real3dPreviewLocked = false;
    let real3dGpuFallback = false;
    // The parcel floor estimate is one number for the whole parcel. To keep
    // the ADU glued to local mesh elevation (sloped sites, retaining walls,
    // raised pads), we sample the photorealistic mesh just outside the ADU
    // footprint on every sync. One in-flight probe at a time; the next sync
    // schedules a fresh one when the current finishes.
    let real3dAduProbeInFlight = false;
    // Parametric ADU model in the Real 3D view — replaces the legacy single
    // green box. All polygon entities composing the model are tracked here so
    // we can clear and rebuild them atomically whenever the ADU moves, resizes,
    // or its style changes.
    let aduModelEntities = [];
    const ADU_STYLE_DEFAULTS = Object.freeze({
      wallColor: '#d8c5a8',
      roofColor: '#3a3a40',
      doorColor: '#2a221a',
      windowColor: '#7894a3',
      roofType: 'gable',       // 'gable' | 'hip' | 'flat'
      doorSide: 'front',       // 'front' | 'back' | 'left' | 'right' | 'none'
      windowsPerSide: 2,       // 0–3
    });
    let aduStyle = (function loadAduStyle() {
      try {
        const raw = localStorage.getItem('aduMvpAduStyle');
        return raw ? { ...ADU_STYLE_DEFAULTS, ...JSON.parse(raw) } : { ...ADU_STYLE_DEFAULTS };
      } catch { return { ...ADU_STYLE_DEFAULTS }; }
    })();
    let selectedFrontEdgeIdx = null; // index into parcel rings_local[0] edges; null = not set
    let houseState = { x: 0, y: 0, rot: 0 };
    let houseEditMode = false;
    let houseEditTrim = null; // glow ring shown only in edit mode
    let aduState = { x: 0, y: 0, rot: 0, widthM: 18 * FT_TO_M, depthM: 24 * FT_TO_M, heightM: 16 * FT_TO_M };
    let aduValid = true;
    let drag = { active: false, offset: new THREE.Vector3(), plane: new THREE.Plane(new THREE.Vector3(0, 0, 1), 0) };

    // Polygon-clipping helpers (work in MultiPolygon = Array<Polygon>; each Polygon = Array<Ring> = Array<Array<[x,y]>>).
    const PC = (typeof window !== 'undefined' && window.polygonClipping) ? window.polygonClipping : null;
    if (!PC) debugWarn('polygon-clipping library failed to load — buildable-zone recompute will be skipped.');

    let serverGoogleTilesKey = '';

    initThree();
    els.googleTilesKey.value = localStorage.getItem('aduMvpGoogleTilesKey') || '';
    setStatus('Enter an address and click Load Site to begin.', '');

    fetch('/api/config').then(r => r.json()).then(cfg => {
      if (cfg.google_tiles_key) {
        serverGoogleTilesKey = cfg.google_tiles_key;
        const keyRow = els.googleTilesKey.closest('div');
        if (keyRow) keyRow.hidden = true;
      }
    }).catch(() => {});

    function setStatus(text, state = '') {
      els.statusDot.className = 'dot ' + state;
      els.statusText.textContent = text;
    }

    function disableBusy(disabled) {
      els.loadBtn.disabled = disabled;
      els.snapBtn.disabled = disabled || !siteModel;
    }

    async function postJson(path, body) {
      const res = await fetch(API_BASE + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const text = await res.text();
      const data = text ? JSON.parse(text) : {};
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      return data;
    }

    async function loadSite({ keepFrontEdge = false, lead = null } = {}) {
      const leadLat = lead && Number.isFinite(Number(lead.latitude)) ? Number(lead.latitude) : null;
      const leadLon = lead && Number.isFinite(Number(lead.longitude)) ? Number(lead.longitude) : null;
      const addressInput = els.address.value.trim();
      if (!addressInput && (leadLat == null || leadLon == null)) {
        setStatus('Enter an address to get started.', '');
        return;
      }
      if (!keepFrontEdge) selectedFrontEdgeIdx = null;
      setStatus('Loading parcel and building footprints...', 'busy');
      disableBusy(true);
      if (els.stageLog) {
        els.stageLog.removeAttribute('hidden');
        els.stageLog.innerHTML = '<div class="stage-log-loading"><span class="stage-log-spinner"></span><span>Analyzing property…</span></div>';
      }
      try {
        const siteRequest = {
          city: lead ? 'san_jose' : getSelectedCity(),
          address: addressInput || lead?.address || '',
          include_checklist: true,
          standards: standardsVal,
          adu_type: aduTypeVal,
          adu_stories: currentFloors,
          adu_width_ft: Number(els.aduWidth.value) || 30,
          adu_depth_ft: Number(els.aduDepth.value) || 40,
          adu_height_ft: Number(els.sidebarHeight?.value || els.height?.value) || 16,
          front_edge_index: selectedFrontEdgeIdx,
        };
        if (leadLat != null && leadLon != null) {
          siteRequest.latitude = leadLat;
          siteRequest.longitude = leadLon;
        }
        const data = await postJson('/api/site', siteRequest);
        siteModel = data.site_model;
        propertyStats = data.property_stats || null;
        zipContext = data.zip_context || null;
        financing = data.financing || null;
        renderFinancing();
        real3dAduBaseHeightM = NaN;
        real3dFloorHeightM = NaN;
        real3dFloorReady = false;
        real3dFloorSampleInFlight = false;
        real3dPreviewLocked = false;
        real3dGpuFallback = false;
        if (els.lockReal3dBtn) els.lockReal3dBtn.textContent = 'HQ Mode';
        resetReal3dForSiteChange();
        renderDebug(data);
        renderStages(data.stages || []);
        buildScene();
        renderFrontEdgePicker();
        // Compute best-fitting initial ADU dimensions for the 3D view.
        const initialAdu = chooseInitialAdu();
        if (initialAdu) {
          els.aduWidth.value = String(Math.round(initialAdu.widthFt));
          els.aduDepth.value = String(Math.round(initialAdu.depthFt));
        }
        syncSidebarDims();
        renderMetrics();
        // Two-phase checklist UI
        const _siteChecklistItems = data.checklist?.items || [];
        _allChecklistItems = _siteChecklistItems;
        renderPhase1(_siteChecklistItems);
        renderDataWarnings(data.data_warnings || []);
        renderAduPicker(data.property_stats);
        els.phase2Section.setAttribute('hidden', '');
        // If the user is currently looking at the Real 3D tab, rebuild scene.
        const real3dVisible = !els.real3dPanel.hidden;
        if (real3dVisible && cesiumViewer) {
          requestAnimationFrame(() => syncReal3dScene());
        }
        // UX reveal — show all deferred sections
        document.getElementById('welcomeState')?.remove();
        document.querySelector('.tabs')?.style && (document.querySelector('.tabs').style.display = '');
        document.querySelectorAll('.pre-load-hidden').forEach(el => {
          el.removeAttribute('hidden');
        });
        document.querySelectorAll('[data-post-load]').forEach(el => {
          el.removeAttribute('hidden');
        });
        setStatus('Site loaded — choose an ADU type to see design requirements.', 'ok');
        pushUrlState();
        { const cta = document.getElementById('complianceCta'); if (cta) cta.hidden = false; }
      } catch (err) {
        setStatus(err.message || 'Site failed to load', 'err');
      } finally {
        disableBusy(false);
      }
    }

    function initThree() {
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf7f7f7);
      // subtle atmospheric haze on long views
      scene.fog = new THREE.Fog(0xf7f7f7, 220, 600);
      camera = new THREE.PerspectiveCamera(38, 1, 0.1, 2000);
      camera.up.set(0, 0, 1);
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
      renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;
      els.view.appendChild(renderer.domElement);

      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.085;
      controls.rotateSpeed = 0.85;
      controls.zoomSpeed = 1.05;
      controls.panSpeed = 2.0;
      controls.enablePan = true;
      controls.screenSpacePanning = false;
      controls.keyPanSpeed = 24;
      controls.mouseButtons = {
        LEFT: THREE.MOUSE.PAN,
        MIDDLE: THREE.MOUSE.DOLLY,
        RIGHT: THREE.MOUSE.ROTATE,
      };
      controls.touches = {
        ONE: THREE.TOUCH.PAN,
        TWO: THREE.TOUCH.DOLLY_ROTATE,
      };
      controls.minPolarAngle = 0.02;
      controls.maxPolarAngle = Math.PI * 0.495; // can't go below the ground plane
      controls.minDistance = 4;
      controls.maxDistance = 1200;
      renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());
      raycaster = new THREE.Raycaster();

      // Sky-like soft fill + warm sun for that golden-hour real-estate feel.
      scene.add(new THREE.HemisphereLight(0xfff7e0, 0x6c7a72, 1.05));
      scene.add(new THREE.AmbientLight(0xffffff, 0.18));
      sun = new THREE.DirectionalLight(0xffe9c2, 2.5);
      sun.position.set(-32, -38, 80);
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      const S = 60;
      sun.shadow.camera.left = -S;
      sun.shadow.camera.right = S;
      sun.shadow.camera.top = S;
      sun.shadow.camera.bottom = -S;
      sun.shadow.camera.near = 1;
      sun.shadow.camera.far = 250;
      sun.shadow.bias = -0.0004;
      sun.shadow.normalBias = 0.02;
      sun.shadow.radius = 4;            // softer PCF
      sun.target.position.set(0, 0, 0);
      scene.add(sun);
      scene.add(sun.target);

      renderer.domElement.addEventListener('pointerdown', onPointerDown);
      renderer.domElement.addEventListener('pointermove', onPointerMove);
      renderer.domElement.addEventListener('pointerup', onPointerUp);
      renderer.domElement.addEventListener('pointermove', onHoverMove);
      renderer.domElement.addEventListener('pointerleave', () => setCursor('default'));
      window.addEventListener('resize', resize);
      resize();
      animate();
    }

    function resize() {
      if (els.modelPanel.hidden) return;
      const rect = els.view.getBoundingClientRect();
      renderer.setSize(Math.max(1, rect.width), Math.max(1, rect.height), false);
      camera.aspect = Math.max(1, rect.width) / Math.max(1, rect.height);
      camera.updateProjectionMatrix();
    }

    function animate(now) {
      requestAnimationFrame(animate);
      const t = now || performance.now();
      controls.update();
      tickAduColorTween();
      tickHouseEditPulse(t);
      // Skip the GPU pass entirely when the model viewer is not visible
      // (user is on the Checklist / Financing / Real 3D tabs). Still tick
      // tweens above so positions are correct when the tab is re-shown.
      if (els.modelPanel && !els.modelPanel.hidden) {
        renderer.render(scene, camera);
      }
    }

    // ---- Tweens & transitions ---------------------------------------------
    function tickAduColorTween() {
      if (!aduMesh) return;
      const target = aduMesh.userData.targetColor;
      if (target) {
        aduMesh.material.color.lerp(target, 0.18);
      }
      const targetOp = aduMesh.userData.targetOpacity ?? 1;
      const cur = aduMesh.material.opacity;
      if (Math.abs(cur - targetOp) > 0.005) {
        aduMesh.material.opacity = cur + (targetOp - cur) * 0.18;
        aduMesh.material.transparent = aduMesh.material.opacity < 0.99;
      }
    }

    function tickHouseEditPulse(now) {
      if (!houseEditTrim || !houseEditMode) return;
      // Gentle 0.6 Hz pulse on the edit-glow line opacity.
      const o = 0.55 + Math.sin(now * 0.0032) * 0.25;
      houseEditTrim.material.opacity = o;
    }

    // ---- Hover / cursor ---------------------------------------------------
    function setCursor(c) {
      renderer.domElement.style.cursor = c;
    }

    function onHoverMove(event) {
      if (drag.active) return; // drag handler controls cursor
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(mouse, camera);
      if (aduMesh) {
        if (raycaster.intersectObject(aduMesh, true).length) { setCursor('grab'); return; }
      }
      if (houseGroup) {
        if (raycaster.intersectObject(houseGroup, true).length) {
          setCursor(houseEditMode ? 'grab' : (hideStructureMode ? 'pointer' : 'default'));
          return;
        }
      }
      setCursor('default');
    }

    // ---- House edit-mode toggle ------------------------------------------
    function setHouseEditMode(on) {
      houseEditMode = on;
      if (on) setHideStructureMode(false);
      els.houseEditBtn.textContent = on ? 'Done editing' : 'Edit Position';
      els.houseEditBtn.style.background = on ? 'var(--brand)' : '';
      els.houseEditBtn.style.color = on ? 'var(--brand-ink)' : '';
      els.houseRot.disabled = !on;
      els.houseResetBtn.disabled = !on;
      els.houseHelp.innerHTML = on
        ? 'Drag the house, rotate, or use the slider. Click <strong>Done editing</strong> when aligned.'
        : 'Click <strong>Edit Position</strong> to align the house with the satellite. The buildable zone recalculates live.';
      els.helpHint.textContent = on
        ? 'Drag the house to align \u00B7 Click model tab to inspect \u00B7 Drag the green ADU \u00B7 Left-drag empty space to pan'
        : 'Click houses to hide \u00B7 Drag the green ADU \u00B7 Left-drag empty space to pan \u00B7 Right-drag to orbit';
      // Add / remove the editable glow line on the house footprint.
      if (houseEditTrim) {
        houseGroup?.remove(houseEditTrim);
        houseEditTrim.geometry.dispose();
        houseEditTrim.material.dispose();
        houseEditTrim = null;
      }
      if (on && houseGroup && siteModel?.buildings?.length) {
        const ring = siteModel.buildings[0].rings_local[0];
        const pts = ring.map(p => new THREE.Vector3(p[0], p[1], 0.09));
        houseEditTrim = new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: 0xffc857, transparent: true, opacity: 0.85 })
        );
        houseGroup.add(houseEditTrim);
      }
      setCursor('default');
    }

    function setHideStructureMode(on) {
      hideStructureMode = on;
      els.hideStructureBtn.textContent = on ? 'Done Hiding Structures' : 'Hide Structure Mode';
      els.hideStructureBtn.style.background = on ? 'var(--brand)' : '';
      els.hideStructureBtn.style.color = on ? 'var(--brand-ink)' : '';
      if (on && houseEditMode) setHouseEditMode(false);
      els.helpHint.textContent = on
        ? 'Click a house structure to hide it \u00B7 Click Done Hiding Structures when finished'
        : 'Drag the green ADU \u00B7 Left-drag empty space to pan \u00B7 Right-drag to orbit';
      setCursor('default');
    }

    function clearSceneGroup(group) {
      if (!group) return;
      scene.remove(group);
      group.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
          else obj.material.dispose();
        }
      });
    }

    function disposeMesh(mesh) {
      if (!mesh) return;
      if (mesh.geometry) mesh.geometry.dispose();
      const mats = Array.isArray(mesh.material) ? mesh.material : (mesh.material ? [mesh.material] : []);
      mats.forEach(m => m && m.dispose && m.dispose());
    }

    // ── Front property line picker ────────────────────────────────────────

    function renderFrontEdgePicker() {
      const picker = document.getElementById('frontEdgePicker');
      const svg = document.getElementById('frontEdgeSvg');
      if (!picker || !svg || !siteModel) return;

      const ring = siteModel.parcel?.rings_local?.[0];
      if (!ring || ring.length < 4) return;

      // Coordinate transform: local UTM meters → SVG pixels, Y flipped
      const SVG_SIZE = 200, PAD = 18;
      const xs = ring.map(p => p[0]), ys = ring.map(p => p[1]);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const w = (maxX - minX) || 1, h = (maxY - minY) || 1;
      const scale = (SVG_SIZE - 2 * PAD) / Math.max(w, h);
      const ox = PAD + ((SVG_SIZE - 2 * PAD) - w * scale) / 2;
      const oy = PAD + ((SVG_SIZE - 2 * PAD) - h * scale) / 2;
      const toSvg = (x, y) => [
        ox + (x - minX) * scale,
        SVG_SIZE - oy - (y - minY) * scale,
      ];

      // Closed ring: first and last point are the same; N-1 unique edges
      const n = ring.length;
      const isClosed = ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1];
      const edgeCount = isClosed ? n - 1 : n;

      let html = '';

      // Parcel fill
      const pts = ring.slice(0, isClosed ? n - 1 : n)
        .map(p => toSvg(p[0], p[1]).join(','))
        .join(' ');
      html += `<polygon points="${pts}" fill="rgba(94,173,168,0.10)" stroke="none"/>`;

      // Existing buildings for orientation context
      for (const b of (siteModel.buildings || [])) {
        const bRing = b.rings_local?.[0];
        if (!bRing) continue;
        const bPts = bRing.map(p => toSvg(p[0], p[1]).join(',')).join(' ');
        html += `<polygon points="${bPts}" fill="rgba(79,90,82,0.22)" stroke="rgba(79,90,82,0.4)" stroke-width="1"/>`;
      }

      // Buildable zone (green) — reflects front setback when a front edge is set
      for (const poly of (siteModel.buildable_zone?.polygons || [])) {
        const zRing = poly.rings_local?.[0];
        if (!zRing) continue;
        const zPts = zRing.map(p => toSvg(p[0], p[1]).join(',')).join(' ');
        html += `<polygon points="${zPts}" fill="rgba(58,163,92,0.28)" stroke="rgba(58,163,92,0.7)" stroke-width="1.2"/>`;
      }

      // Edges: visible thin line + wide transparent hit area per edge
      for (let i = 0; i < edgeCount; i++) {
        const p1 = toSvg(ring[i][0], ring[i][1]);
        const p2 = toSvg(ring[(i + 1) % n][0], ring[(i + 1) % n][1]);
        const d = `M${p1[0].toFixed(1)},${p1[1].toFixed(1)} L${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
        const selCls = i === selectedFrontEdgeIdx ? ' selected' : '';
        html += `<path class="fe-edge${selCls}" data-idx="${i}" d="${d}"/>`;
        html += `<path class="fe-hit" data-idx="${i}" d="${d}"/>`;
      }

      // North indicator
      html += `<text x="192" y="13" font-size="8" fill="rgba(94,160,156,0.7)" text-anchor="end" font-family="Inter,sans-serif" pointer-events="none">N↑</text>`;

      svg.innerHTML = html;

      // Wire hit areas: hover highlight + click to select
      svg.querySelectorAll('.fe-hit').forEach(hit => {
        const idx = Number(hit.dataset.idx);
        const edge = hit.previousElementSibling;

        hit.addEventListener('pointerenter', () => {
          if (idx !== selectedFrontEdgeIdx) edge.classList.add('hovered');
        });
        hit.addEventListener('pointerleave', () => {
          edge.classList.remove('hovered');
        });
        hit.addEventListener('click', () => {
          selectedFrontEdgeIdx = idx;
          renderFrontEdgePicker();
          _updateFrontEdgeMsg();
          loadSite({ keepFrontEdge: true });
        });
      });

      picker.hidden = false;
      _updateFrontEdgeMsg();
    }

    function _updateFrontEdgeMsg() {
      const msg = document.getElementById('frontEdgeMsg');
      if (!msg) return;
      if (selectedFrontEdgeIdx === null) {
        msg.innerHTML = 'Tap an edge to mark your front property line';
        msg.style.color = '';
      } else {
        msg.innerHTML =
          `<span style="color:var(--ok);font-weight:600;">✓ Front property line set</span>` +
          `<br><button class="front-edge-clear" id="frontEdgeClearBtn" type="button">Change selection</button>`;
        document.getElementById('frontEdgeClearBtn')?.addEventListener('click', () => {
          selectedFrontEdgeIdx = null;
          renderFrontEdgePicker();
          loadSite({ keepFrontEdge: true });
        });
      }
    }

    // ── Scene assembly ────────────────────────────────────────────────────
    // `buildScene()` orchestrates a full rebuild of the Three.js model viewer
    // from the current `siteModel`. Each phase is delegated to a small
    // single-purpose helper so the high-level sequence reads as a recipe.

    function buildScene(options = {}) {
      resetSceneGroups();
      buildSiteFloor();
      buildHouses();
      // Buildable-zone polygons are pre-computed by the backend; we just
      // render them here. Subsequent edits to the house trigger a client-side
      // recompute via `markSiteDirty()`.
      renderBuildableZone(siteModel.buildable_zone.polygons.map(p => p.rings_local));
      placeInitialAdu(options);
      frameSite();
      updateHud();
    }

    // Tear down all per-site Three.js groups and re-create fresh empties.
    // Separated so `buildScene` reads as a list of phases rather than a
    // 25-line preamble of disposal bookkeeping.
    function resetSceneGroups() {
      clearSceneGroup(parcelGroup);
      clearSceneGroup(buildingGroup);
      clearSceneGroup(buildableGroup);
      clearSceneGroup(imageryGroup);
      if (aduMesh) {
        scene.remove(aduMesh);
        disposeMesh(aduMesh);
        aduMesh = null;
      }
      imageryPlane = null;
      houseGroup = null;
      hiddenHouseCount = 0;
      updateShowHousesLabel();
      setHideStructureMode(false);
      // Dispose cached floor textures before dropping references so we do not
      // accumulate GPU memory when the user loads several addresses in a row.
      for (const tex of floorTextureCache.values()) tex?.dispose?.();
      floorTextureCache.clear();
      floorModeReady = new Set();
      floorMaterial = null;
      houseState = { x: 0, y: 0, rot: 0 };
      els.houseRot.value = '0';
      parcelGroup = new THREE.Group();
      buildingGroup = new THREE.Group();
      buildableGroup = new THREE.Group();
      imageryGroup = new THREE.Group();
      scene.add(imageryGroup, parcelGroup, buildingGroup, buildableGroup);
    }

    function buildSiteFloor() {
      buildParcelFloor();
      preloadBasemaps();
      addOutline(parcelGroup, siteModel.parcel.rings_local[0], 0.05, 0xffd54a, 2.4);
    }

    // Build the house group — all primary buildings packed inside one Group
    // so translate + rotate moves the whole house at once when the user
    // clicks Edit Position.
    function buildHouses() {
      houseGroup = new THREE.Group();
      houseGroup.userData.draggable = 'house';
      buildingGroup.add(houseGroup);
      for (const b of siteModel.buildings) {
        const itemGroup = new THREE.Group();
        itemGroup.userData.hideableHouse = true;
        itemGroup.userData.buildingId = b.id;
        // Use actual LiDAR height when available; no fudge factor. Minimum
        // 3.0 m (≈10 ft) so the model is always visible.
        const totalHm = Math.max(b.height_m, 3.0);
        itemGroup.add(buildHouseModel(b.rings_local, totalHm));
        addOutline(itemGroup, b.rings_local[0], 0.07, 0x4f5a52, 1.6);
        houseGroup.add(itemGroup);
      }
      setHouseEditMode(false); // start locked; user opts in
    }

    // Seed `aduState` from the best auto-fit placement, apply type-specific
    // snapping, and build the ADU mesh.
    function placeInitialAdu({ preserveDimensions = false } = {}) {
      const currentWidthFt = Number(els.aduWidth.value) || 30;
      const currentDepthFt = Number(els.aduDepth.value) || 40;
      const initialAdu = preserveDimensions ? null : chooseInitialAdu();
      const firstPlacement = preserveDimensions
        ? (findAduPlacement(currentWidthFt, currentDepthFt) || siteModel.adu.placements[0])
        : (initialAdu?.placement || siteModel.adu.placements[0]);
      if (initialAdu && !preserveDimensions) {
        els.aduWidth.value = String(Math.round(initialAdu.widthFt));
        els.aduDepth.value = String(Math.round(initialAdu.depthFt));
      }
      aduState.widthM = Number(els.aduWidth.value) * FT_TO_M;
      aduState.depthM = Number(els.aduDepth.value) * FT_TO_M;
      aduState.heightM = Number(els.height.value) * FT_TO_M;
      if (firstPlacement) {
        aduState.x = firstPlacement.center_local[0];
        aduState.y = firstPlacement.center_local[1];
        aduState.rot = firstPlacement.rotation_deg;
        els.snapBtn.disabled = false;
      } else {
        // No auto-fit candidate (e.g. ADU larger than buildable zone). Drop
        // the ADU at the parcel centroid so the user can still drag it and
        // see what fits. Always orient with the parcel so it doesn't look crooked.
        aduState.x = 0;
        aduState.y = 0;
        const propertyAxis = Number(siteModel?.adu?.suggested_rotation_deg || 0);
        aduState.rot = aduRotationForAxis(propertyAxis, aduState.widthM, aduState.depthM);
        els.snapBtn.disabled = true;
      }
      els.rotation.value = String(Math.round(aduState.rot));
      if (aduTypeVal === 'attached') snapInitialToWall();
      else if (aduTypeVal === 'jadu') snapInitialToHouseCenter();
      rebuildAdu();
    }

    function buildParcelFloor() {
      buildImageryPlane();
      applyFloorMode(els.floorMode?.value || 'satellite');
    }

    function makeShape(rings) {
      const shape = new THREE.Shape(rings[0].map(p => new THREE.Vector2(p[0], p[1])));
      for (let i = 1; i < rings.length; i++) {
        shape.holes.push(new THREE.Path(rings[i].map(p => new THREE.Vector2(p[0], p[1]))));
      }
      return shape;
    }

    function extrudeRings(rings, height, color) {
      const geom = new THREE.ExtrudeGeometry(makeShape(rings), { depth: height, bevelEnabled: false });
      geom.computeVertexNormals();
      const mesh = new THREE.Mesh(
        geom,
        new THREE.MeshStandardMaterial({
          color,
          roughness: 0.82,
          metalness: 0.02,
          transparent: true,
          opacity: 0.58,
          depthWrite: false,
        })
      );
      return mesh;
    }

    // ---------- House model: transparent mass from footprint -----------------
    /**
     * Build a transparent mass from the GIS footprint. Roof generation is
     * intentionally omitted because arbitrary parcel-service footprints were
     * producing unreliable roof holes.
     */
    function buildHouseModel(rings, totalHeightM) {
      const group = new THREE.Group();
      const wallMat = new THREE.MeshStandardMaterial({
        color: 0xd9c7aa,
        roughness: 0.92,
        metalness: 0,
        transparent: true,
        opacity: 0.52,
        depthWrite: false,
      });

      const wallGeom = new THREE.ExtrudeGeometry(makeShape(rings), { depth: totalHeightM, bevelEnabled: false });
      wallGeom.computeVertexNormals();
      const walls = new THREE.Mesh(wallGeom, wallMat);
      walls.castShadow = true;
      walls.receiveShadow = true;
      walls.userData.kind = 'house';
      group.add(walls);
      return group;
    }

    function addOutline(group, ring, z, color, width = 1) {
      const pts = ring.map(p => new THREE.Vector3(p[0], p[1], z));
      const line = new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color, linewidth: width })
      );
      group.add(line);
    }

    function rebuildAdu() {
      if (aduMesh) {
        scene.remove(aduMesh);
        disposeMesh(aduMesh);
      }
      const w = aduState.widthM;
      const d = aduState.depthM;
      const rings = [[
        [-w / 2, -d / 2],
        [w / 2, -d / 2],
        [w / 2, d / 2],
        [-w / 2, d / 2],
        [-w / 2, -d / 2],
      ]];
      aduMesh = extrudeRings(rings, aduState.heightM, 0x2f8f58);
      aduMesh.position.set(aduState.x, aduState.y, 0.08);
      aduMesh.rotation.z = THREE.MathUtils.degToRad(aduState.rot);
      aduMesh.castShadow = true;
      aduMesh.receiveShadow = true;
      aduMesh.userData.draggable = 'adu';
      setAduValidityMaterial(isAduValid(aduState.x, aduState.y, aduState.rot));
      scene.add(aduMesh);
      renderMetrics();
      updateHud();
      syncReal3dAdu();
      renderFinancing();
    }

    function updateAduSizeFromInputs() {
      if (!siteModel) return;
      aduState.widthM = Math.max(1, Number(els.aduWidth.value) || 18) * FT_TO_M;
      aduState.depthM = Math.max(1, Number(els.aduDepth.value) || 24) * FT_TO_M;
      rebuildAdu();
      schedulePushUrlState();
    }

    function setAduValidityMaterial(valid) {
      if (!aduMesh) return;
      aduValid = valid;
      // Set tween targets — animate loop lerps toward these for smooth feel.
      aduMesh.userData.targetColor = new THREE.Color(valid ? 0x2f8f58 : 0xb33a44);
      aduMesh.userData.targetOpacity = valid ? 0.62 : 0.42;
      els.statusText.textContent = valid
        ? 'ADU placement valid'
        : 'ADU is outside the buildable zone (overlapping setback / house clearance)';
      els.statusDot.className = valid ? 'dot ok' : 'dot err';
    }

    // ---- Buildable-zone live recompute ------------------------------------
    function renderBuildableZone(polygons, opts = {}) {
      clearSceneGroup(buildableGroup);
      buildableGroup = new THREE.Group();
      scene.add(buildableGroup);
      // Amber tint when the clip failed so the user knows the green region
      // is the parcel envelope, not a real buildable-zone calculation.
      const color = opts.degraded ? 0xd8b377 : 0x3aa35c;
      const opacity = opts.degraded ? 0.18 : 0.24;
      let total = 0;
      for (const rings of polygons) {
        if (!rings || !rings.length) continue;
        const mesh = new THREE.Mesh(
          new THREE.ShapeGeometry(makeShape(rings)),
          new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false })
        );
        mesh.position.z = 0.04;
        buildableGroup.add(mesh);
        total += polygonArea(rings[0]);
      }
      siteModel._buildableArea_ft2 = total * M2_TO_FT2;
      siteModel._buildableRings = polygons;
      siteModel._buildableDegraded = !!opts.degraded;
      if (opts.degraded) {
        setStatus('Buildable-zone clip failed — showing parcel envelope. Move the house to retry.', 'warn');
      }
      updateHud();
    }

    function polygonArea(ring) {
      let s = 0;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        s += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
      }
      return Math.abs(s) / 2;
    }

    function transformRing(ring, dx, dy, rotDeg) {
      const a = THREE.MathUtils.degToRad(rotDeg);
      const ca = Math.cos(a), sa = Math.sin(a);
      return ring.map(([x, y]) => [x * ca - y * sa + dx, x * sa + y * ca + dy]);
    }

    /**
     * Recompute the buildable zone from current house position.
     * buildable_new = parcel_eroded - union(translated inflated house polygons)
     */
    function recomputeBuildableZone() {
      if (!PC || !siteModel) return;
      const baseRingsList = (siteModel.buildable_zone.parcel_eroded_polygons || []).map(p => p.rings_local);
      if (!baseRingsList.length) return;
      // polygon-clipping expects MultiPolygon = Array<Polygon>; Polygon = Array<Ring>.
      const base = baseRingsList.map(rings => rings.map(closeRing));
      const inflated = (siteModel.buildings || [])
        .map(b => b.rings_local_inflated)
        .filter(Boolean)
        .map(rings => [transformRing(rings[0], houseState.x, houseState.y, houseState.rot)].map(closeRing));
      let result;
      let clipFailed = false;
      try {
        result = inflated.length
          ? PC.difference(base, ...inflated)
          : base;
      } catch (err) {
        debugWarn('polygon-clipping difference failed:', err);
        // Surface the failure instead of pretending the unclipped parcel is
        // the buildable zone — that would let the user place an ADU on top
        // of the existing house and call it valid.
        result = base;
        clipFailed = true;
      }
      const polysOuterOnly = result.map(poly => [poly[0]]);
      renderBuildableZone(polysOuterOnly, { degraded: clipFailed });
      // Re-evaluate ADU validity in the new zone.
      if (aduMesh) setAduValidityMaterial(isAduValid(aduState.x, aduState.y, aduState.rot));
    }

    function closeRing(ring) {
      if (!ring || !ring.length) return ring;
      const [x0, y0] = ring[0];
      const [xn, yn] = ring[ring.length - 1];
      return (x0 === xn && y0 === yn) ? ring : [...ring, [x0, y0]];
    }

    function frameSite(animate = true) {
      // Start in a clean top-down map view centered on the existing house.
      // The radius still uses the full ground quad/parcel so panning has room.
      let center = new THREE.Vector3(0, 0, 0);
      let radius = 30;
      const cs = siteModel?.imagery?.corners_local_m;
      if (cs && cs.length === 4) {
        const xs = cs.map(c => c[0]), ys = cs.map(c => c[1]);
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        center.set((minX + maxX) / 2, (minY + maxY) / 2, 0);
        radius = Math.max(maxX - minX, maxY - minY) * 0.62;
      } else {
        const box = new THREE.Box3().setFromObject(parcelGroup);
        box.getCenter(center);
        const size = box.getSize(new THREE.Vector3());
        radius = Math.max(size.x, size.y, 20);
      }
      if (houseGroup && houseGroup.children.length) {
        const houseBox = new THREE.Box3().setFromObject(houseGroup);
        if (!houseBox.isEmpty()) {
          houseBox.getCenter(center);
          center.z = 0;
        }
      }
      camera.near = 0.1;
      camera.far = 1500;
      camera.updateProjectionMatrix();

      const target = new THREE.Vector3(center.x, center.y, 0);
      const finalPos = new THREE.Vector3(center.x, center.y, Math.max(42, radius * 1.25));
      camera.position.copy(finalPos);
      controls.target.copy(target);
      controls.update();
    }

    function areaLabel() { return displayUnit === 'm' ? 'sq m' : 'sq ft'; }
    function areaValue(ft2) {
      if (ft2 == null || Number.isNaN(Number(ft2))) return null;
      return displayUnit === 'm' ? Number(ft2) / M2_TO_FT2 : Number(ft2);
    }
    function fmtArea(ft2) {
      const v = areaValue(ft2);
      if (v == null) return '—';
      return `${formatNumber(v)} ${areaLabel()}`;
    }

    function renderMetrics() {
      if (!siteModel) return;
      const aduAreaFt2 = aduState.widthM * aduState.depthM * M2_TO_FT2;
      const buildableFt2 = siteModel._buildableArea_ft2 ?? siteModel.buildable_zone.area_ft2;
      els.metrics.innerHTML = [
        metric(siteModel.parcel.area_ft2, `parcel ${areaLabel()}`),
        metric(buildableFt2, `buildable ${areaLabel()}`),
        metric(siteModel.buildings.reduce((s, b) => s + b.area_ft2, 0), 'existing footprint'),
        metric(aduAreaFt2, 'ADU footprint'),
      ].join('');
    }

    function metric(valueFt2, label) {
      const v = areaValue(valueFt2);
      return `<div class="metric"><strong>${v == null ? '—' : formatNumber(v)}</strong><span>${label}</span></div>`;
    }

    function renderDebug(data) {
      const sm = data.site_model || {};
      const zoning = (data.zoning && data.zoning.district) || {};
      const gp = (data.zoning && data.zoning.general_plan) || {};
      const designations = (data.zoning && data.zoning.designations) || {};
      const imagery = sm.imagery || {};
      const summary = {
        job_id: data.job_id,
        address_input: els.address.value.trim(),
        address_normalized: sm.address,
        geocode: { lat: sm.latitude, lon: sm.longitude },
        parcel: {
          apn: sm.parcel?.apn || null,
          site_address: sm.parcel?.site_address || null,
          area_ft2: sm.parcel?.area_ft2 || null,
        },
        zoning: zoning.zoning || null,
        zoning_full: zoning.zoning_full_name || null,
        general_plan: gp.gp_designation || null,
        designations,
        imagery: {
          provider: imagery.provider || null,
          crs_image: imagery.crs_image || null,
          width_px: imagery.width_px || null,
          height_px: imagery.height_px || null,
          corners_local_m: imagery.corners_local_m || null,
          url_image: imagery.url_image || null,
        },
        site_model_url: data.site_model_url,
      };
      els.debug.innerHTML = formatDebugHtml(summary);
    }

    function formatDebugHtml(obj) {
      const json = JSON.stringify(obj, null, 2);
      // Linkify any http(s) URL so the imagery URL is one click away.
      return escapeHtml(json).replace(
        /(https?:\/\/[^\s"]+)/g,
        '<a href="$1" target="_blank" rel="noreferrer" style="color:var(--info); text-decoration:underline">$1</a>'
      );
    }

    function renderStages(stages) {
      const log = els.stageLog;
      if (!log) return;
      log.removeAttribute('hidden');
      log.innerHTML = '';
      stages.forEach((s, i) => {
        const entry = document.createElement('div');
        entry.className = 'stage-log-entry';
        entry.style.animationDelay = `${i * 55}ms`;
        const dotClass = s.status === 'ok' ? 'ok' : s.status === 'failed' ? 'fail' : s.status === 'warn' ? 'warn' : '';
        const detailHtml = s.detail ? `: <span class="stage-log-detail">${escapeHtml(s.detail)}</span>` : '';
        entry.innerHTML = `
          <span class="stage-log-dot ${dotClass}"></span>
          <span class="stage-log-name">${escapeHtml(s.name)}${detailHtml}</span>
          <span class="stage-log-dur">${s.duration_ms || 0} ms</span>`;
        log.appendChild(entry);
      });
    }

    const _CHECK_ICONS = { pass: '✓', fail: '✗', verify: '!', info: 'i', unavailable: '–' };

    const _PART_LABELS = {
      1: 'Property Qualification',
      2: 'Property Designations',
      3: 'Development Standards',
      4: 'Fire Safety',
      5: 'Miscellaneous',
    };

    function _renderCheckItem(item) {
      const icon = _CHECK_ICONS[item.status] || '?';
      const st = escapeHtml(String(item.status));
      const qNum = item.number != null ? `<span class="check-partnum">Q${item.number}</span>` : '';
      return `<div class="check" data-status="${st}">
        <div class="check-row">
          <div class="check-icon ${st}">${icon}</div>
          <div>
            <div class="check-header">${qNum}<span class="check-q">${escapeHtml(item.question || '')}</span></div>
            <div class="check-detail">${escapeHtml(item.detail || '')}</div>
            ${item.source ? `<div class="meta">Source: ${escapeHtml(item.source)}</div>` : ''}
          </div>
        </div>
      </div>`;
    }

    function renderChecklistSummary(items) {
      const el = els.checklistSummary;
      if (!el) return;
      const counts = { fail: 0, verify: 0, pass: 0, unavailable: 0 };
      items.forEach(item => { if (item.status in counts) counts[item.status]++; });
      const parts = [];
      if (counts.fail) parts.push(`<span class="summary-pill fail">${counts.fail} issue${counts.fail !== 1 ? 's' : ''}</span>`);
      if (counts.verify) parts.push(`<span class="summary-pill verify">${counts.verify} to verify</span>`);
      if (counts.pass) parts.push(`<span class="summary-pill pass">${counts.pass} pass</span>`);
      if (counts.unavailable) parts.push(`<span class="summary-pill unavail">${counts.unavailable} unavailable</span>`);
      el.innerHTML = parts.join('');
      el.hidden = !parts.length;
    }

    function renderCheckItems(container, items) {
      if (!container) return;
      if (!items || !items.length) {
        container.innerHTML = '<div class="check" data-status="info"><div style="color:var(--text-soft);font-size:13px;">No items for this phase.</div></div>';
        return;
      }
      // Group by part
      const groups = new Map();
      items.forEach(item => {
        const p = item.part ?? 0;
        if (!groups.has(p)) groups.set(p, []);
        groups.get(p).push(item);
      });
      let html = '';
      for (const [part, partItems] of [...groups.entries()].sort((a, b) => a[0] - b[0])) {
        const label = _PART_LABELS[part] || `Part ${part}`;
        const failCount  = partItems.filter(i => i.status === 'fail').length;
        const verifyCount = partItems.filter(i => i.status === 'verify').length;
        let badgeCls, badgeTxt;
        if (failCount)        { badgeCls = 'fail';   badgeTxt = `${failCount} issue${failCount !== 1 ? 's' : ''}`; }
        else if (verifyCount) { badgeCls = 'verify'; badgeTxt = `${verifyCount} to verify`; }
        else                  { badgeCls = 'pass';   badgeTxt = 'All clear'; }
        html += `<div class="checklist-group">
          <div class="checklist-group-header">
            <span class="checklist-group-title">${escapeHtml(label)}</span>
            <span class="group-badge ${badgeCls}">${badgeTxt}</span>
          </div>
          <div class="checklist-group-items">${partItems.map(_renderCheckItem).join('')}</div>
        </div>`;
      }
      container.innerHTML = html;
    }

    function renderDataWarnings(warnings) {
      const banner = document.getElementById('dataWarningsBanner');
      if (!banner) return;
      if (!warnings || warnings.length === 0) { banner.hidden = true; return; }
      const names = warnings.map(w => escapeHtml(w.field.replace(/_/g, ' '))).join(', ');
      const plural = warnings.length === 1 ? 'service' : 'services';
      banner.className = 'data-warnings-banner';
      banner.hidden = false;
      banner.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#D97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <div>
          <strong>${warnings.length} GIS ${plural} unavailable</strong> — some checklist items show partial data.
          <div class="data-warnings-fields">Affected: ${names}</div>
        </div>
        <button class="data-warnings-dismiss" aria-label="Dismiss" type="button">×</button>`;
      banner.querySelector('.data-warnings-dismiss').addEventListener('click', () => { banner.hidden = true; });
    }

    function renderPhase1(items) {
      const phase1 = items.filter(item => item.part < 3 || (item.part === 3 && item.number === 10));
      renderChecklistSummary(phase1);
      renderCheckItems(els.phase1Checklist, phase1);
    }

    function backendConstraintsFor(type = aduTypeVal, floors = currentFloors) {
      const c = siteModel?.applied_constraints;
      if (!c) return null;
      if ((siteModel?.adu_type || '').toLowerCase() !== type) return null;
      if ((siteModel?.standards || '').toLowerCase() !== standardsVal) return null;
      if (Number(siteModel?.adu_stories || 1) !== Number(floors || 1)) return null;
      return c;
    }

    function regulatoryMaxSqft(type, parcelFt2, primarySqft) {
      // Use backend-resolved constraints when available and type matches
      const c = backendConstraintsFor(type);
      if (c?.max_adu_size_sf != null) return c.max_adu_size_sf;
      if (standardsVal === 'state') return type === 'jadu' ? 500 : 800;
      // Fallback: city-standard approximation for not-yet-selected cards.
      const SMALL_LOT = 9000, SMALL_CAP = 1000, LARGE_CAP = 1200;
      if (type === 'jadu') return 500;
      const lotCap = (!parcelFt2 || parcelFt2 < SMALL_LOT) ? SMALL_CAP : LARGE_CAP;
      if (type === 'attached' && primarySqft > 0) return Math.min(primarySqft * 0.5, lotCap);
      return lotCap;
    }

    const _ADU_ICONS = {
      detached: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><path d="M3 10.5L12 3l9 7.5V21a1 1 0 01-1 1H4a1 1 0 01-1-1V10.5z"/><path d="M9 22v-7h6v7"/></svg>`,
      attached:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><path d="M1 10.5L7 4l6 6.5V20H1V10.5z"/><path d="M13 11l4-4 6 4V20H13V11z"/></svg>`,
      jadu:      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><path d="M2 11L12 3l10 8V22H2V11z"/><path d="M9 22v-5h6v5"/><path d="M12 12v10" stroke-dasharray="2 2.5"/></svg>`,
    };
    const _CARD_CHECK = `<div class="adu-card-check" aria-hidden="true"><svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="2 6 5 9 10 3"/></svg></div>`;

    function renderAduPicker(stats) {
      if (!els.aduTypeCards) return;
      const parcelFt2 = siteModel?.parcel?.area_ft2 || 0;
      const primarySqft = (stats?.found && stats?.sqft) ? Number(stats.sqft) : 0;
      const types = [
        {
          val: 'detached',
          label: 'Detached',
          hint: standardsVal === 'state' ? 'Standalone, no siting restriction' : 'Standalone in rear yard',
        },
        { val: 'attached', label: 'Attached', hint: 'Shares wall with main home' },
        { val: 'jadu', label: 'JADU', hint: 'Within existing footprint' },
      ];
      els.aduTypeCards.innerHTML = types.map(t => {
        const maxSf = Math.round(regulatoryMaxSqft(t.val, parcelFt2, primarySqft));
        const sel = t.val === aduTypeVal;
        return `<div class="adu-card${sel ? ' selected' : ''}" data-type="${t.val}" role="radio" aria-checked="${sel}">
          <div class="adu-card-icon">${_ADU_ICONS[t.val] || ''}</div>
          <div class="adu-card-title">${t.label}</div>
          <div class="adu-card-hint" style="margin-bottom:14px;">${escapeHtml(t.hint)}</div>
          <div class="adu-card-max">${formatNumber(maxSf)}<span class="adu-card-max-unit"> sf</span></div>
          <div class="adu-card-hint">regulatory max</div>
          ${_CARD_CHECK}
        </div>`;
      }).join('');
    }

    function renderSizeCard(type, stats) {
      if (!els.sizeRecommendation) return;
      const parcelFt2 = siteModel?.parcel?.area_ft2 || 0;
      const primarySqft = (stats?.found && stats?.sqft) ? Number(stats.sqft) : 0;
      const regMax = Math.round(regulatoryMaxSqft(type, parcelFt2, primarySqft));
      const buildable = Math.round(siteModel?._buildableArea_ft2 ?? siteModel?.buildable_zone?.area_ft2 ?? 0);
      const suggested = buildable > 0 ? Math.min(regMax, buildable) : regMax;
      const w = Number(els.aduWidth.value) || 30;
      const d = Number(els.aduDepth.value) || 40;
      const current = w * d;
      const overLimit = current > suggested;
      els.sizeRecommendation.innerHTML = `
        <div class="size-recommendation-title">Maximum ADU Size</div>
        <div class="size-stats">
          <div class="size-stat">
            <strong>${formatNumber(regMax)} sf</strong>
            <span>Regulatory max</span>
          </div>
          <div class="size-stat">
            <strong>${buildable > 0 ? formatNumber(buildable) + ' sf' : 'N/A'}</strong>
            <span>Buildable zone</span>
          </div>
          <div class="size-stat highlight">
            <strong>${formatNumber(suggested)} sf</strong>
            <span>Suggested limit</span>
          </div>
        </div>
        <div style="margin-top:12px;font-size:12.5px;color:var(--text-soft);">
          Current model: <strong>${formatNumber(Math.round(current))} sf</strong> (${w} × ${d} ft).
          ${overLimit ? `<span style="color:var(--err);margin-left:6px;">Exceeds limit by ${formatNumber(Math.round(current - suggested))} sf.</span>` : ''}
        </div>`;
    }

    // All checklist items from the most recent type-fetch; used by the Checklist step.
    let _allChecklistItems = [];

    function renderSidebarLimits(type) {
      const card = document.getElementById('sidebarLimitsCard');
      const section = document.getElementById('sidebarLimitsSection');
      if (!card) return;

      const parcelFt2 = siteModel?.parcel?.area_ft2 || 0;
      const primarySqft = (propertyStats?.found && propertyStats?.sqft) ? Number(propertyStats.sqft) : 0;
      const maxSf = Math.round(regulatoryMaxSqft(type, parcelFt2, primarySqft));

      const maxHeightFt = _maxHeightForType(type, currentFloors);
      const floorLabel = type === 'detached'
        ? (currentFloors === 1 ? '1-story max' : '2-story max')
        : (type === 'jadu' ? 'matches existing' : null);
      const maxHeight = type === 'jadu'
        ? 'matches existing'
        : `${maxHeightFt} ft${floorLabel ? ` (${floorLabel})` : ''}`;

      const c = backendConstraintsFor(type);
      let setbackText;
      if (type === 'jadu') {
        setbackText = 'No independent setback — JADU must remain within the existing primary structure or attached garage.';
      } else if (c) {
        const parts = [`Front: ${c.front_setback_ft} ft`];
        if (c.siting_min_front_offset_ft != null) parts.push(`siting ≥ ${c.siting_min_front_offset_ft} ft from front`);
        parts.push(`Side: ${c.min_side_setback_ft} ft · Rear: ${c.min_rear_setback_ft} ft`);
        if (c.min_building_separation_ft != null) parts.push(`${c.min_building_separation_ft} ft from main home`);
        if (c.front_setback_encroachment_active) parts.push('Front setback waived (§20.80.176 — 800 sf rule)');
        setbackText = parts.join('. ');
      } else {
        const setbackByType = standardsVal === 'state'
          ? {
              detached: 'Side/rear: 4 ft. Front setback per zoning district unless the 800 sf state exception applies. No siting restriction.',
              attached: 'Side/rear: 4 ft. Front setback per zoning district unless the 800 sf state exception applies. No siting restriction.',
              jadu: 'No additional setback — within existing primary structure footprint.',
            }
          : {
              detached: '≥ 45 ft from front property line, or behind main home. Min 6 ft separation.',
              attached: 'Per zoning district Table 20-60. No additional side/rear setback required.',
              jadu: 'No additional setback — within existing primary structure footprint.',
            };
        setbackText = setbackByType[type] || '';
      }

      const w = Number(els.sidebarWidth?.value || els.aduWidth.value) || 30;
      const d = Number(els.sidebarDepth?.value || els.aduDepth.value) || 40;
      const currentSf = w * d;
      const over = currentSf > maxSf;

      card.innerHTML = `
        <div class="sidebar-limit-row">
          <span class="sidebar-limit-label">Max floor area</span>
          <span class="sidebar-limit-value${over ? ' over' : ''}">${formatNumber(maxSf)} sf</span>
        </div>
        <div class="sidebar-limit-row">
          <span class="sidebar-limit-label">Max height</span>
          <span class="sidebar-limit-value">${escapeHtml(maxHeight)}</span>
        </div>
        <div class="sidebar-setback-warn">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <span>${escapeHtml(setbackText)}</span>
        </div>`;
      if (section) section.hidden = false;
    }

    // Track dims at last checklist fetch so we can warn when they're stale
    let _checklistDims = { w: 0, d: 0, h: 0, floors: 0, type: '', standards: '' };

    function renderFullChecklist(items) {
      const summaryEl = document.getElementById('fullChecklistSummary');
      const container = document.getElementById('fullChecklist');
      const tabBar    = document.getElementById('checklistTabBar');
      if (!container) return;

      // Summary pills
      if (summaryEl) {
        const counts = { fail: 0, verify: 0, pass: 0, info: 0, unavailable: 0 };
        items.forEach(item => { if (item.status in counts) counts[item.status]++; });
        const parts = [];
        if (counts.fail)        parts.push(`<span class="summary-pill fail">${counts.fail} issue${counts.fail !== 1 ? 's' : ''}</span>`);
        if (counts.verify)      parts.push(`<span class="summary-pill verify">${counts.verify} to verify</span>`);
        if (counts.pass)        parts.push(`<span class="summary-pill pass">${counts.pass} pass</span>`);
        if (counts.unavailable) parts.push(`<span class="summary-pill unavail">${counts.unavailable} unavailable</span>`);
        summaryEl.innerHTML = parts.join('');
        summaryEl.hidden = !parts.length;
      }

      // Build per-part map
      const partGroups = new Map();
      items.forEach(item => {
        const p = item.part ?? 0;
        if (!partGroups.has(p)) partGroups.set(p, []);
        partGroups.get(p).push(item);
      });
      const sortedParts = [...partGroups.keys()].sort((a, b) => a - b);

      function partBadgeCls(pItems) {
        if (pItems.some(i => i.status === 'fail')) return 'fail';
        if (pItems.some(i => i.status === 'verify')) return 'verify';
        return 'pass';
      }

      function renderTabContent(part) {
        if (part === 'all') {
          renderCheckItems(container, items);
        } else {
          const pItems = partGroups.get(part) || [];
          container.innerHTML = pItems.length
            ? pItems.map(_renderCheckItem).join('')
            : '<div class="check" data-status="info"><div style="color:var(--text-soft);font-size:13px;">No items in this category.</div></div>';
        }
      }

      if (tabBar) {
        const allFail   = items.filter(i => i.status === 'fail').length;
        const allVerify = items.filter(i => i.status === 'verify').length;
        const allBadgeCls = allFail ? 'fail' : allVerify ? 'verify' : 'pass';
        const allBadgeNum = allFail || allVerify || items.filter(i => i.status === 'pass').length;

        const partTabsHtml = sortedParts.map(p => {
          const label = _PART_LABELS[p] || `Part ${p}`;
          const pItems = partGroups.get(p);
          const cls = partBadgeCls(pItems);
          const failN = pItems.filter(i => i.status === 'fail').length;
          const verN  = pItems.filter(i => i.status === 'verify').length;
          const badgeNum = failN || verN || pItems.length;
          return `<button class="checklist-tab-btn" data-part="${p}" role="tab" aria-selected="false">
            ${escapeHtml(label)}<span class="cl-tab-badge ${cls}">${badgeNum}</span>
          </button>`;
        }).join('');

        tabBar.innerHTML = `<button class="checklist-tab-btn active" data-part="all" role="tab" aria-selected="true">
          All<span class="cl-tab-badge ${allBadgeCls}">${allBadgeNum}</span>
        </button>${partTabsHtml}`;

        tabBar.querySelectorAll('.checklist-tab-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            tabBar.querySelectorAll('.checklist-tab-btn').forEach(b => {
              b.classList.remove('active');
              b.setAttribute('aria-selected', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');
            const raw = btn.dataset.part;
            renderTabContent(raw === 'all' ? 'all' : Number(raw));
          });
        });
      }

      renderTabContent('all');
    }

    function currentAduHeightFt() {
      return Number(els.sidebarHeight?.value || els.height?.value) || 16;
    }

    async function selectAduType(type) {
      applyAduType(type);
      els.aduTypeCards?.querySelectorAll('.adu-card').forEach(c => {
        const sel = c.dataset.type === type;
        c.classList.toggle('selected', sel);
        if (c.hasAttribute('aria-checked')) c.setAttribute('aria-checked', sel ? 'true' : 'false');
      });
      syncSidebarDims();
      // Reset to 1 floor for new type and update height slider max
      currentFloors = 1;
      document.getElementById('floorsToggle')?.querySelectorAll('.seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.floors === '1');
      });
      _updateHeightSlider(type, 1);
      renderSidebarLimits(type);
      const w = Number(els.sidebarWidth?.value || els.aduWidth.value) || 30;
      const d = Number(els.sidebarDepth?.value || els.aduDepth.value) || 40;
      const h = currentAduHeightFt();
      // Navigate to model immediately — the CTA uses whatever _allChecklistItems is
      // already available (seeded by loadSite). The fetch below will refine it.
      navigateWizard(4);
      pushUrlState();
      const ctaSection = document.getElementById('sidebarCtaSection');
      if (ctaSection) ctaSection.hidden = false;
      // Show sidebar requirements loading state
      const reqSection = document.getElementById('sidebarReqSection');
      if (reqSection) reqSection.hidden = false;
      if (els.sidebarRequirements) els.sidebarRequirements.innerHTML =
        '<div style="color:var(--text-faint);font-size:11px;padding:4px 0;">Loading…</div>';
      const refreshBtn = document.getElementById('refreshReqBtn');
      if (refreshBtn) refreshBtn.hidden = true;
      try {
        const data = await postJson('/api/site', {
          city: getSelectedCity(),
          address: els.address.value.trim(),
          include_checklist: true,
          standards: standardsVal,
          adu_type: type,
          adu_stories: currentFloors,
          adu_width_ft: w,
          adu_depth_ft: d,
          adu_height_ft: h,
          front_edge_index: selectedFrontEdgeIdx,
        });
        const items = data.checklist?.items || [];
        _allChecklistItems = items;
        _checklistDims = { w, d, h, floors: currentFloors, type, standards: standardsVal };
        const phase2 = items.filter(item => !(item.part < 3 || (item.part === 3 && item.number === 10)));
        if (data.site_model) {
          siteModel = data.site_model;
          propertyStats = data.property_stats || propertyStats;
          zipContext = data.zip_context || zipContext;
          financing = data.financing || financing;
          _updateHeightSlider(type, currentFloors);
          buildScene({ preserveDimensions: true });
          renderAduPicker(propertyStats);
          const real3dVisible = !els.real3dPanel.hidden;
          if (real3dVisible && cesiumViewer) requestAnimationFrame(() => syncReal3dScene());
        }
        renderSidebarRequirements(phase2);
        renderSidebarLimits(type);
        renderSidebarSizeStat();
        // Keep phase2Checklist in sync for back-compat
        renderCheckItems(els.phase2Checklist, phase2);
        renderSizeCard(type, propertyStats || data.property_stats);
        renderFinancing();
      } catch (err) {
        if (els.sidebarRequirements)
          els.sidebarRequirements.innerHTML =
            `<div style="color:var(--err);font-size:11px;">${escapeHtml(err.message || 'Failed to load requirements')}</div>`;
      }
    }

    function syncSidebarDims() {
      if (els.sidebarWidth)  els.sidebarWidth.value  = els.aduWidth.value;
      if (els.sidebarDepth)  els.sidebarDepth.value  = els.aduDepth.value;
      if (els.sidebarHeight) {
        els.sidebarHeight.value = els.height.value;
        if (els.sidebarHeightLabel) els.sidebarHeightLabel.textContent = els.height.value;
        if (els.sidebarHeightVal)   els.sidebarHeightVal.textContent   = els.height.value + ' ft';
      }
    }

    function renderSidebarSizeStat() {
      const el = els.sidebarSizeStat;
      if (!el || !siteModel) { if (el) el.hidden = true; return; }
      const w = Number(els.sidebarWidth?.value || els.aduWidth.value) || 30;
      const d = Number(els.sidebarDepth?.value || els.aduDepth.value) || 40;
      const current = w * d;
      const parcelFt2 = siteModel?.parcel?.area_ft2 || 0;
      const primarySqft = (propertyStats?.found && propertyStats?.sqft) ? Number(propertyStats.sqft) : 0;
      const regMax = Math.round(regulatoryMaxSqft(aduTypeVal, parcelFt2, primarySqft));
      const over = current > regMax;
      const diff = Math.abs(Math.round(current - regMax));
      el.hidden = false;
      el.innerHTML = `${formatNumber(Math.round(current))} sf &nbsp;·&nbsp; max ${formatNumber(regMax)} sf &nbsp;·&nbsp; <span class="${over ? 'ss-over' : 'ss-ok'}">${over ? `over ${formatNumber(diff)} sf` : `under ${formatNumber(diff)} sf`}</span>`;
    }

    function renderSidebarRequirements(items) {
      const el = els.sidebarRequirements;
      if (!el) return;
      if (!items || !items.length) { el.innerHTML = ''; return; }
      el.innerHTML = items.map(item => {
        const st = item.status || 'unavailable';
        const dotCls = ['pass','fail','verify','info'].includes(st) ? st : '';
        const q = item.question || '';
        // Strip the "Q##. " prefix for the short label — keep it readable at small size
        const shortQ = q.replace(/^Q[\d.]+\s+/, '');
        return `<div class="sidebar-req-item" data-status="${escapeHtml(st)}">
          <span class="sidebar-req-dot ${dotCls}"></span>
          <span class="sidebar-req-q">${escapeHtml(shortQ)}</span>
          <span class="sidebar-req-badge ${escapeHtml(st)}">${escapeHtml(st)}</span>
        </div>`;
      }).join('');
    }

    function updateHud() {
      if (!siteModel) return;
      const aduAreaFt2 = aduState.widthM * aduState.depthM * M2_TO_FT2;
      const buildableFt2 = siteModel._buildableArea_ft2 ?? siteModel.buildable_zone.area_ft2;
      els.parcelHud.textContent = fmtArea(siteModel.parcel.area_ft2);
      els.buildableHud.textContent = fmtArea(buildableFt2);
      els.aduHud.textContent = fmtArea(aduAreaFt2);
    }

    function pointerToGround(event) {
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(mouse, camera);
      const out = new THREE.Vector3();
      return raycaster.ray.intersectPlane(drag.plane, out) ? out : null;
    }

    function onPointerDown(event) {
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(mouse, camera);

      // ADU has priority since it sits on top.
      if (aduMesh) {
        const aduHits = raycaster.intersectObject(aduMesh, true);
        if (aduHits.length) {
          drag.active = true;
          drag.mode = 'adu';
          controls.enabled = false;
          setCursor('grabbing');
          const ground = pointerToGround(event);
          if (ground) drag.offset.set(aduState.x - ground.x, aduState.y - ground.y, 0);
          renderer.domElement.setPointerCapture(event.pointerId);
          return;
        }
      }
      if (hideStructureMode && !houseEditMode && houseGroup && event.button === 0) {
        const houseHits = raycaster.intersectObject(houseGroup, true);
        const hideTarget = houseHits.length ? findHideableHouse(houseHits[0].object) : null;
        if (hideTarget) {
          hideTarget.visible = false;
          hiddenHouseCount += 1;
          updateShowHousesLabel();
          setStatus('House hidden from model', 'ok');
          return;
        }
      }
      // House drags only when explicitly in Edit Position mode.
      if (houseEditMode && houseGroup) {
        const houseHits = raycaster.intersectObject(houseGroup, true);
        if (houseHits.length) {
          drag.active = true;
          drag.mode = 'house';
          controls.enabled = false;
          setCursor('grabbing');
          const ground = pointerToGround(event);
          if (ground) drag.offset.set(houseState.x - ground.x, houseState.y - ground.y, 0);
          renderer.domElement.setPointerCapture(event.pointerId);
        }
      }
    }

    function findHideableHouse(object) {
      let cur = object;
      while (cur && cur !== houseGroup) {
        if (cur.userData?.hideableHouse) return cur;
        cur = cur.parent;
      }
      return null;
    }

    function onPointerMove(event) {
      if (!drag.active) return;
      const ground = pointerToGround(event);
      if (!ground) return;

      if (drag.mode === 'adu' && aduMesh) {
        let nx = ground.x + drag.offset.x;
        let ny = ground.y + drag.offset.y;

        if (aduTypeVal === 'attached') {
          // Snap the nearest ADU face to the nearest house wall.
          const snapped = snapToHouseWall(nx, ny, aduState.rot);
          nx = snapped.x;
          ny = snapped.y;
        } else if (aduTypeVal === 'jadu') {
          // Clamp so all corners remain inside the house footprint.
          const clamped = clampAduToHouse(nx, ny, aduState.rot);
          nx = clamped.x;
          ny = clamped.y;
        }
        // Detached: free drag — validity shown by colour only.
        aduState.x = nx;
        aduState.y = ny;
        aduMesh.position.x = aduState.x;
        aduMesh.position.y = aduState.y;
        setAduValidityMaterial(isAduValid(aduState.x, aduState.y, aduState.rot));
        updateHud();
      } else if (drag.mode === 'house' && houseGroup) {
        houseState.x = ground.x + drag.offset.x;
        houseState.y = ground.y + drag.offset.y;
        markHouseDirty();
      }
    }

    // Single entry point for "the house moved or rotated". Performs the
    // cheap visual transform immediately, and queues the expensive
    // polygon-clipping recompute for the next animation frame so a rapid
    // sequence of mouse-move events still produces only one recompute.
    let _buildableRecomputeQueued = false;
    function markHouseDirty() {
      if (houseGroup) {
        houseGroup.position.set(houseState.x, houseState.y, 0);
        houseGroup.rotation.z = THREE.MathUtils.degToRad(houseState.rot);
      }
      if (_buildableRecomputeQueued) return;
      _buildableRecomputeQueued = true;
      requestAnimationFrame(() => {
        _buildableRecomputeQueued = false;
        recomputeBuildableZone();
      });
    }

    /**
     * Build the satellite ground plane.
     *
     * Backend computes the imagery quad's 4 corners in the same parcel-local
     * UTM frame as `siteModel.parcel.rings_local`. We build a BufferGeometry
     * quad from those corners with UVs (0,0)(1,0)(1,1)(0,1), so the texture
     * maps 1:1 onto the placement quad with zero client-side projection math.
     * The quad is essentially rectangular at residential scales (sub-mm
     * deviation), and aligns perfectly with parcel + building polygons.
     */
    function buildImageryPlane() {
      const imagery = siteModel.imagery;
      if (!imagery || !imagery.corners_local_m || imagery.corners_local_m.length !== 4) {
        els.imageryHud.textContent = 'No image';
        return;
      }
      const c = imagery.corners_local_m; // SW, SE, NE, NW

      // Two triangles: SW, SE, NE  and  SW, NE, NW
      const positions = new Float32Array([
        c[0][0], c[0][1], 0,
        c[1][0], c[1][1], 0,
        c[2][0], c[2][1], 0,
        c[0][0], c[0][1], 0,
        c[2][0], c[2][1], 0,
        c[3][0], c[3][1], 0,
      ]);
      // UV (0,0) at SW, (1,0) at SE, (1,1) at NE, (0,1) at NW. Note the
      // texture's pixel rows go top-down, so v=1 is the NORTH side. ArcGIS
      // returns north-up images, so this matches.
      const uvs = new Float32Array([
        0, 0,  1, 0,  1, 1,
        0, 0,  1, 1,  0, 1,
      ]);
      const normals = new Float32Array([
        0, 0, 1,  0, 0, 1,  0, 0, 1,
        0, 0, 1,  0, 0, 1,  0, 0, 1,
      ]);
      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geom.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
      geom.setAttribute('normal', new THREE.BufferAttribute(normals, 3));

      const material = new THREE.MeshStandardMaterial({
        color: 0x9aa89a,
        roughness: 1,
        metalness: 0,
        side: THREE.DoubleSide,
      });
      floorMaterial = material;

      imageryPlane = new THREE.Mesh(geom, material);
      // Push slightly below z=0 to avoid z-fighting with building base & ADU.
      imageryPlane.position.z = -0.02;
      imageryPlane.receiveShadow = true;
      imageryGroup.add(imageryPlane);
    }

    function basemapDescriptor(mode) {
      const imagery = siteModel?.imagery || {};
      if (mode === 'satellite') {
        return imagery.basemaps?.satellite || { label: 'Satellite', url_image: imagery.url_image };
      }
      if (mode === 'streets') {
        return imagery.basemaps?.streets;
      }
      return null;
    }

    function preloadBasemaps() {
      for (const mode of ['satellite', 'streets']) {
        const desc = basemapDescriptor(mode);
        if (desc?.url_image) loadFloorTexture(mode, desc);
      }
    }

    function applyFloorMode(mode) {
      if (!floorMaterial) return;
      if (mode === 'outline') {
        applyProceduralFloor(0xe7ece8, 0.96);
        els.imageryHud.textContent = 'Outline';
        return;
      }
      const desc = basemapDescriptor(mode);
      if (!desc?.url_image) { els.imageryHud.textContent = 'No map'; return; }
      const cached = floorTextureCache.get(mode);
      if (cached) {
        floorMaterial.map = cached;
        floorMaterial.color.set(0xffffff);
        floorMaterial.transparent = false;
        floorMaterial.opacity = 1;
        floorMaterial.needsUpdate = true;
        els.imageryHud.textContent = desc.label || mode;
        return;
      }
      els.imageryHud.textContent = 'Loading';
      loadFloorTexture(mode, desc).then(texture => {
        if ((els.floorMode?.value || 'satellite') !== mode || !floorMaterial) return;
        floorMaterial.map = texture;
        floorMaterial.color.set(0xffffff);
        floorMaterial.transparent = false;
        floorMaterial.opacity = 1;
        floorMaterial.needsUpdate = true;
        els.imageryHud.textContent = desc.label || mode;
      });
    }

    function applyProceduralFloor(color, opacity = 0.96) {
      if (!floorMaterial) return;
      floorMaterial.map = null;
      floorMaterial.color.set(color);
      floorMaterial.transparent = true;
      floorMaterial.opacity = opacity;
      floorMaterial.needsUpdate = true;
    }

    function loadFloorTexture(mode, desc) {
      if (floorTextureCache.has(mode)) return Promise.resolve(floorTextureCache.get(mode));
      const loader = new THREE.TextureLoader();
      return new Promise((resolve, reject) => {
        loader.load(desc.url_image, resolve, undefined, reject);
      }).then(texture => {
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        floorTextureCache.set(mode, texture);
        floorModeReady.add(mode);
        return texture;
      });
    }

    function onPointerUp(event) {
      if (!drag.active) return;
      drag.active = false;
      drag.mode = null;
      controls.enabled = true;
      setCursor('default');
      try { renderer.domElement.releasePointerCapture(event.pointerId); } catch (_e) {}
    }

    function pointInRing(x, y, ring) {
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
        const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-9) + xi);
        if (intersect) inside = !inside;
      }
      return inside;
    }

    function pointInRings(x, y, rings) {
      if (!pointInRing(x, y, rings[0])) return false;
      for (let i = 1; i < rings.length; i++) if (pointInRing(x, y, rings[i])) return false;
      return true;
    }

    function pointInBuildable(x, y) {
      const rings = siteModel?._buildableRings || (siteModel?.buildable_zone?.polygons || []).map(p => p.rings_local);
      return rings.some(r => pointInRings(x, y, r));
    }

    function aduCorners(x, y, rotationDeg) {
      const hw = aduState.widthM / 2;
      const hd = aduState.depthM / 2;
      const a = THREE.MathUtils.degToRad(rotationDeg);
      return [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]].map(([px, py]) => [
        x + px * Math.cos(a) - py * Math.sin(a),
        y + px * Math.sin(a) + py * Math.cos(a),
      ]);
    }

    function isAduValid(x, y, rotationDeg) {
      if (aduTypeVal === 'jadu') return isAduInsideHouse(x, y, rotationDeg);
      const corners = aduCorners(x, y, rotationDeg);
      const edgeSamples = [];
      for (let i = 0; i < corners.length; i++) {
        const a = corners[i];
        const b = corners[(i + 1) % corners.length];
        edgeSamples.push(a);
        edgeSamples.push([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
      }
      edgeSamples.push([x, y]);
      return edgeSamples.every(([px, py]) => pointInBuildable(px, py));
    }

    // ── House-geometry helpers for Attached / JADU placement ──────────────────

    /** Return all house polygon rings in world (scene-local) space. */
    function getHouseRingsWorld() {
      if (!siteModel?.buildings) return [];
      return siteModel.buildings.flatMap(b =>
        b.rings_local.map(ring => transformRing(ring, houseState.x, houseState.y, houseState.rot))
      );
    }

    /** Centroid of all house rings in world space. */
    function getHouseCentroid() {
      const houseRings = getHouseRingsWorld();
      if (!houseRings.length) return { x: 0, y: 0 };
      const pts = houseRings.flat();
      return {
        x: pts.reduce((s, p) => s + p[0], 0) / pts.length,
        y: pts.reduce((s, p) => s + p[1], 0) / pts.length,
      };
    }

    /** Check if a single point is inside any building footprint (world space). */
    function pointInHouseFootprint(px, py) {
      const houseRings = getHouseRingsWorld();
      // Group rings back into per-building chunks (each building has 1+ rings).
      // Since getHouseRingsWorld flattens all buildings, check individually.
      if (!siteModel?.buildings) return false;
      return siteModel.buildings.some(b => {
        const rings = b.rings_local.map(ring =>
          transformRing(ring, houseState.x, houseState.y, houseState.rot)
        );
        return pointInRings(px, py, rings);
      });
    }

    /** True when every corner of the ADU is inside any building footprint. */
    function isAduInsideHouse(x, y, rotationDeg) {
      return aduCorners(x, y, rotationDeg).every(([px, py]) => pointInHouseFootprint(px, py));
    }

    /**
     * Support function of the ADU rectangle in world direction (dx, dy).
     * Returns the half-extent of the ADU from its center to the farthest face
     * in that direction (used for snapping faces to house walls).
     */
    function aduSupportInDir(dx, dy, rotDeg) {
      const rotRad = THREE.MathUtils.degToRad(rotDeg);
      const cosR = Math.cos(rotRad), sinR = Math.sin(rotRad);
      // Transform direction to ADU-local space
      const lx = dx * cosR + dy * sinR;
      const ly = -dx * sinR + dy * cosR;
      return (aduState.widthM / 2) * Math.abs(lx) + (aduState.depthM / 2) * Math.abs(ly);
    }

    /**
     * Snap the ADU center to the nearest house wall edge (for Attached ADU).
     * The ADU slides along the wall, keeping one face flush with it.
     */
    function snapToHouseWall(rawX, rawY, rotDeg) {
      const houseRings = getHouseRingsWorld();
      let bestDist = Infinity;
      let bestX = rawX, bestY = rawY;

      for (const ring of houseRings) {
        const n = ring.length;
        // Treat as closed polygon; skip duplicate closing vertex if present.
        const closed = n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1];
        const m = closed ? n - 1 : n;

        for (let i = 0; i < m; i++) {
          const [ax, ay] = ring[i];
          const [bx, by] = ring[(i + 1) % m];
          const ex = bx - ax, ey = by - ay;
          const edgeLen = Math.sqrt(ex * ex + ey * ey);
          if (edgeLen < 0.05) continue;

          const tx = ex / edgeLen, ty = ey / edgeLen;

          // Project the raw drag point onto the edge segment.
          const pdx = rawX - ax, pdy = rawY - ay;
          let t = pdx * tx + pdy * ty;
          t = Math.max(0, Math.min(edgeLen, t));
          const px = ax + tx * t;   // closest point on edge
          const py = ay + ty * t;

          // Both outward perpendicular directions from this edge.
          for (const sign of [1, -1]) {
            // Perpendicular (one of the two outward candidates).
            const nx = -ty * sign, ny = tx * sign;

            // ADU half-extent in this outward direction (which face will touch the wall).
            const halfExt = aduSupportInDir(nx, ny, rotDeg);

            // Candidate ADU center position.
            const cx = px + nx * halfExt;
            const cy = py + ny * halfExt;

            const dist = Math.hypot(cx - rawX, cy - rawY);
            if (dist < bestDist) {
              bestDist = dist;
              bestX = cx;
              bestY = cy;
            }
          }
        }
      }
      return { x: bestX, y: bestY };
    }

    /**
     * Clamp the ADU center so all its corners stay inside the house footprint (for JADU).
     * If the current position is already valid, return it unchanged.
     * Otherwise, move toward the house centroid until valid.
     */
    function clampAduToHouse(rawX, rawY, rotDeg) {
      if (isAduInsideHouse(rawX, rawY, rotDeg)) return { x: rawX, y: rawY };
      const { x: cx, y: cy } = getHouseCentroid();
      // Step from raw position toward centroid in 16 increments.
      for (let s = 1; s <= 16; s++) {
        const nx = rawX + (cx - rawX) * (s / 16);
        const ny = rawY + (cy - rawY) * (s / 16);
        if (isAduInsideHouse(nx, ny, rotDeg)) return { x: nx, y: ny };
      }
      return { x: cx, y: cy };
    }

    /**
     * For Attached ADU: initial placement — snap to the nearest house wall
     * from whatever position the auto-fit algorithm chose.
     */
    function snapInitialToWall() {
      const snapped = snapToHouseWall(aduState.x, aduState.y, aduState.rot);
      aduState.x = snapped.x;
      aduState.y = snapped.y;
    }

    /**
     * For JADU: initial placement — move to house centroid (always inside).
     */
    function snapInitialToHouseCenter() {
      const { x, y } = getHouseCentroid();
      aduState.x = x;
      aduState.y = y;
    }

    function maxCurrentAduAreaFt2() {
      const parcelArea = Number(siteModel?.parcel?.area_ft2 || 0);
      const primarySqft = (propertyStats?.found && propertyStats?.sqft) ? Number(propertyStats.sqft) : 0;
      return regulatoryMaxSqft(aduTypeVal, parcelArea, primarySqft) || 1200;
    }

    function normalizeAngleDeg(angleDeg) {
      return ((angleDeg + 180) % 360) - 180;
    }

    function aduRotationForAxis(axisAngleDeg, widthM, depthM) {
      // ADU rotation is the local width-axis angle. If the footprint is deeper
      // than wide, rotate so the depth axis follows the property axis.
      return normalizeAngleDeg(axisAngleDeg - (depthM > widthM ? 90 : 0));
    }

    function addUniqueAngle(angles, angleDeg) {
      const normalized = normalizeAngleDeg(angleDeg);
      if (!angles.some(existing => Math.abs(existing - normalized) <= 1)) {
        angles.push(normalized);
      }
    }

    function candidateAduRotations(widthM, depthM) {
      const propertyAxis = Number(siteModel?.adu?.suggested_rotation_deg || 0);
      const angles = [];
      for (const axis of [propertyAxis, propertyAxis + 90]) {
        addUniqueAngle(angles, aduRotationForAxis(axis, widthM, depthM));
      }
      return angles;
    }

    function buildableBounds() {
      const rings = siteModel?._buildableRings || [];
      const pts = rings.flatMap(poly => poly[0] || []);
      if (!pts.length) return null;
      const xs = pts.map(p => p[0]);
      const ys = pts.map(p => p[1]);
      return {
        minX: Math.min(...xs),
        maxX: Math.max(...xs),
        minY: Math.min(...ys),
        maxY: Math.max(...ys),
      };
    }

    function findAduPlacement(widthFt, depthFt) {
      const oldW = aduState.widthM;
      const oldD = aduState.depthM;
      aduState.widthM = widthFt * FT_TO_M;
      aduState.depthM = depthFt * FT_TO_M;
      const bounds = buildableBounds();
      const angles = candidateAduRotations(aduState.widthM, aduState.depthM);
      const preferredAngle = angles[0]; // dominant parcel-axis rotation — always prefer this
      let preferred = null;
      let fallback = null;
      if (bounds) {
        const step = Math.max(1.2, Math.min(widthFt, depthFt) * FT_TO_M / 3);
        for (const angle of angles) {
          for (let x = bounds.minX; x <= bounds.maxX; x += step) {
            for (let y = bounds.minY; y <= bounds.maxY; y += step) {
              if (!isAduValid(x, y, angle)) continue;
              const score = -Math.hypot(x, y);
              if (angle === preferredAngle) {
                if (!preferred || score > preferred.score) preferred = { center_local: [x, y], rotation_deg: angle, score };
              } else {
                if (!fallback || score > fallback.score) fallback = { center_local: [x, y], rotation_deg: angle, score };
              }
            }
          }
        }
      }
      aduState.widthM = oldW;
      aduState.depthM = oldD;
      return preferred || fallback;
    }

    function chooseInitialAdu() {
      if (!siteModel) return null;
      const buildableArea = Number(siteModel._buildableArea_ft2 ?? siteModel.buildable_zone?.area_ft2 ?? 0);
      const maxArea = maxCurrentAduAreaFt2();
      const targetArea = Math.max(80, Math.min(maxArea, buildableArea || maxArea));
      const aspect = 24 / 32; // width:depth, close to the app's original 18x24 proportion.
      const candidates = [];
      for (let area = targetArea; area >= 120; area *= 0.90) {
        let width = Math.sqrt(area * aspect);
        let depth = area / width;
        width = Math.max(8, Math.min(40, width));
        depth = Math.max(8, Math.min(80, depth));
        candidates.push([width, depth], [depth, width]);
        if (area < 140) break;
      }
      for (const [width, depth] of candidates) {
        const placement = findAduPlacement(width, depth);
        if (placement) return { widthFt: width, depthFt: depth, placement };
      }
      return null;
    }

    function formatNumber(v) {
      if (v == null || Number.isNaN(Number(v))) return 'N/A';
      return Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      })[ch]);
    }

    function externalLinkHtml(url, label) {
      const href = String(url || '');
      if (!/^https?:\/\//i.test(href)) return '';
      return '<a class="lead-source-link" href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' +
        escapeHtml(label) +
      '</a>';
    }

    function ensureUtmProjection() {
      if (!window.proj4) return false;
      if (!window.proj4.defs('EPSG:26910')) {
        window.proj4.defs('EPSG:26910', '+proj=utm +zone=10 +datum=NAD83 +units=m +no_defs +type=crs');
      }
      return true;
    }

    function localMetersToLonLat(x, y) {
      const originUtm = siteModel?.origin_utm;
      if (originUtm && ensureUtmProjection()) {
        const projected = window.proj4('EPSG:26910', 'EPSG:4326', [
          Number(originUtm.x || 0) + x,
          Number(originUtm.y || 0) + y,
        ]);
        return { longitude: projected[0], latitude: projected[1] };
      }
      const origin = siteLonLat();
      const lat0 = Number(origin.latitude || siteModel?.latitude || 0);
      const lon0 = Number(origin.longitude || siteModel?.longitude || 0);
      const metersPerDegLat = 111320;
      const metersPerDegLon = metersPerDegLat * Math.cos(THREE.MathUtils.degToRad(lat0 || 37.3));
      return {
        longitude: lon0 + x / metersPerDegLon,
        latitude: lat0 + y / metersPerDegLat,
      };
    }

    function lonLatToLocalMeters(longitude, latitude) {
      const originUtm = siteModel?.origin_utm;
      if (originUtm && ensureUtmProjection()) {
        const projected = window.proj4('EPSG:4326', 'EPSG:26910', [longitude, latitude]);
        return {
          x: projected[0] - Number(originUtm.x || 0),
          y: projected[1] - Number(originUtm.y || 0),
        };
      }
      const origin = siteLonLat();
      const metersPerDegLat = 111320;
      const metersPerDegLon = metersPerDegLat * Math.cos(THREE.MathUtils.degToRad(origin.latitude || 37.3));
      return {
        x: (longitude - origin.longitude) * metersPerDegLon,
        y: (latitude - origin.latitude) * metersPerDegLat,
      };
    }

    function parcelPositionsDegrees() {
      const coords = siteModel?.parcel?.geojson?.coordinates?.[0] || [];
      return coords.flatMap(([lon, lat]) => [lon, lat]);
    }

    function closedParcelCoords() {
      const coords = siteModel?.parcel?.geojson?.coordinates?.[0] || [];
      if (coords.length < 3) return [];
      const first = coords[0];
      const last = coords[coords.length - 1];
      const isClosed = Math.abs(first[0] - last[0]) < 1e-10 && Math.abs(first[1] - last[1]) < 1e-10;
      return isClosed ? coords : [...coords, first];
    }

    function siteLonLat() {
      const originUtm = siteModel?.origin_utm;
      if (originUtm && ensureUtmProjection()) {
        const projected = window.proj4('EPSG:26910', 'EPSG:4326', [
          Number(originUtm.x || 0),
          Number(originUtm.y || 0),
        ]);
        return { longitude: projected[0], latitude: projected[1] };
      }
      const coords = closedParcelCoords();
      if (coords.length > 1) {
        const open = coords.slice(0, -1);
        const sums = open.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1]], [0, 0]);
        return { longitude: sums[0] / open.length, latitude: sums[1] / open.length };
      }
      return {
        longitude: Number(siteModel?.longitude || 0),
        latitude: Number(siteModel?.latitude || 0),
      };
    }

    function distanceMeters(a, b) {
      const latM = 111320;
      const lonM = latM * Math.cos(THREE.MathUtils.degToRad(a.latitude || 37.3));
      const dx = (b.longitude - a.longitude) * lonM;
      const dy = (b.latitude - a.latitude) * latM;
      return Math.hypot(dx, dy);
    }

    function real3dContextClipCoords(padM = REAL3D_CONTEXT_PAD_M) {
      const ring = siteModel?.parcel?.rings_local?.[0] || [];
      if (ring.length >= 4) {
        const xs = ring.map(p => p[0]);
        const ys = ring.map(p => p[1]);
        const minX = Math.min(...xs) - padM;
        const maxX = Math.max(...xs) + padM;
        const minY = Math.min(...ys) - padM;
        const maxY = Math.max(...ys) + padM;
        return [
          localMetersToLonLat(minX, minY),
          localMetersToLonLat(maxX, minY),
          localMetersToLonLat(maxX, maxY),
          localMetersToLonLat(minX, maxY),
          localMetersToLonLat(minX, minY),
        ].map(p => [p.longitude, p.latitude]);
      }
      return closedParcelCoords();
    }

    function aduLonLatCorners() {
      const corners = aduCorners(aduState.x, aduState.y, aduState.rot || 0);
      return corners.map(([x, y]) => localMetersToLonLat(x, y));
    }

    function flatLonLatHeights(lonLats, heights, liftM = 0) {
      return lonLats.flatMap((p, i) => [p.longitude, p.latitude, (heights[i] || 0) + liftM]);
    }

    function lonLatToCartographic(p) {
      return Cesium.Cartographic.fromDegrees(p.longitude, p.latitude);
    }

    // ── Real-3D ground-elevation estimation ────────────────────────────────
    // The Google photorealistic mesh is the ground truth for elevation. We
    // sample heights from the mesh at carefully chosen points (perimeter +
    // grid, excluding building footprints), take the median, and drop high
    // outliers (trees / fences / neighbouring roofs).
    //
    // Sampling can fail two ways: (1) `sampleHeightMostDetailed` may not be
    // available, or (2) tiles for the parcel area haven't streamed in yet.
    // Both manifest as fewer than 3 valid samples — in that case the
    // estimator returns `null`, callers leave the floor height undefined,
    // and the tileset's `initialTilesLoaded` / `allTilesLoaded` events
    // trigger a retry until we get a real value.

    async function sampleReal3dHeights(lonLats) {
      if (!cesiumViewer?.scene || typeof cesiumViewer.scene.sampleHeightMostDetailed !== 'function') {
        return lonLats.map(() => null);
      }
      try {
        const samples = await cesiumViewer.scene.sampleHeightMostDetailed(lonLats.map(lonLatToCartographic));
        return samples.map(s => Number.isFinite(s?.height) ? s.height : null);
      } catch (_err) {
        return lonLats.map(() => null);
      }
    }

    function percentile(values, pct) {
      const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
      if (!sorted.length) return null;
      const idx = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * pct)));
      return sorted[idx];
    }

    function isInsideAnyBuilding(x, y) {
      const buildings = siteModel?.buildings || [];
      for (const b of buildings) {
        const rings = b.rings_local;
        if (rings && rings.length && pointInRings(x, y, rings)) return true;
      }
      return false;
    }

    // Build the set of lon/lat sample locations that are likely to be REAL
    // ground (i.e. not on top of a building). Caller is responsible for
    // dropping rooftop-like outliers downstream.
    function real3dFloorSamplePoints() {
      const points = [];
      const seen = new Set();
      const addLocal = (x, y) => {
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        if (isInsideAnyBuilding(x, y)) return;
        // ~25 cm dedup grid — perimeter walks plus grid sampling can produce
        // near-duplicates that don't add information.
        const key = `${Math.round(x * 4)}_${Math.round(y * 4)}`;
        if (seen.has(key)) return;
        seen.add(key);
        points.push({ x, y });
      };

      const parcelRing = siteModel?.parcel?.rings_local?.[0] || [];
      for (const [x, y] of parcelRing) addLocal(x, y);

      // Buildable-zone centroids are guaranteed outside buildings.
      for (const poly of siteModel?.buildable_zone?.polygons || []) {
        const ring = poly.rings_local?.[0] || [];
        if (!ring.length) continue;
        let sx = 0, sy = 0;
        for (const [x, y] of ring) { sx += x; sy += y; }
        addLocal(sx / ring.length, sy / ring.length);
      }

      // 4×4 grid inside the parcel, with `addLocal`'s building filter pruning
      // points that land on the existing house.
      const xs = parcelRing.map(p => p[0]);
      const ys = parcelRing.map(p => p[1]);
      if (xs.length && ys.length) {
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const rings = siteModel?.parcel?.rings_local || [];
        for (let ix = 1; ix <= 4; ix++) {
          for (let iy = 1; iy <= 4; iy++) {
            const x = minX + (maxX - minX) * ix / 5;
            const y = minY + (maxY - minY) * iy / 5;
            if (rings.length && pointInRings(x, y, rings)) addLocal(x, y);
          }
        }
      }

      return points.slice(0, 40).map(p => localMetersToLonLat(p.x, p.y));
    }

    // Sample the photorealistic mesh at the given lon/lats and return a
    // height percentile after trimming obvious high outliers (tree canopy /
    // rooftops that read a few metres above nearby grade). `pct` should
    // stay low (0.12–0.35) when you want "ground at the footprint", and
    // closer to 0.5 for a parcel-wide grade.
    //
    // Returns `null` — never `0` — when fewer than 3 valid samples survive.
    async function sampleMeshHeightPercentile(lonLats, pct = 0.5) {
      if (!lonLats?.length) return null;
      const heights = await sampleReal3dHeights(lonLats);
      const valid = heights.filter(Number.isFinite);
      if (valid.length < 3) return null;
      const med = percentile(valid, 0.5);
      // Trim only upward outliers; keep the lower side of the cloud intact
      // so lawns / pads beat sporadic tall hits from the collision mesh.
      const cleaned = valid.filter(h => h <= med + 1.25);
      const pool = cleaned.length >= 3 ? cleaned : valid;
      const lo = percentile(pool, 0.1);
      const hi = percentile(pool, 0.9);
      const tight = pool.filter(h => h >= lo - 0.25 && h <= hi + 0.25);
      const finalPool = tight.length >= 3 ? tight : pool;
      const result = percentile(finalPool, pct);
      debugLog('sampleMeshHeightPercentile', {
        requested: lonLats.length, valid: valid.length,
        pct, median: med, result,
      });
      return Number.isFinite(result) ? result : null;
    }

    // Estimate the parcel floor height from the mesh. Returns null when
    // tiles aren't loaded enough yet — callers retry on tileset events.
    async function sampleParcelFloorHeight() {
      return sampleMeshHeightPercentile(real3dFloorSamplePoints(), 0.32);
    }

    // Sample slightly *inside* the ADU rectangle (inset toward the centroid)
    // plus one point at the placement centre. Probing 1–2 m *outside* the pad
    // often lands on a neighbour roof or tree crown while the photogrammetry
    // mesh still *looks* like low yard — that mismatch reads as the ADU
    // "floating in the sky."
    function aduGroundProbeLonLats() {
      const corners = aduCorners(aduState.x, aduState.y, aduState.rot || 0);
      if (!corners || corners.length !== 4) return [];
      const cx = corners.reduce((s, p) => s + p[0], 0) / corners.length;
      const cy = corners.reduce((s, p) => s + p[1], 0) / corners.length;
      const INSET_M = 0.55;
      const probes = [];
      const pushInset = (x, y) => {
        const dx = cx - x, dy = cy - y;
        const len = Math.hypot(dx, dy) || 1;
        probes.push(localMetersToLonLat(
          x + (dx / len) * INSET_M,
          y + (dy / len) * INSET_M,
        ));
      };
      probes.push(localMetersToLonLat(aduState.x, aduState.y));
      for (let i = 0; i < corners.length; i++) {
        const a = corners[i];
        const b = corners[(i + 1) % corners.length];
        pushInset(a[0], a[1]);
        pushInset((a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
      }
      return probes;
    }

    // Refine the ADU base height from local mesh elevation. Single in-flight
    // probe — overlapping calls are dropped (the next sync will reschedule
    // automatically). The ADU is re-rendered only if the new base differs
    // meaningfully from the current one, to avoid pointless redraws.
    async function refineAduBaseFromMesh() {
      if (real3dAduProbeInFlight) return;
      if (!cesiumViewer || !siteModel || !googleTileset) return;
      real3dAduProbeInFlight = true;
      try {
        const base = await sampleMeshHeightPercentile(aduGroundProbeLonLats(), 0.16);
        if (!Number.isFinite(base)) return;
        if (Math.abs(base - real3dAduBaseHeightM) < 0.05) return;
        real3dAduBaseHeightM = base;
        renderAduAtCurrentBase();
      } finally {
        real3dAduProbeInFlight = false;
      }
    }

    // Render the ADU at its current state + current base height, without
    // kicking off another probe. Used by `refineAduBaseFromMesh` to commit
    // the refined base, and shared with `syncReal3dAdu` to keep the render
    // path in one place.
    function renderAduAtCurrentBase() {
      if (!cesiumViewer || !siteModel) return;
      const baseM = Number.isFinite(real3dAduBaseHeightM)
        ? real3dAduBaseHeightM
        : real3dFloorHeightM;
      // No known ground height yet (tiles still streaming) — defer rendering
      // entirely so the ADU never appears at sea level.
      if (!Number.isFinite(baseM)) return;
      const corners = aduLonLatCorners();
      const closedCorners = [...corners, corners[0]];
      const heightM = Math.max(2, aduState.heightM || 16 * FT_TO_M);
      renderReal3dAdu(corners, closedCorners, heightM, baseM);
      cesiumViewer.scene.requestRender();
    }

    function getGoogleTilesKey() {
      return serverGoogleTilesKey || (els.googleTilesKey.value || '').trim();
    }

    function setReal3dStatus(text, isError = false) {
      els.real3dStatus.textContent = text;
      els.real3dStatus.style.color = isError ? 'var(--err)' : 'var(--text-soft)';
    }

    function resetReal3dForSiteChange() {
      real3dSyncToken += 1;
      real3dAduProbeInFlight = false;
      real3dFloorReady = false;
      real3dFloorSampleInFlight = false;
      real3dFloorHeightM = NaN;
      real3dAduBaseHeightM = NaN;
      if (!cesiumViewer) return;
      clearAduModel();
      const refs = [floorRef, contextFloorRef, contextOutlineRef, parcelFillRef, parcelOutlineRef];
      for (const ref of refs) {
        if (ref.entity) {
          try { cesiumViewer.entities.remove(ref.entity); } catch (_err) {}
          ref.entity = null;
        }
      }
      if (real3dAduFootprintEntity) {
        try { cesiumViewer.entities.remove(real3dAduFootprintEntity); } catch (_err) {}
        real3dAduFootprintEntity = null;
      }
      cesiumViewer.scene.requestRender();
    }

    async function ensureReal3dLoaded() {
      if (!siteModel) {
        setReal3dStatus('Load a site first.', true);
        return;
      }
      if (typeof Cesium === 'undefined') {
        setReal3dStatus('Cesium failed to load. Check network access.', true);
        return;
      }
      const key = getGoogleTilesKey();
      if (!key) {
        setReal3dStatus('Paste a Google Map Tiles API key, then click Load Real 3D.', true);
        return;
      }
      localStorage.setItem('aduMvpGoogleTilesKey', key);
      const tilesetUrl = `https://tile.googleapis.com/v1/3dtiles/root.json?key=${encodeURIComponent(key)}`;
      if (!cesiumViewer) {
        cesiumViewer = new Cesium.Viewer(els.cesiumContainer, {
          animation: false,
          timeline: false,
          baseLayerPicker: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          fullscreenButton: false,
          globe: false,
          requestRenderMode: true,
          showRenderLoopErrors: false,
        });
        cesiumViewer.scene.rethrowRenderErrors = false;
        cesiumViewer.scene.renderError.addEventListener((_scene, err) => {
          handleReal3dRenderError(err);
        });
        if (cesiumViewer.scene.globe) cesiumViewer.scene.globe.show = false;
        cesiumViewer.scene.skyAtmosphere.show = false;
        cesiumViewer.scene.fog.enabled = false;
        const controller = cesiumViewer.scene.screenSpaceCameraController;
        controller.minimumZoomDistance = 1.0;
        controller.maximumZoomDistance = 240;
        applyReal3dLighting();
        installReal3dCameraClamp();
      }
      if (real3dKeyLoaded !== key) {
        if (googleTileset) {
          cesiumViewer.scene.primitives.remove(googleTileset);
          googleTileset = null;
        }
        real3dPreviewLocked = false;
        setReal3dCameraInputs(true);
        els.lockReal3dBtn.textContent = 'HQ Mode';
        setReal3dStatus('Checking Google Map Tiles API key...');
        try {
          const response = await fetch(tilesetUrl);
          const text = await response.text();
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${text.slice(0, 220)}`);
          }
          const rootJson = JSON.parse(text);
          if (!rootJson.asset || !rootJson.root) {
            throw new Error('Root tileset response did not include asset/root fields.');
          }
        } catch (err) {
          setReal3dStatus(`Google 3D Tiles did not load: ${err.message}. Check Map Tiles API, billing, and localhost key restrictions.`, true);
          console.error('Google 3D Tiles root request failed:', err);
          return;
        }

        setReal3dStatus('Google key accepted. Streaming photorealistic 3D tiles...');
        const tileBudgetOptions = {
          showCreditsOnScreen: true,
          maximumScreenSpaceError: 18,
          dynamicScreenSpaceError: true,
          cullRequestsWhileMoving: true,
          cullRequestsWhileMovingMultiplier: 80,
          preloadWhenHidden: false,
          preloadFlightDestinations: false,
          immediatelyLoadDesiredLevelOfDetail: false,
          loadSiblings: false,
          cacheBytes: 96 * 1024 * 1024,
          maximumCacheOverflowBytes: 32 * 1024 * 1024,
        };
        try {
          googleTileset = Cesium.Cesium3DTileset.fromUrl
            ? await Cesium.Cesium3DTileset.fromUrl(tilesetUrl, tileBudgetOptions)
            : new Cesium.Cesium3DTileset({ url: tilesetUrl, ...tileBudgetOptions });
          googleTileset.tileFailed?.addEventListener?.(err => {
            debugWarn('Google 3D tile failed:', err);
            setReal3dStatus(`A Google 3D tile failed to load: ${err.message || 'see console'}`, true);
          });
          // Sampling `sampleHeightMostDetailed` only works once tiles around
          // the parcel are streamed in. Retry floor sampling on each tile-load
          // event (it self-stops once we have a real value). The ADU base is
          // probed once after initial load, then refined only when the user
          // moves the ADU — re-probing on every `allTilesLoaded` would spam
          // the GPU during camera moves and risk render-loop errors.
          googleTileset.initialTilesLoaded?.addEventListener?.(() => {
            refreshParcelFloorHeight();
            refineAduBaseFromMesh();
          });
          googleTileset.allTilesLoaded?.addEventListener?.(() => {
            refreshParcelFloorHeight();
          });
          cesiumViewer.scene.primitives.add(googleTileset);
        } catch (err) {
          setReal3dStatus(`Cesium could not create the Google tileset: ${err.message}`, true);
          console.error('Cesium Google tileset creation failed:', err);
          return;
        }
        real3dKeyLoaded = key;
      }
      syncReal3dScene();
      els.syncReal3dBtn.disabled = false;
      els.focusReal3dBtn.disabled = false;
      els.streetReal3dBtn.disabled = false;
      els.aduWindowReal3dBtn.disabled = false;
      els.lockReal3dBtn.disabled = false;
      setReal3dStatus(`Real 3D preview loaded with ${REAL3D_CONTEXT_PAD_M} m of neighborhood context. Boundary and ADU overlays are synced.`);
    }

    function installReal3dCameraClamp() {
      if (!cesiumViewer || real3dCameraClampInstalled) return;
      real3dCameraClampInstalled = true;
      cesiumViewer.camera.moveEnd.addEventListener(() => {
        if (!siteModel || !cesiumViewer) return;
        const carto = Cesium.Cartographic.fromCartesian(cesiumViewer.camera.position);
        const loc = {
          longitude: Cesium.Math.toDegrees(carto.longitude),
          latitude: Cesium.Math.toDegrees(carto.latitude),
        };
        const center = siteLonLat();
        const tooFar = distanceMeters(center, loc) > REAL3D_CONTEXT_PAD_M + 70;
        const tooHigh = carto.height > 260;
        if (tooFar || tooHigh) {
          flyReal3dToSite(0.45);
          setReal3dStatus('Snapped back to the parcel preview bounds.');
        }
      });
    }

    function setReal3dCameraInputs(enabled) {
      const controller = cesiumViewer?.scene?.screenSpaceCameraController;
      if (!controller) return;
      controller.enableInputs = enabled;
      controller.enableRotate = enabled;
      controller.enableTranslate = enabled;
      controller.enableZoom = enabled;
      controller.enableTilt = enabled;
      controller.enableLook = enabled;
    }

    // Profile-driven tile-quality tuning. Picking a profile by state keeps
    // the actual property writes in one place and makes the trade-off matrix
    // (quality vs. tile traffic vs. GPU pressure) obvious at a glance.
    const REAL3D_TILE_PROFILES = {
      // Default streaming preview — aggressive culling, low GPU load.
      preview:  { maximumScreenSpaceError: 18,  dynamicScreenSpaceError: true,  cullRequestsWhileMoving: true  },
      // HQ lock — load every tile to full detail, suspend movement-based culls.
      hq:       { maximumScreenSpaceError: 2.5, dynamicScreenSpaceError: false, cullRequestsWhileMoving: false },
      // After a GPU render error — keep quality conservative so we don't relapse.
      fallback: { maximumScreenSpaceError: 8,   dynamicScreenSpaceError: true,  cullRequestsWhileMoving: true  },
    };

    function applyReal3dTileQuality() {
      if (!googleTileset) return;
      const profileKey = real3dGpuFallback ? 'fallback' : (real3dPreviewLocked ? 'hq' : 'preview');
      Object.assign(googleTileset, REAL3D_TILE_PROFILES[profileKey], {
        preloadFlightDestinations: false,
        loadSiblings: false,
      });
      cesiumViewer?.scene?.requestRender();
    }

    function toggleReal3dLock() {
      if (!cesiumViewer || !googleTileset) return;
      if (real3dPreviewLocked) {
        real3dPreviewLocked = false;
        setReal3dCameraInputs(true);
        applyReal3dTileQuality();
        els.lockReal3dBtn.textContent = 'HQ Mode';
        setReal3dStatus('Normal 3D quality restored. Camera guardrails still limit tile loading.');
        return;
      }

      real3dPreviewLocked = true;
      setReal3dCameraInputs(true);
      applyReal3dTileQuality();
      flyReal3dToSite(0.25);
      els.lockReal3dBtn.textContent = 'Normal 3D';
      setReal3dStatus(`High-quality mode enabled for the ${REAL3D_CONTEXT_PAD_M} m context. No Cesium freeze/cache path is used.`);
    }

    function formatHour(hour) {
      const h = Number(hour);
      if (h === 0) return '12 AM';
      if (h < 12) return `${h} AM`;
      if (h === 12) return '12 PM';
      return `${h - 12} PM`;
    }

    function applyReal3dLighting() {
      const hour = Number(els.real3dTimeOfDay?.value || 14);
      if (els.real3dTimeLabel) els.real3dTimeLabel.textContent = formatHour(hour);
      const nightOpacity = hour < 6 || hour > 20
        ? 0.54
        : hour < 8
          ? 0.25
          : hour > 18
            ? 0.34
            : 0;
      if (els.real3dLightingOverlay) els.real3dLightingOverlay.style.opacity = String(nightOpacity);
      cesiumViewer?.scene?.requestRender();
    }

    function handleReal3dRenderError(err) {
      if (real3dGpuFallback) return;
      console.warn('Cesium render error; switching Real 3D to stable mode:', err);
      real3dGpuFallback = true;
      real3dPreviewLocked = false;
      setReal3dCameraInputs(true);
      applyReal3dTileQuality();
      if (els.lockReal3dBtn) {
        els.lockReal3dBtn.disabled = false;
        els.lockReal3dBtn.textContent = 'HQ Mode';
      }
      setReal3dStatus('Real 3D switched to stable mode. Advanced material effects are disabled.', true);
      setTimeout(() => {
        if (!cesiumViewer) return;
        cesiumViewer.useDefaultRenderLoop = true;
        syncReal3dParcel();
        syncReal3dAdu();
        cesiumViewer.resize();
        cesiumViewer.scene.requestRender();
      }, 120);
    }

    function syncReal3dScene() {
      if (!cesiumViewer || !siteModel) return;
      syncReal3dContext();
      syncReal3dFloor();
      syncReal3dParcel();
      syncReal3dAdu();
      flyReal3dToSite();
      cesiumViewer.scene.requestRender();
    }

    // ── Shared upsert helpers for ground-anchored polygon + outline entities.
    // Floor / parcel-fill / context-floor are all "flat polygon at some height"
    // with optional outline polyline at the same height — they used to repeat
    // the same create-or-update boilerplate three times.

    function upsertGroundPolygon(ref, name, flatDegrees, height, material) {
      const hierarchy = Cesium.Cartesian3.fromDegreesArray(flatDegrees);
      if (ref.entity) {
        ref.entity.polygon.hierarchy = hierarchy;
        ref.entity.polygon.height = height;
        ref.entity.polygon.material = material;
      } else {
        ref.entity = cesiumViewer.entities.add({
          name,
          polygon: { hierarchy, height, material, outline: false },
        });
      }
    }

    function upsertGroundOutline(ref, name, lonLats, height, color, width, liftM = 0.18) {
      const heights = lonLats.map(() => height);
      const positions = Cesium.Cartesian3.fromDegreesArrayHeights(flatLonLatHeights(lonLats, heights, liftM));
      if (ref.entity) {
        ref.entity.polyline.positions = positions;
      } else {
        ref.entity = cesiumViewer.entities.add({
          name,
          polyline: { positions, width, material: color, clampToGround: false },
        });
      }
    }

    function syncReal3dContext() {
      if (!cesiumViewer || !siteModel) return;
      if (!Number.isFinite(real3dFloorHeightM)) return;
      const ring = real3dContextClipCoords();
      if (!ring.length) return;
      const lonLats = ring.map(([longitude, latitude]) => ({ longitude, latitude }));
      const flat = ring.flatMap(([lon, lat]) => [lon, lat]);
      upsertGroundPolygon(
        contextFloorRef, '15 m context floor', flat,
        real3dFloorHeightM + 0.04,
        Cesium.Color.fromCssColorString('#101916').withAlpha(0.18),
      );
      upsertGroundOutline(
        contextOutlineRef, '15 m context boundary', lonLats,
        real3dFloorHeightM, Cesium.Color.CYAN.withAlpha(0.62), 3, 0.22,
      );
    }

    // Render the floor at the current known height (no-op if unknown) and
    // kick off a sample to fill it in. Safe to call repeatedly: a real
    // sample value short-circuits future work; a failed sample (tiles not
    // loaded) leaves things unset so the next tileset event retries.
    function syncReal3dFloor() {
      if (!cesiumViewer || !siteModel) return;
      if (Number.isFinite(real3dFloorHeightM)) {
        renderReal3dFloor(real3dFloorHeightM);
      }
      refreshParcelFloorHeight();
    }

    async function refreshParcelFloorHeight() {
      if (real3dFloorReady || real3dFloorSampleInFlight) return;
      if (!cesiumViewer || !siteModel || !googleTileset) return;
      real3dFloorSampleInFlight = true;
      // Capture the token so a slow sample from a previous site can't write
      // its terrain elevation into the new site after the user has loaded
      // a new address. `resetReal3dForSiteChange` bumps `real3dSyncToken`.
      const token = real3dSyncToken;
      try {
        const h = await sampleParcelFloorHeight();
        if (token !== real3dSyncToken || !cesiumViewer || !siteModel) return;
        // Tiles not loaded yet — leave height undefined and let the next
        // tileset event call us again. Never write a fallback value.
        if (!Number.isFinite(h)) return;
        real3dFloorHeightM = h;
        // Seed the ADU base only if it hasn't been independently refined.
        // On sloped sites `refineAduBaseFromMesh` may produce a different
        // local value and we must not clobber it from here.
        if (!Number.isFinite(real3dAduBaseHeightM)) {
          real3dAduBaseHeightM = h;
        }
        renderReal3dFloor(h);
        syncReal3dContext();
        syncReal3dParcel();
        syncReal3dAdu();
        real3dFloorReady = true;
      } finally {
        real3dFloorSampleInFlight = false;
      }
    }

    function renderReal3dFloor(heightM) {
      if (!Number.isFinite(heightM)) return;
      const positions = parcelPositionsDegrees();
      if (!positions.length) return;
      upsertGroundPolygon(
        floorRef, 'Parcel floor', positions,
        heightM + 0.08,
        Cesium.Color.fromCssColorString('#263832').withAlpha(0.58),
      );
    }

    function syncReal3dParcel() {
      if (!cesiumViewer || !siteModel) return;
      if (!Number.isFinite(real3dFloorHeightM)) return;
      const positions = parcelPositionsDegrees();
      if (!positions.length) return;
      upsertGroundPolygon(
        parcelFillRef, 'Parcel fill', positions,
        real3dFloorHeightM + 0.12,
        Cesium.Color.YELLOW.withAlpha(0.10),
      );
      const outlineCoords = closedParcelCoords().map(([longitude, latitude]) => ({ longitude, latitude }));
      upsertGroundOutline(
        parcelOutlineRef, 'Parcel boundary', outlineCoords,
        real3dFloorHeightM, Cesium.Color.YELLOW.withAlpha(0.78), 6, 0.18,
      );
      cesiumViewer.scene.requestRender();
    }

    function syncReal3dAdu() {
      if (!cesiumViewer || !siteModel) return;
      renderAduAtCurrentBase();
      // Fire-and-forget: refine the base against local mesh elevation. The
      // probe runs at most one at a time and re-renders if it finds a
      // materially different ground height around the ADU footprint.
      refineAduBaseFromMesh();
    }

    // ── Parametric ADU model in Cesium ─────────────────────────────────────
    // The ADU is composed of 4 walls + a roof (gable/hip/flat) + 1 door +
    // N windows per side. Every piece is a planar polygon entity placed using
    // `perPositionHeight: true`, so we can put quads on vertical wall planes
    // and sloped quads on roof planes directly. All entities are tracked in
    // `aduModelEntities` so a rebuild is just clear + add.

    function clearAduModel() {
      if (!cesiumViewer) return;
      for (const entity of aduModelEntities) {
        try { cesiumViewer.entities.remove(entity); } catch (_err) {}
      }
      aduModelEntities = [];
    }

    function cesiumColor(hex, alpha = 1) {
      try {
        return Cesium.Color.fromCssColorString(hex).withAlpha(alpha);
      } catch (_err) {
        // Invalid hex (e.g. from corrupt localStorage) — fall back to a
        // neutral colour rather than crashing the whole model rebuild.
        return Cesium.Color.fromCssColorString('#cccccc').withAlpha(alpha);
      }
    }

    function localToCart3(x, y, heightM) {
      const lonLat = localMetersToLonLat(x, y);
      const lon = Number(lonLat.longitude);
      const lat = Number(lonLat.latitude);
      const h = Number(heightM);
      if (!Number.isFinite(lon) || !Number.isFinite(lat) || !Number.isFinite(h)) {
        throw new Error(`bad cart3 input: lon=${lon} lat=${lat} h=${h}`);
      }
      return Cesium.Cartesian3.fromDegrees(lon, lat, h);
    }

    // Add one piece of the ADU model. Returns the entity on success, null on
    // failure (and logs once). Callers may continue building remaining pieces
    // — losing a single window is far better than losing the whole house.
    function addAduPolygon({ vertices, color, name, outline = false }) {
      try {
        const positions = vertices.map(v => localToCart3(v.x, v.y, v.h));
        const entity = cesiumViewer.entities.add({
          name,
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            perPositionHeight: true,
            material: color,
            outline,
            outlineColor: outline ? Cesium.Color.BLACK.withAlpha(0.5) : undefined,
          },
        });
        aduModelEntities.push(entity);
        return entity;
      } catch (err) {
        debugWarn(`ADU piece "${name}" failed to build:`, err);
        return null;
      }
    }

    // Vertical rectangular wall from `start` to `end` (in local meters) between
    // heights `baseH` and `topH`. Vertices wind CCW when viewed from outside.
    function buildAduWall(start, end, baseH, topH, color, name) {
      return addAduPolygon({
        name, color,
        vertices: [
          { x: start.x, y: start.y, h: baseH },
          { x: end.x,   y: end.y,   h: baseH },
          { x: end.x,   y: end.y,   h: topH  },
          { x: start.x, y: start.y, h: topH  },
        ],
      });
    }

    // Place a rectangular "sticker" (door or window) on a wall plane.
    // `t0`/`t1` are fractional positions along the wall (0..1); `h0`/`h1` are
    // absolute heights. The rect is shifted outward along the wall normal by
    // `inset` metres to avoid z-fighting with the wall polygon underneath.
    function buildWallSticker(start, end, t0, t1, h0, h1, color, inset, name) {
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const len = Math.hypot(dx, dy);
      if (len <= 0) return null;
      // Outward normal (right-hand of CCW perimeter winding).
      const nx =  dy / len;
      const ny = -dx / len;
      const ax = start.x + dx * t0 + nx * inset;
      const ay = start.y + dy * t0 + ny * inset;
      const bx = start.x + dx * t1 + nx * inset;
      const by = start.y + dy * t1 + ny * inset;
      return addAduPolygon({
        name, color,
        vertices: [
          { x: ax, y: ay, h: h0 },
          { x: bx, y: by, h: h0 },
          { x: bx, y: by, h: h1 },
          { x: ax, y: ay, h: h1 },
        ],
      });
    }

    function buildGableRoof(localCorners, eaveH, peakH, color) {
      const [SW, SE, NE, NW] = localCorners;
      // Ridge runs across the middle of the depth axis in the rotated local
      // frame, derived from the actual wall midpoints so it tracks ADU rotation.
      const ridgeW = { x: (SW.x + NW.x) / 2, y: (SW.y + NW.y) / 2 };
      const ridgeE = { x: (SE.x + NE.x) / 2, y: (SE.y + NE.y) / 2 };
      // North slope
      addAduPolygon({
        name: 'roof N', color,
        vertices: [
          { x: NW.x, y: NW.y, h: eaveH },
          { x: NE.x, y: NE.y, h: eaveH },
          { x: ridgeE.x, y: ridgeE.y, h: peakH },
          { x: ridgeW.x, y: ridgeW.y, h: peakH },
        ],
      });
      // South slope
      addAduPolygon({
        name: 'roof S', color,
        vertices: [
          { x: SW.x, y: SW.y, h: eaveH },
          { x: ridgeW.x, y: ridgeW.y, h: peakH },
          { x: ridgeE.x, y: ridgeE.y, h: peakH },
          { x: SE.x, y: SE.y, h: eaveH },
        ],
      });
      // Triangular gable ends — same colour as the walls (siding extends up).
      const gableColor = cesiumColor(aduStyle.wallColor);
      addAduPolygon({
        name: 'gable E', color: gableColor,
        vertices: [
          { x: SE.x, y: SE.y, h: eaveH },
          { x: NE.x, y: NE.y, h: eaveH },
          { x: ridgeE.x, y: ridgeE.y, h: peakH },
        ],
      });
      addAduPolygon({
        name: 'gable W', color: gableColor,
        vertices: [
          { x: SW.x, y: SW.y, h: eaveH },
          { x: ridgeW.x, y: ridgeW.y, h: peakH },
          { x: NW.x, y: NW.y, h: eaveH },
        ],
      });
    }

    function buildHipRoof(localCorners, eaveH, peakH, color) {
      const [SW, SE, NE, NW] = localCorners;
      const cx = (SW.x + SE.x + NE.x + NW.x) / 4;
      const cy = (SW.y + SE.y + NE.y + NW.y) / 4;
      const slopes = [
        ['S', SW, SE],
        ['E', SE, NE],
        ['N', NE, NW],
        ['W', NW, SW],
      ];
      for (const [face, a, b] of slopes) {
        addAduPolygon({
          name: `roof hip ${face}`, color,
          vertices: [
            { x: a.x, y: a.y, h: eaveH },
            { x: b.x, y: b.y, h: eaveH },
            { x: cx,  y: cy,  h: peakH },
          ],
        });
      }
    }

    function buildFlatRoof(localCorners, eaveH, color) {
      addAduPolygon({
        name: 'roof flat', color,
        vertices: localCorners.map(c => ({ x: c.x, y: c.y, h: eaveH })),
      });
    }

    function buildWindowsOnWall(start, end, baseH, eaveH, count, color, doorT) {
      if (count <= 0) return;
      const wallLen = Math.hypot(end.x - start.x, end.y - start.y);
      if (wallLen < 1.4) return;
      const winW = Math.min(1.0, (wallLen / (count + 1)) * 0.65);
      const winH = Math.min(1.2, eaveH - baseH - 0.8);
      if (winH <= 0.3) return;
      const sill = baseH + Math.min(1.0, (eaveH - baseH) * 0.42);
      const head = sill + winH;
      for (let i = 0; i < count; i++) {
        const t = (i + 1) / (count + 1);
        // Keep windows clear of the door if it shares this wall.
        if (doorT >= 0 && Math.abs(t - doorT) < (winW / wallLen + 0.25)) continue;
        const t0 = t - (winW / 2) / wallLen;
        const t1 = t + (winW / 2) / wallLen;
        buildWallSticker(start, end, t0, t1, sill, head, color, 0.04, 'window');
      }
    }

    function buildDoorOnWall(start, end, baseH, eaveH, color) {
      const wallLen = Math.hypot(end.x - start.x, end.y - start.y);
      if (wallLen < 1.2) return;
      const doorW = 0.95;
      const doorH = Math.min(2.05, eaveH - baseH - 0.2);
      const t0 = 0.5 - (doorW / 2) / wallLen;
      const t1 = 0.5 + (doorW / 2) / wallLen;
      buildWallSticker(start, end, t0, t1, baseH + 0.04, baseH + doorH, color, 0.05, 'door');
    }

    // Walls in CCW outward order: front=NE→NW, left=NW→SW, back=SW→SE, right=SE→NE.
    function aduWallForSide(localCorners, side) {
      const [SW, SE, NE, NW] = localCorners;
      switch (side) {
        case 'front': return [NE, NW];
        case 'back':  return [SW, SE];
        case 'left':  return [NW, SW];
        case 'right': return [SE, NE];
        default: return null;
      }
    }

    function renderReal3dAdu(_corners, closedCorners, heightM, baseHeightM) {
      if (!cesiumViewer) return;

      // ── Pre-flight validation — refuse to start a rebuild from a bad state
      // (e.g. an ADU resize fired before the site finished loading). The old
      // model stays on screen until we have valid inputs again, which is
      // strictly better than tearing it down and showing nothing.
      const inputsValid =
        siteModel &&
        Number.isFinite(aduState.x) && Number.isFinite(aduState.y) &&
        Number.isFinite(aduState.widthM) && Number.isFinite(aduState.depthM) &&
        aduState.widthM > 0 && aduState.depthM > 0 &&
        Number.isFinite(heightM) && heightM > 0 &&
        Number.isFinite(baseHeightM);
      if (!inputsValid) {
        debugWarn('renderReal3dAdu skipped — invalid inputs', {
          aduState, heightM, baseHeightM, hasSite: !!siteModel,
        });
        return;
      }

      // Walk the original local-meter footprint so wall planes line up with
      // rotation perfectly. `aduCorners` returns [SW, SE, NE, NW].
      const localXY = aduCorners(aduState.x, aduState.y, aduState.rot || 0);
      if (!localXY.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y))) {
        debugWarn('renderReal3dAdu skipped — non-finite ADU corners');
        return;
      }
      const localCorners = localXY.map(([x, y]) => ({ x, y }));
      const [SW, SE, NE, NW] = localCorners;

      const baseH = baseHeightM + 0.05;
      const eaveH = baseH + heightM;
      // Roof peak rises with the shorter footprint axis; clamped to keep tiny
      // ADUs from sprouting unrealistic spires.
      const peakRise = aduStyle.roofType === 'flat'
        ? 0
        : Math.min(2.4, Math.max(0.9, Math.min(aduState.widthM, aduState.depthM) * 0.22));
      const peakH = eaveH + peakRise;

      // Build into a staging list. Only commit (i.e. clear the old model and
      // adopt the new entities) once we've actually produced the structural
      // walls — otherwise we'd leave the user staring at empty space.
      const previousEntities = aduModelEntities;
      aduModelEntities = [];
      let success = false;
      try {
        const wallColor = cesiumColor(aduStyle.wallColor);
        buildAduWall(NE, NW, baseH, eaveH, wallColor, 'wall front');
        buildAduWall(NW, SW, baseH, eaveH, wallColor, 'wall left');
        buildAduWall(SW, SE, baseH, eaveH, wallColor, 'wall back');
        buildAduWall(SE, NE, baseH, eaveH, wallColor, 'wall right');

        // Require at least one wall to have actually been added before we
        // throw the old model away.
        if (aduModelEntities.length < 1) {
          throw new Error('no walls produced — aborting rebuild');
        }

        const roofColor = cesiumColor(aduStyle.roofColor);
        if (aduStyle.roofType === 'flat') {
          buildFlatRoof(localCorners, eaveH, roofColor);
        } else if (aduStyle.roofType === 'hip') {
          buildHipRoof(localCorners, eaveH, peakH, roofColor);
        } else {
          buildGableRoof(localCorners, eaveH, peakH, roofColor);
        }

        const doorColor = cesiumColor(aduStyle.doorColor);
        if (aduStyle.doorSide !== 'none') {
          const doorWall = aduWallForSide(localCorners, aduStyle.doorSide);
          if (doorWall) buildDoorOnWall(doorWall[0], doorWall[1], baseH, eaveH, doorColor);
        }

        const winColor = cesiumColor(aduStyle.windowColor);
        const winCount = Math.max(0, Math.min(3, Number(aduStyle.windowsPerSide) || 0));
        for (const side of ['front', 'back', 'left', 'right']) {
          const wall = aduWallForSide(localCorners, side);
          if (!wall) continue;
          const doorT = aduStyle.doorSide === side ? 0.5 : -1;
          buildWindowsOnWall(wall[0], wall[1], baseH, eaveH, winCount, winColor, doorT);
        }
        success = true;
      } catch (err) {
        debugWarn('ADU model rebuild failed; keeping previous model.', err);
      }

      if (success) {
        // Atomic swap: remove the previous model entities now that the new
        // ones are safely on the scene.
        for (const entity of previousEntities) {
          try { cesiumViewer.entities.remove(entity); } catch (_err) {}
        }
      } else {
        // Roll back: remove anything we may have partially built and put the
        // previous model entities back as the active list.
        for (const entity of aduModelEntities) {
          try { cesiumViewer.entities.remove(entity); } catch (_err) {}
        }
        aduModelEntities = previousEntities;
        return;
      }

      // Ground footprint outline (the white selection indicator). Built
      // separately from the model so a model failure still preserves the
      // outline as a hint that the ADU exists.
      try {
        const outlinePositions = Cesium.Cartesian3.fromDegreesArrayHeights(
          flatLonLatHeights(closedCorners, closedCorners.map(() => baseH), 0.18)
        );
        if (!real3dAduFootprintEntity) {
          real3dAduFootprintEntity = cesiumViewer.entities.add({
            name: 'ADU footprint',
            polyline: {
              positions: outlinePositions,
              width: 4,
              material: Cesium.Color.WHITE.withAlpha(0.85),
              clampToGround: false,
            },
          });
        } else {
          real3dAduFootprintEntity.polyline.positions = outlinePositions;
        }
      } catch (err) {
        debugWarn('ADU footprint outline failed to update', err);
      }

      cesiumViewer.scene.requestRender();
    }

    // Validate a {longitude, latitude} pair plus a height — Cesium's camera
    // silently moves to the centre of the earth (or asserts) on NaN, so we
    // reject bad inputs before they ever reach `flyTo`.
    function safeCart3Destination(loc, heightM) {
      const lon = Number(loc?.longitude);
      const lat = Number(loc?.latitude);
      const h = Number(heightM);
      if (!Number.isFinite(lon) || !Number.isFinite(lat) || !Number.isFinite(h)) return null;
      if (Math.abs(lon) > 180 || Math.abs(lat) > 90) return null;
      return Cesium.Cartesian3.fromDegrees(lon, lat, h);
    }

    function flyReal3dToSite(duration = 0.8) {
      if (!cesiumViewer || !siteModel) return;
      const loc = siteLonLat();
      const destination = safeCart3Destination(loc, 82);
      if (!destination) {
        debugWarn('flyReal3dToSite skipped — site lon/lat invalid', loc);
        return;
      }
      cesiumViewer.camera.flyTo({
        destination,
        orientation: {
          heading: THREE.MathUtils.degToRad(20),
          pitch: THREE.MathUtils.degToRad(-66),
          roll: 0,
        },
        duration,
      });
    }

    function localHeadingToCesium(dx, dy) {
      return Math.atan2(dx, dy);
    }

    function parcelLocalBounds() {
      const ring = siteModel?.parcel?.rings_local?.[0] || [];
      if (!ring.length) return null;
      const xs = ring.map(p => p[0]);
      const ys = ring.map(p => p[1]);
      return {
        minX: Math.min(...xs),
        maxX: Math.max(...xs),
        minY: Math.min(...ys),
        maxY: Math.max(...ys),
      };
    }

    function ringCenter(ring) {
      if (!ring?.length) return { x: 0, y: 0 };
      const open = ring.length > 1 && Math.hypot(ring[0][0] - ring[ring.length - 1][0], ring[0][1] - ring[ring.length - 1][1]) < 1e-6
        ? ring.slice(0, -1)
        : ring;
      const sum = open.reduce((acc, p) => ({ x: acc.x + p[0], y: acc.y + p[1] }), { x: 0, y: 0 });
      return { x: sum.x / open.length, y: sum.y / open.length };
    }

    function primaryHouseCenterLocal() {
      const buildings = siteModel?.buildings || [];
      if (!buildings.length) return { x: 0, y: 0 };
      const primary = buildings.reduce((best, b) => (Number(b.area_ft2 || 0) > Number(best.area_ft2 || 0) ? b : best), buildings[0]);
      return ringCenter(primary.rings_local?.[0] || []);
    }

    function flyReal3dStreetLevel() {
      if (!cesiumViewer || !siteModel) return;
      const bounds = parcelLocalBounds();
      if (!bounds) return flyReal3dToSite(0.45);
      const target = primaryHouseCenterLocal();
      const geocodeLocal = lonLatToLocalMeters(
        Number(siteModel.longitude || siteLonLat().longitude),
        Number(siteModel.latitude || siteLonLat().latitude)
      );
      let dirX = geocodeLocal.x - target.x;
      let dirY = geocodeLocal.y - target.y;
      if (Math.hypot(dirX, dirY) < 2) {
        const height = bounds.maxY - bounds.minY;
        const width = bounds.maxX - bounds.minX;
        if (height >= width) {
          dirX = 0;
          dirY = -1;
        } else {
          dirX = -1;
          dirY = 0;
        }
      }
      const len = Math.max(Math.hypot(dirX, dirY), 0.001);
      dirX /= len;
      dirY /= len;
      const parcelRing = siteModel?.parcel?.rings_local?.[0] || [];
      const support = parcelRing.reduce((max, p) => Math.max(max, (p[0] - target.x) * dirX + (p[1] - target.y) * dirY), 10);
      const targetX = target.x;
      const targetY = target.y;
      const cameraX = target.x + dirX * (support + 8);
      const cameraY = target.y + dirY * (support + 8);
      const loc = localMetersToLonLat(cameraX, cameraY);
      const destination = safeCart3Destination(loc, real3dFloorHeightM + 2.1);
      if (!destination) {
        debugWarn('flyReal3dStreetLevel skipped — invalid camera position', loc);
        return flyReal3dToSite(0.45);
      }
      cesiumViewer.camera.flyTo({
        destination,
        orientation: {
          heading: localHeadingToCesium(targetX - cameraX, targetY - cameraY),
          pitch: THREE.MathUtils.degToRad(-7),
          roll: 0,
        },
        duration: 0.65,
      });
    }

    function flyReal3dAduWindow() {
      if (!cesiumViewer || !siteModel) return;
      if (!Number.isFinite(aduState.x) || !Number.isFinite(aduState.y)) {
        debugWarn('flyReal3dAduWindow skipped — ADU position not set');
        return;
      }
      const a = THREE.MathUtils.degToRad(aduState.rot || 0);
      const forwardX = -Math.sin(a);
      const forwardY = Math.cos(a);
      const cameraX = aduState.x + forwardX * (aduState.depthM * 0.5 + 0.5);
      const cameraY = aduState.y + forwardY * (aduState.depthM * 0.5 + 0.5);
      const loc = localMetersToLonLat(cameraX, cameraY);
      const destination = safeCart3Destination(loc, real3dAduBaseHeightM + 1.65);
      if (!destination) {
        debugWarn('flyReal3dAduWindow skipped — invalid camera position', loc);
        return flyReal3dToSite(0.45);
      }
      cesiumViewer.camera.flyTo({
        destination,
        orientation: {
          heading: localHeadingToCesium(forwardX, forwardY),
          pitch: THREE.MathUtils.degToRad(-3),
          roll: 0,
        },
        duration: 0.65,
      });
    }

    function showTab(name) {
      const showModel  = name === 'model';
      const showReal3d = name === 'real3d';
      // Financing and checklist panels are now wizard steps, not tabs in stepModel.
      els.checklistPanel.hidden = true;
      els.modelPanel.hidden  = !showModel;
      els.real3dPanel.hidden = !showReal3d;
      els.modelTab.classList.toggle('active', showModel);
      els.real3dTab.classList.toggle('active', showReal3d);
      els.checklistTab.classList.toggle('active', false);
      els.financingTab.classList.toggle('active', false);
      if (showModel) {
        requestAnimationFrame(() => {
          resize();
          if (siteModel) frameSite(false);
          controls.update();
        });
      } else if (showReal3d) {
        requestAnimationFrame(() => {
          if (cesiumViewer) {
            cesiumViewer.resize();
            syncReal3dScene();
          }
        });
      }
    }

    function fmtMoney(v) {
      if (v == null || Number.isNaN(Number(v))) return 'N/A';
      return '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
    }
    function fmtPct(v, digits = 1) {
      if (v == null || Number.isNaN(Number(v))) return 'N/A';
      return Number(v).toFixed(digits) + '%';
    }
    function metricBlock(value, label) {
      return `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
    }

    // Estimate ADU rent client-side so it updates as the user resizes the ADU.
    // Mirrors backend property_data.estimate_adu_rent: rent/sqft → bedroom bucket → zip average.
    function estimateAduRentClient(aduSqft, zc) {
      if (!zc || !aduSqft || aduSqft <= 0) return { monthly_rent: null, method: 'no_data', confidence: 'low' };
      if (zc.rent_per_sqft) {
        return {
          monthly_rent: Math.round(zc.rent_per_sqft * aduSqft),
          rent_per_sqft: zc.rent_per_sqft,
          method: 'rent_per_sqft',
          confidence: (zc.rental_listings || 0) >= 5 ? 'medium' : 'low',
        };
      }
      const likelyBeds = aduSqft < 500 ? 0 : (aduSqft < 750 ? 1 : 2);
      const breakdown = zc.rent_breakdown || [];
      if (breakdown.length) {
        const match = breakdown.slice().sort((a, b) =>
          Math.abs((a.bedrooms || 0) - likelyBeds) - Math.abs((b.bedrooms || 0) - likelyBeds)
        )[0];
        return {
          monthly_rent: match.avg_rent,
          method: `bedroom_bucket_${match.bedrooms}br`,
          confidence: 'low',
        };
      }
      if (zc.average_rent) {
        return { monthly_rent: Math.round(zc.average_rent), method: 'zip_average', confidence: 'low' };
      }
      return { monthly_rent: null, method: 'no_data', confidence: 'low' };
    }

    // Human-friendly labels for the rent-estimation methods the backend (or
    // the client-side fallback) can return. Avoids leaking internal strings
    // like `bedroom_bucket_0br` directly into the UI.
    function rentMethodLabel(method) {
      if (!method) return 'method unavailable';
      if (method === 'rent_per_sqft') return 'rent per sqft from local rentals';
      if (method === 'zip_average') return 'zip-wide average rent';
      if (method === 'no_data') return 'no comparable rentals found';
      if (method === 'no_size') return 'ADU size missing';
      const m = method.match(/^bedroom_bucket_(\d+)br$/);
      if (m) {
        const beds = Number(m[1]);
        return `${beds === 0 ? 'studio' : `${beds}-bedroom`} rental comps`;
      }
      return method.replace(/_/g, ' ');
    }

    function renderFinancing() {
      const aduSqft = (aduState.widthM * aduState.depthM) * M2_TO_FT2;
      const zc = zipContext || {};
      const rentEst = estimateAduRentClient(aduSqft, zc);

      els.rentCards.innerHTML = [
        metricBlock(formatNumber(aduSqft), 'ADU sqft'),
        metricBlock(fmtMoney(rentEst.monthly_rent), 'est. rent / mo'),
        metricBlock(rentEst.monthly_rent ? fmtMoney(rentEst.monthly_rent * 12) : 'N/A', 'est. rent / yr'),
      ].join('');

      const basis = zc.rental_listings
        ? `Based on ${zc.rental_listings} rental listing(s) in zip ${zc.zip_code || 'N/A'} (HomeHarvest / Realtor.com)`
        : (zc.zip_code ? `No rental listings found in zip ${zc.zip_code} via HomeHarvest` : 'Load a site to fetch rent comps');
      const psf = zc.rent_per_sqft ? ` · avg $${zc.rent_per_sqft}/sqft` : '';
      els.financingNote.textContent =
        `${basis}${psf}. Estimate uses ${rentMethodLabel(rentEst.method)} (${rentEst.confidence} confidence).`;
    }

    // ── URL state (shareable links) ───────────────────────────────────────────
    function pushUrlState() {
      const params = new URLSearchParams();
      const addr = els.address.value.trim();
      if (addr) params.set('a', addr);
      if (aduTypeVal !== 'detached') params.set('type', aduTypeVal);
      const w = String(els.aduWidth.value);
      const d = String(els.aduDepth.value);
      const h = String(els.height.value);
      if (w && w !== '30') params.set('w', w);
      if (d && d !== '40') params.set('d', d);
      if (h && h !== '16') params.set('h', h);
      const qs = params.toString();
      history.replaceState(null, '', qs ? '?' + qs : location.pathname);
    }

    let _urlPushTimer = null;
    function schedulePushUrlState() {
      clearTimeout(_urlPushTimer);
      _urlPushTimer = setTimeout(pushUrlState, 400);
    }

    function readUrlState() {
      const params = new URLSearchParams(location.search);
      const addr = params.get('a');
      const type = params.get('type');
      const w = params.get('w');
      const d = params.get('d');
      const h = params.get('h');
      if (type) applyAduType(type);
      if (w) els.aduWidth.value = w;
      if (d) els.aduDepth.value = d;
      if (h) {
        els.height.value = h;
        const lbl = document.getElementById('heightLabel');
        const val = document.getElementById('heightVal');
        if (lbl) lbl.textContent = h;
        if (val) val.textContent = h + ' ft';
      }
      if (addr) {
        els.address.value = addr;
        dismissLandingOverlay();
        const chip = document.getElementById('addressChipRow');
        const chipText = document.getElementById('addressChipText');
        if (chip) chip.hidden = false;
        if (chipText) chipText.textContent = addr;
        navigateWizard(1);
        loadSite();
      }
    }

    els.financingTab?.addEventListener('click', () => navigateWizard(6));

    els.form.addEventListener('submit', e => {
      e.preventDefault();
      dismissLandingOverlay();
      loadSite();
    });

    function dismissLandingOverlay() {
      const el = document.getElementById('landingOverlay');
      if (el && !el.classList.contains('is-dismissed')) {
        el.classList.add('is-dismissed');
        el.setAttribute('aria-hidden', 'true');
      }
    }

    function hideLandingOverlayForTool() {
      const el = document.getElementById('landingOverlay');
      if (!el) return;
      el.classList.add('is-dismissed');
      el.setAttribute('aria-hidden', 'true');
    }

    function showLandingOverlayFromTool() {
      const el = document.getElementById('landingOverlay');
      if (!el) return;
      el.classList.remove('is-dismissed');
      el.removeAttribute('aria-hidden');
    }

    function startFromLanding() {
      const landingInput = document.getElementById('landingAddress');
      if (!landingInput) return;
      const v = landingInput.value.trim();
      if (!v) {
        landingInput.focus();
        return;
      }
      els.address.value = v;
      dismissLandingOverlay();
      navigateWizard(1);
      loadSite();
    }

    document.getElementById('landingStartBtn')?.addEventListener('click', startFromLanding);
    document.getElementById('landingAddress')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        startFromLanding();
      }
    });
    els.modelTab.addEventListener('click', () => showTab('model'));
    els.real3dTab.addEventListener('click', () => showTab('real3d'));


    // Add Plans listeners
    els.addPlansBtn?.addEventListener('click', openAddPlans);
    els.addPlansCloseBtn?.addEventListener('click', closeAddPlans);
    els.addPlanForm?.addEventListener('submit', submitAddPlan);
    els.addPlansCityFilter?.addEventListener('click', (e) => {
      const btn = e.target.closest('.seg-btn');
      if (!btn) return;
      els.addPlansCityFilter.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b === btn));
      loadManualPlans(btn.dataset.city || '');
    });
    els.loadReal3dBtn.addEventListener('click', ensureReal3dLoaded);
    els.syncReal3dBtn.addEventListener('click', syncReal3dScene);
    els.focusReal3dBtn.addEventListener('click', () => flyReal3dToSite(0.45));
    els.streetReal3dBtn.addEventListener('click', flyReal3dStreetLevel);
    els.aduWindowReal3dBtn.addEventListener('click', flyReal3dAduWindow);
    els.lockReal3dBtn.addEventListener('click', toggleReal3dLock);
    els.real3dTimeOfDay.addEventListener('input', applyReal3dLighting);
    els.googleTilesKey.addEventListener('change', () => {
      localStorage.setItem('aduMvpGoogleTilesKey', getGoogleTilesKey());
    });

    // ── ADU style controls ────────────────────────────────────────────────
    function initAduStyleControls() {
      els.aduWallColor.value   = aduStyle.wallColor;
      els.aduRoofColor.value   = aduStyle.roofColor;
      els.aduDoorColor.value   = aduStyle.doorColor;
      els.aduWindowColor.value = aduStyle.windowColor;
      els.aduRoofType.value    = aduStyle.roofType;
      els.aduDoorSide.value    = aduStyle.doorSide;
      els.aduWindowCount.value = String(aduStyle.windowsPerSide);
      els.aduWindowCountLabel.textContent = String(aduStyle.windowsPerSide);
    }

    function persistAduStyle() {
      try { localStorage.setItem('aduMvpAduStyle', JSON.stringify(aduStyle)); } catch (_err) {}
    }

    function onAduStyleChanged() {
      persistAduStyle();
      // Only rebuild if the Real 3D scene is actually up — otherwise the next
      // syncReal3dAdu() call will pick up the new style automatically.
      if (cesiumViewer && siteModel) syncReal3dAdu();
    }

    const styleColorBindings = [
      [els.aduWallColor,   'wallColor'],
      [els.aduRoofColor,   'roofColor'],
      [els.aduDoorColor,   'doorColor'],
      [els.aduWindowColor, 'windowColor'],
    ];
    for (const [input, key] of styleColorBindings) {
      input.addEventListener('input', () => {
        aduStyle[key] = input.value;
        onAduStyleChanged();
      });
    }
    els.aduRoofType.addEventListener('change', () => {
      aduStyle.roofType = els.aduRoofType.value;
      onAduStyleChanged();
    });
    els.aduDoorSide.addEventListener('change', () => {
      aduStyle.doorSide = els.aduDoorSide.value;
      onAduStyleChanged();
    });
    els.aduWindowCount.addEventListener('input', () => {
      const n = Math.max(0, Math.min(3, Number(els.aduWindowCount.value) || 0));
      aduStyle.windowsPerSide = n;
      els.aduWindowCountLabel.textContent = String(n);
      onAduStyleChanged();
    });
    initAduStyleControls();
    els.floorMode.addEventListener('change', () => {
      if (!siteModel) return;
      applyFloorMode(els.floorMode.value);
    });
    els.snapBtn.addEventListener('click', () => {
      // Re-run the same type-aware snap logic used on initial site load so
      // attached / JADU types land in the right place, not the generic
      // top-scored detached placement.
      if (!siteModel) return;
      if (aduTypeVal === 'attached') {
        snapInitialToWall();
      } else if (aduTypeVal === 'jadu') {
        snapInitialToHouseCenter();
      } else {
        const p = siteModel.adu?.placements?.[0];
        if (!p) return;
        aduState.x = p.center_local[0];
        aduState.y = p.center_local[1];
        aduState.rot = p.rotation_deg;
      }
      els.rotation.value = String(Math.round(aduState.rot));
      rebuildAdu();
    });
    els.rotation.addEventListener('input', () => {
      aduState.rot = Number(els.rotation.value);
      rebuildAdu();
    });
    els.aduWidth.addEventListener('input', updateAduSizeFromInputs);
    els.aduDepth.addEventListener('input', updateAduSizeFromInputs);
    els.height.addEventListener('input', () => {
      aduState.heightM = Number(els.height.value) * FT_TO_M;
      rebuildAdu();
      renderSidebarLimits(aduTypeVal);
      _markReqsStale();
    });

    // ── Floors toggle ─────────────────────────────────────────────────────────
    let currentFloors = 1;

    function _maxHeightForType(type, floors) {
      // Use backend constraints when stories match the cached fetch
      const c = backendConstraintsFor(type, floors);
      if (c?.max_height_ft != null) return c.max_height_ft;
      if (standardsVal === 'state') {
        if (type === 'attached') return 25;
        if (type === 'jadu') return 25;
        return 18;
      }
      // Fallback: city-standard approximation
      if (type === 'attached') return 25;
      if (type === 'jadu')     return 25;
      return floors === 2 ? 25 : 18;
    }

    function _updateHeightSlider(type, floors) {
      const slider = els.sidebarHeight;
      const mainSlider = els.height;
      const hint = document.getElementById('sidebarHeightHint');
      if (!slider) return;
      const max = _maxHeightForType(type, floors);
      slider.max = String(max);
      if (mainSlider) mainSlider.max = String(max);
      // Clamp current value
      const cur = Number(slider.value);
      if (cur > max) {
        slider.value = String(max);
        if (mainSlider) mainSlider.value = String(max);
        if (els.sidebarHeightLabel) els.sidebarHeightLabel.textContent = String(max);
        if (els.sidebarHeightVal)   els.sidebarHeightVal.textContent   = max + ' ft';
        aduState.heightM = max * FT_TO_M;
        rebuildAdu();
      }
      if (hint) {
        const label = floors === 1 ? '1-story max' : '2-story max';
        hint.textContent = `${label}: ${max} ft`;
      }
    }

    document.getElementById('floorsToggle')?.querySelectorAll('.seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.getElementById('floorsToggle').querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFloors = Number(btn.dataset.floors);
        _updateHeightSlider(aduTypeVal, currentFloors);
        renderSidebarLimits(aduTypeVal);
        _refreshConstraints();
      });
    });

    // Background re-fetch: updates siteModel + renders limits/picker WITHOUT navigating.
    // Used by the standards toggle and floors toggle so they don't hijack the wizard step.
    async function _refreshConstraints() {
      if (!siteModel || !els.address.value.trim()) return;
      const w = Number(els.sidebarWidth?.value || els.aduWidth.value) || 30;
      const d = Number(els.sidebarDepth?.value || els.aduDepth.value) || 40;
      const h = currentAduHeightFt();
      try {
        const data = await postJson('/api/site', {
          city: getSelectedCity(),
          address: els.address.value.trim(),
          include_checklist: true,
          standards: standardsVal,
          adu_type: aduTypeVal,
          adu_stories: currentFloors,
          adu_width_ft: w,
          adu_depth_ft: d,
          adu_height_ft: h,
          front_edge_index: selectedFrontEdgeIdx,
        });
        if (data.site_model) siteModel = data.site_model;
        if (data.property_stats) propertyStats = data.property_stats;
        const items = data.checklist?.items || [];
        _allChecklistItems = items;
        _checklistDims = { w, d, h, floors: currentFloors, type: aduTypeVal, standards: standardsVal };
        _updateHeightSlider(aduTypeVal, currentFloors);
        // Rebuild the 3D scene so the buildable zone reflects the new setbacks
        // while preserving the dimensions used for this rules fetch.
        buildScene({ preserveDimensions: true });
        renderSidebarLimits(aduTypeVal);
        renderSidebarSizeStat();
        renderAduPicker(data.property_stats);
        renderSizeCard(aduTypeVal, data.property_stats);
        // Refresh checklist if that step is currently visible
        const checklistStep = document.getElementById('stepChecklist');
        if (checklistStep && !checklistStep.hidden) renderFullChecklist(_allChecklistItems);
      } catch (err) {
        _markReqsStale();
        setStatus(err.message || 'Rules refresh failed — requirements may be stale.', 'err');
      }
    }

    function applyStandards(val) {
      standardsVal = val;
      document.querySelectorAll('[data-standards]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.standards === val);
      });
      applyAduType(aduTypeVal);
      const hint = document.getElementById('standardsHintStep2');
      if (hint) {
        hint.textContent = val === 'city'
          ? 'City standards: up to 1,000–1,200 sf depending on lot size'
          : 'State standards: max 800 sf, 4 ft side/rear setbacks, no siting restriction';
      }
      _refreshConstraints();
    }
    document.querySelectorAll('[data-standards]').forEach(btn => {
      btn.addEventListener('click', () => applyStandards(btn.dataset.standards));
    });

    // Sidebar dimension inputs — sync to the existing hidden step-3 inputs so all
    // existing handlers (updateAduSizeFromInputs, rebuildAdu, etc.) continue to fire.
    function _markReqsStale() {
      const btn = document.getElementById('refreshReqBtn');
      if (btn) btn.hidden = false;
    }
    els.sidebarWidth?.addEventListener('input', e => {
      els.aduWidth.value = e.target.value;
      updateAduSizeFromInputs();
      renderSidebarSizeStat();
      renderSidebarLimits(aduTypeVal);
      _markReqsStale();
    });
    els.sidebarDepth?.addEventListener('input', e => {
      els.aduDepth.value = e.target.value;
      updateAduSizeFromInputs();
      renderSidebarSizeStat();
      renderSidebarLimits(aduTypeVal);
      _markReqsStale();
    });
    els.sidebarHeight?.addEventListener('input', e => {
      const v = e.target.value;
      els.height.value = v;
      if (els.sidebarHeightLabel) els.sidebarHeightLabel.textContent = v;
      if (els.sidebarHeightVal)   els.sidebarHeightVal.textContent   = v + ' ft';
      if (els.heightLabel)        els.heightLabel.textContent        = v;
      if (els.heightVal)          els.heightVal.textContent          = v + ' ft';
      aduState.heightM = Number(v) * FT_TO_M;
      rebuildAdu();
      renderSidebarLimits(aduTypeVal);
      _markReqsStale();
    });
    document.getElementById('refreshReqBtn')?.addEventListener('click', () => {
      if (aduTypeVal && siteModel) selectAduType(aduTypeVal);
    });
    els.houseRot.addEventListener('input', () => {
      houseState.rot = Number(els.houseRot.value);
      markHouseDirty();
    });
    els.houseResetBtn.addEventListener('click', () => {
      // Smooth tween back to origin instead of snapping.
      const start = { x: houseState.x, y: houseState.y, rot: houseState.rot };
      const t0 = performance.now();
      const dur = 480;
      function step() {
        const t = Math.min(1, (performance.now() - t0) / dur);
        // ease-in-out cubic
        const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        houseState.x = start.x * (1 - e);
        houseState.y = start.y * (1 - e);
        houseState.rot = start.rot * (1 - e);
        els.houseRot.value = String(Math.round(houseState.rot));
        markHouseDirty();
        if (t < 1) requestAnimationFrame(step);
      }
      step();
    });
    els.showHousesBtn.addEventListener('click', () => {
      if (!houseGroup) return;
      houseGroup.children.forEach(child => { child.visible = true; });
      hiddenHouseCount = 0;
      updateShowHousesLabel();
      setStatus('Hidden houses restored', 'ok');
    });

    function updateShowHousesLabel() {
      const btn = els.showHousesBtn;
      if (!btn) return;
      btn.disabled = hiddenHouseCount === 0;
      btn.textContent = hiddenHouseCount > 0
        ? `Show ${hiddenHouseCount} hidden house${hiddenHouseCount === 1 ? '' : 's'}`
        : 'Show hidden houses';
    }
    els.hideStructureBtn.addEventListener('click', () => setHideStructureMode(!hideStructureMode));
    els.houseEditBtn.addEventListener('click', () => setHouseEditMode(!houseEditMode));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && houseEditMode) setHouseEditMode(false);
      if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault();
        toggleSidebar();
      }
    });

    // ── Sidebar collapse ────────────────────────────────────────────────────
    function setSidebar(collapsed) {
      els.app.classList.toggle('sidebar-collapsed', collapsed);
      localStorage.setItem('aduMvpSidebar', collapsed ? '1' : '0');
      // Repaint the viewers after the grid-template animation completes.
      setTimeout(() => {
        resize();
        if (cesiumViewer) cesiumViewer.resize();
      }, 280);
    }
    function toggleSidebar() {
      setSidebar(!els.app.classList.contains('sidebar-collapsed'));
    }
    els.sidebarToggle.addEventListener('click', toggleSidebar);
    if (localStorage.getItem('aduMvpSidebar') === '1') setSidebar(true);

    // ── ADU type selector ───────────────────────────────────────────────────
    const ADU_TYPE_HINTS = {
      detached: 'Standalone structure in the rear yard. Must be behind the main home or \u226545\u00a0ft from the front property line. Front-yard placement not allowed.',
      attached: 'Shares a wall with the primary home. No additional siting restriction beyond applicable setbacks; front door must be on a different facade.',
      jadu: 'Junior ADU within the existing primary footprint (incl. attached garage). Max 500\u00a0sf. Owner-occupancy required unless it has independent sanitation facilities.',
    };
    function applyAduType(val) {
      aduTypeVal = val;
      els.aduTypeSeg.querySelectorAll('.seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.val === val);
      });
      els.aduTypeHint.textContent = (
        val === 'detached' && standardsVal === 'state'
          ? 'Standalone structure. State Standards allow no local siting restriction; side/rear setbacks are 4 ft and front setback follows the zoning district unless the 800 sf exception applies.'
          : ADU_TYPE_HINTS[val] || ''
      );
      // JADU max size cap
      if (val === 'jadu') {
        els.aduWidth.max = '22';
        els.aduDepth.max = '23';
        if (Number(els.aduWidth.value) > 22) els.aduWidth.value = '22';
        if (Number(els.aduDepth.value) > 23) els.aduDepth.value = '23';
      } else {
        els.aduWidth.max = '40';
        els.aduDepth.max = '50';
      }
    }
    els.aduTypeSeg.addEventListener('click', (e) => {
      const btn = e.target.closest('.seg-btn[data-val]');
      if (!btn) return;
      // If a site is loaded, delegate to selectAduType so Phase 2 updates.
      if (siteModel) {
        selectAduType(btn.dataset.val);
      } else {
        applyAduType(btn.dataset.val);
      }
    });

    // ── Checklist ADU type picker (delegated, rendered dynamically) ──────────
    els.aduTypeCards?.addEventListener('click', (e) => {
      const card = e.target.closest('.adu-card[data-type]');
      if (!card || !siteModel) return;
      // Update aria-checked on all cards
      els.aduTypeCards.querySelectorAll('.adu-card[role="radio"]').forEach(c => {
        c.setAttribute('aria-checked', c === card ? 'true' : 'false');
      });
      selectAduType(card.dataset.type);
    });

    applyAduType(aduTypeVal);

    // ── Unit toggle (ft / m) ────────────────────────────────────────────────
    function applyUnit(unit) {
      displayUnit = unit;
      localStorage.setItem('aduMvpUnit', unit);
      els.unitToggle.querySelectorAll('button').forEach(b => {
        b.classList.toggle('active', b.dataset.unit === unit);
      });
      if (siteModel) {
        renderMetrics();
        updateHud();
      }
    }
    els.unitToggle.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-unit]');
      if (btn) applyUnit(btn.dataset.unit);
    });
    applyUnit(displayUnit);

    // ── Debug pane toggle ───────────────────────────────────────────────────
    els.debugToggle.addEventListener('click', () => {
      const hidden = els.debug.hasAttribute('hidden');
      if (hidden) {
        els.debug.removeAttribute('hidden');
        els.debugToggle.textContent = 'Hide';
      } else {
        els.debug.setAttribute('hidden', '');
        els.debugToggle.textContent = 'Show';
      }
    });

    document.getElementById('landingAddress')?.focus();

    // ── Wizard navigation ────────────────────────────────────────────────────
    const WIZARD_STEP_IDS = ['stepCompliance', 'stepAduType', 'stepConfigure', 'stepModel', 'stepChecklist', 'stepFinancing'];

    const _CHECK_SVG = `<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="2 6 5 9 10 3"/></svg>`;
    // Visual step labels — sd3/configure skipped; sd4=model (3), sd5=checklist (4), sd6=financing (5)
    const _VISUAL_STEP_NUM = { 1: '1', 2: '2', 4: '3', 5: '4', 6: '5' };

    function navigateWizard(step) {
      // Determine direction for enter animation before hiding steps
      const prevIdx = WIZARD_STEP_IDS.findIndex(id => {
        const el = document.getElementById(id);
        return el && !el.hidden;
      });
      const goingForward = prevIdx < 0 || step > prevIdx + 1;
      const enterClass = goingForward ? 'is-enter-forward' : 'is-enter-backward';

      WIZARD_STEP_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.hidden = true;
      });
      const targetId = WIZARD_STEP_IDS[step - 1];
      if (targetId) {
        const el = document.getElementById(targetId);
        if (el) {
          el.hidden = false;
          // Model step (4) has its own stepFade animation — skip directional class
          if (step !== 4) {
            el.classList.remove('is-enter-forward', 'is-enter-backward');
            el.classList.add(enterClass);
            el.addEventListener('animationend', () => el.classList.remove(enterClass), { once: true });
          }
          window.scrollTo(0, 0);
        }
      }
      // Show step indicator
      const indicator = document.getElementById('stepIndicator');
      if (indicator) indicator.hidden = false;
      // Update dots and parent step-item classes
      for (let i = 1; i <= 6; i++) {
        const dot  = document.getElementById('sd' + i);
        const line = document.getElementById('sl' + i);
        if (dot) {
          const isDone   = i < step;
          const isActive = i === step;
          dot.classList.toggle('active', isActive);
          dot.classList.toggle('done', isDone);
          dot.innerHTML = isDone ? _CHECK_SVG : (_VISUAL_STEP_NUM[i] ?? String(i));
          const item = dot.closest('.step-item');
          if (item) {
            item.classList.toggle('active', isActive);
            item.classList.toggle('done', isDone);
          }
        }
        if (line) line.classList.toggle('done', i < step);
      }
      // Back button: show on steps 2+
      const backBtn = document.getElementById('headerBackBtn');
      if (backBtn) backBtn.classList.toggle('visible', step > 1);
      // Model step: go to model tab
      if (step === 4) showTab('model');
      // Financing step: ensure panel is visible and data is fresh
      if (step === 6) {
        const fp = document.getElementById('financingPanel');
        if (fp) fp.hidden = false;
        renderFinancing();
      }
    }

    // ── Wizard button wiring ─────────────────────────────────────────────────

    // Front edge picker skip
    document.getElementById('frontEdgeSkipBtn')?.addEventListener('click', () => {
      document.getElementById('frontEdgePicker').hidden = true;
    });

    // Continue → Step 2 (ADU type)
    document.getElementById('continueToAduBtn')?.addEventListener('click', () => {
      navigateWizard(2);
    });

    // Launch model → Step 4
    document.getElementById('launchModelBtn')?.addEventListener('click', () => {
      navigateWizard(4);
    });

    // Full Compliance Review → Step 5 (checklist), auto-refresh if dims changed
    document.getElementById('continueToChecklistBtn')?.addEventListener('click', async () => {
      const typeLabels = { detached: 'Detached ADU', attached: 'Attached ADU', jadu: 'JADU' };
      const titleEl = document.getElementById('checklistStepTitle');
      if (titleEl) titleEl.textContent = `${typeLabels[aduTypeVal] || 'ADU'} Compliance Checklist`;

      const curW = Number(els.sidebarWidth?.value || els.aduWidth.value) || 30;
      const curD = Number(els.sidebarDepth?.value || els.aduDepth.value) || 40;
      const curH = currentAduHeightFt();
      const dimsChanged = (
        curW !== _checklistDims.w ||
        curD !== _checklistDims.d ||
        curH !== _checklistDims.h ||
        currentFloors !== _checklistDims.floors ||
        aduTypeVal !== _checklistDims.type ||
        standardsVal !== _checklistDims.standards
      );

      if (dimsChanged && els.address.value.trim()) {
        // Navigate first so the loading state is visible
        const container = document.getElementById('fullChecklist');
        const tabBar = document.getElementById('checklistTabBar');
        if (container) container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-soft);font-size:13px;">Recalculating for new dimensions…</div>';
        if (tabBar) tabBar.innerHTML = '';
        document.getElementById('fullChecklistSummary')?.setAttribute('hidden', '');
        navigateWizard(5);
        try {
          const data = await postJson('/api/site', {
            city: getSelectedCity(),
            address: els.address.value.trim(),
            include_checklist: true,
            standards: standardsVal,
            adu_type: aduTypeVal,
            adu_stories: currentFloors,
            adu_width_ft: curW,
            adu_depth_ft: curD,
            adu_height_ft: curH,
            front_edge_index: selectedFrontEdgeIdx,
          });
          _allChecklistItems = data.checklist?.items || [];
          _checklistDims = {
            w: curW,
            d: curD,
            h: curH,
            floors: currentFloors,
            type: aduTypeVal,
            standards: standardsVal,
          };
          if (data.site_model) {
            siteModel = data.site_model;
            propertyStats = data.property_stats || propertyStats;
            zipContext = data.zip_context || zipContext;
            financing = data.financing || financing;
            _updateHeightSlider(aduTypeVal, currentFloors);
            buildScene({ preserveDimensions: true });
            renderSidebarLimits(aduTypeVal);
            renderSidebarSizeStat();
            renderSizeCard(aduTypeVal, propertyStats);
          }
        } catch (err) {
          _allChecklistItems = [{
            part: 0,
            number: null,
            status: 'unavailable',
            question: 'Checklist refresh failed',
            detail: err.message || 'Could not recalculate requirements for the current ADU inputs.',
            source: 'POST /api/site',
          }];
          setStatus('Checklist refresh failed — current requirements are unavailable.', 'err');
        }
      } else {
        navigateWizard(5);
      }
      renderFullChecklist(_allChecklistItems);
    });

    // View Rental Estimate → Step 6 (financing)
    document.getElementById('continueToFinancingBtn')?.addEventListener('click', () => {
      navigateWizard(6);
    });

    // Header back button — skip configure (step 3) going back from model (4); checklist (5) → model (4)
    document.getElementById('headerBackBtn')?.addEventListener('click', () => {
      const currentStep = WIZARD_STEP_IDS.findIndex(id => {
        const el = document.getElementById(id);
        return el && !el.hidden;
      }) + 1;
      if (currentStep > 1) {
        const prevStep = currentStep === 4 ? 2 : currentStep - 1;
        navigateWizard(prevStep);
      }
    });

    // Change address → return to landing
    document.getElementById('changeAddressBtn')?.addEventListener('click', () => {
      const overlay = document.getElementById('landingOverlay');
      if (overlay) { overlay.classList.remove('is-dismissed'); overlay.removeAttribute('aria-hidden'); }
      WIZARD_STEP_IDS.forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
      document.getElementById('stepIndicator').hidden = true;
      document.getElementById('headerBackBtn')?.classList.remove('visible');
      document.getElementById('address')?.focus();
    });

    // Home button (brand logo) — returns to the landing page from any wizard step
    document.getElementById('homeBtn')?.addEventListener('click', () => {
      const overlay = document.getElementById('landingOverlay');
      if (!overlay) return;
      if (!overlay.classList.contains('is-dismissed')) {
        // Already on landing — focus the search input
        document.getElementById('address')?.focus();
        return;
      }
      overlay.classList.remove('is-dismissed');
      overlay.removeAttribute('aria-hidden');
      overlay.classList.add('is-showing');
      overlay.addEventListener('animationend', () => overlay.classList.remove('is-showing'), { once: true });
      WIZARD_STEP_IDS.forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
      document.getElementById('stepIndicator').hidden = true;
      document.getElementById('headerBackBtn')?.classList.remove('visible');
      document.getElementById('address')?.focus();
    });

    // Sidebar collapse toggle
    document.getElementById('sidebarCollapseBtn')?.addEventListener('click', () => {
      document.querySelector('.viewer-sidebar')?.classList.toggle('is-collapsed');
    });

    // Height slider → live label update
    els.height.addEventListener('input', () => {
      const v = els.height.value;
      const lbl = document.getElementById('heightLabel');
      const val = document.getElementById('heightVal');
      if (lbl) lbl.textContent = v;
      if (val) val.textContent = v + ' ft';
      schedulePushUrlState();
    });

    // Navigate to step 1 when form is submitted (alongside existing loadSite call)
    els.form.addEventListener('submit', () => {
      if (els.address.value.trim()) {
        navigateWizard(1);
        // Show address chip
        const chip = document.getElementById('addressChipRow');
        const chipText = document.getElementById('addressChipText');
        if (chip) chip.hidden = false;
        if (chipText) chipText.textContent = els.address.value.trim();
      }
    });

    readUrlState();

    // ── Add Plans (manual plan library) ─────────────────────────────────────
    // Remembers what to restore on close: a 1-based wizard step, or 'landing'.
    let _addPlansReturnStep = null;

    function openAddPlans() {
      const landing = document.getElementById('landingOverlay');
      const onLanding = landing && !landing.classList.contains('is-dismissed');
      if (onLanding) {
        _addPlansReturnStep = 'landing';
      } else {
        // Capture the wizard step currently on screen (1-based), default to 1.
        const idx = WIZARD_STEP_IDS.findIndex(id => {
          const el = document.getElementById(id);
          return el && !el.hidden;
        });
        _addPlansReturnStep = idx >= 0 ? idx + 1 : 1;
      }

      hideLandingOverlayForTool();
      document.querySelectorAll('.wizard-step').forEach(s => s.hidden = true);
      els.stepAddPlans.hidden = false;
      document.getElementById('stepIndicator').hidden = true;
      // Default the form's city to the active city when known.
      if (els.citySelect?.value) els.addPlanForm.elements.city.value = els.citySelect.value;
      loadManualPlans(_currentPlanCityFilter());
    }

    function closeAddPlans() {
      els.stepAddPlans.hidden = true;
      if (_addPlansReturnStep === 'landing' || _addPlansReturnStep == null) {
        showLandingOverlayFromTool();
      } else {
        navigateWizard(_addPlansReturnStep);
      }
    }

    function _currentPlanCityFilter() {
      const active = els.addPlansCityFilter?.querySelector('.seg-btn.active');
      return active ? (active.dataset.city || '') : '';
    }

    async function loadManualPlans(city) {
      try {
        const qs = city ? `?city=${encodeURIComponent(city)}` : '';
        const res = await fetch(`/api/plans${qs}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderManualPlans(data.plans || []);
      } catch (err) {
        els.addPlansList.innerHTML =
          `<div class="apf-error" style="display:block">Could not load plans: ${escapeHtml(err.message)}</div>`;
      }
    }

    const CITY_LABELS = { san_jose: 'San Jose', sf: 'San Francisco', oakland: 'Oakland' };

    function renderManualPlans(plans) {
      if (!plans.length) {
        els.addPlansList.innerHTML = '';
        els.addPlansEmpty.hidden = false;
        return;
      }
      els.addPlansEmpty.hidden = true;

      els.addPlansList.innerHTML = plans.map(p => {
        const dims = (p.width_ft && p.depth_ft) ? `${p.width_ft}′ × ${p.depth_ft}′` : null;
        const beds = p.bedrooms == null ? null : (p.bedrooms === 0 ? 'Studio' : `${p.bedrooms} bd`);
        const chips = [
          `${Number(p.sqft).toLocaleString()} sqft`,
          beds, dims,
        ].filter(Boolean).map(c => `<span class="plan-chip">${escapeHtml(c)}</span>`).join('');

        const media = p.image_url
          ? `<img class="apc-media" src="${escapeHtml(p.image_url)}" alt="${escapeHtml(p.name)} render" loading="lazy">`
          : `<div class="apc-media apc-media-empty" aria-hidden="true">
               <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>
             </div>`;

        const links = [];
        if (p.floor_plan_url) links.push(`<a href="${escapeHtml(p.floor_plan_url)}" target="_blank" rel="noopener" class="apc-link">Floor plan</a>`);
        if (p.url) links.push(`<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener" class="apc-link">Source</a>`);

        return `
          <div class="apc-card" data-id="${escapeHtml(p.id)}">
            ${media}
            <div class="apc-body">
              <div class="apc-top">
                <span class="apc-city">${escapeHtml(CITY_LABELS[p.city] || p.city)}</span>
                <button type="button" class="apc-delete" data-id="${escapeHtml(p.id)}" aria-label="Delete ${escapeHtml(p.name)}">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                </button>
              </div>
              <div class="apc-name">${escapeHtml(p.name)}</div>
              ${p.vendor ? `<div class="apc-vendor">${escapeHtml(p.vendor)}</div>` : ''}
              <div class="apc-chips">${chips}</div>
              ${links.length ? `<div class="apc-links">${links.join('')}</div>` : ''}
            </div>
          </div>`;
      }).join('');

      els.addPlansList.querySelectorAll('.apc-delete').forEach(btn => {
        btn.addEventListener('click', () => deleteManualPlan(btn.dataset.id));
      });
    }

    async function deleteManualPlan(id) {
      if (!confirm('Delete this plan? This cannot be undone.')) return;
      try {
        const res = await fetch(`/api/plans/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadManualPlans(_currentPlanCityFilter());
      } catch (err) {
        alert(`Could not delete plan: ${err.message}`);
      }
    }

    async function submitAddPlan(e) {
      e.preventDefault();
      els.addPlanError.hidden = true;
      const form = els.addPlanForm;
      if (!form.reportValidity()) return;

      els.addPlanSubmit.disabled = true;
      els.addPlanSubmit.textContent = 'Adding…';
      try {
        // FormData omits empty file inputs cleanly and carries multipart files.
        const fd = new FormData(form);
        // Drop blank optional fields so the server sees them as absent.
        for (const key of ['vendor', 'bedrooms', 'bathrooms', 'width_ft', 'depth_ft', 'url']) {
          if (!fd.get(key)) fd.delete(key);
        }
        for (const key of ['image', 'floor_plan']) {
          const f = fd.get(key);
          if (f && (!(f instanceof File) || f.size === 0)) fd.delete(key);
        }
        const res = await fetch('/api/plans', { method: 'POST', body: fd });
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          throw new Error(_formatPlanError(detail));
        }
        const record = await res.json();
        form.reset();
        if (els.citySelect?.value) form.elements.city.value = els.citySelect.value;
        // Switch the filter to show the city we just added to.
        _focusPlanFilter(record.city);
        loadManualPlans(record.city);
      } catch (err) {
        els.addPlanError.textContent = err.message || 'Could not add plan.';
        els.addPlanError.hidden = false;
      } finally {
        els.addPlanSubmit.disabled = false;
        els.addPlanSubmit.textContent = 'Add plan';
      }
    }

    function _focusPlanFilter(city) {
      const buttons = els.addPlansCityFilter?.querySelectorAll('.seg-btn') || [];
      buttons.forEach(b => b.classList.toggle('active', (b.dataset.city || '') === city));
    }

    function _formatPlanError(detail) {
      // FastAPI returns {detail: [...]} for validation errors, or {detail: "msg"}.
      const d = detail.detail;
      if (Array.isArray(d)) {
        return d.map(e => {
          const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : 'field';
          return `${field}: ${e.msg}`;
        }).join('; ');
      }
      return typeof d === 'string' ? d : 'Could not add plan.';
    }

