// Globals
let scene, camera, renderer, controls;
let droneMesh; // InstancedMesh for drones
const maxDrones = 6000; // Drone Pool Size limit
const droneGeometry = new THREE.SphereGeometry(0.15, 8, 8);
const droneMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff });

const dummy = new THREE.Object3D(); // For matrix calculations
const colorObject = new THREE.Color();

// Animation state
let showFrames = [];
let currentShowMeta = null;
let isPlaying = false;
let currentFrameIdx = 0;
let lastTime = 0;
let timeAccumulator = 0;
const playbackSpeed = 0.2; // Speed multiplier: 1.0 = normal, 0.02 = 2% speed (ultra slow)
const spreadScale = 1.4;  // Scale drone coordinates to fill the view nicely
const depthScale = 0.05; // Very small depth scale so text/shapes appear flat & readable

// Current and Target arrays for interpolation
let currentPositions = new Float32Array(maxDrones * 3);
let targetPositions = new Float32Array(maxDrones * 3);
let activeDroneCount = 0;

// UI Elements
const statusEl = document.getElementById('status');
const selShow = document.getElementById('show-selector');
const btnLoad = document.getElementById('btn-load');
const btnUpload = document.getElementById('btn-upload');
const fileInput = document.getElementById('video-upload');
const btnPlay = document.getElementById('btn-play');
const btnPause = document.getElementById('btn-pause');
const btnReset = document.getElementById('btn-reset');
const slider = document.getElementById('timeline');

const lblFrame = document.getElementById('lbl-frame');
const lblTotal = document.getElementById('lbl-total');
const lblTime = document.getElementById('lbl-time');
const lblDrones = document.getElementById('lbl-drones');

// Initialization
function init() {
    // 1. Scene Setup
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050510);
    // Fog removed — was obscuring drones at camera distance

    // 2. Camera Setup
    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(89.6, 89.6, 220); // Centered on expanded formation (0-179 units)

    // 3. Renderer Setup
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    document.getElementById('canvas-container').appendChild(renderer.domElement);

    // 4. Controls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = false; // Disabled: keep camera locked at front view
    controls.autoRotateSpeed = 0;
    controls.target.set(89.6, 89.6, 0); // True center of 128x128 formation at spreadScale=1.4

    // Environment helpers
    const gridHelper = new THREE.GridHelper(200, 40, 0x444455, 0x222233);
    gridHelper.position.set(89.6, 0, 0);
    scene.add(gridHelper);

    // 5. Drone Object Pooling (Phase 3 & 8)
    // InstancedMesh allows rendering thousands of identical objects in 1 draw call
    droneMesh = new THREE.InstancedMesh(droneGeometry, droneMaterial, maxDrones);
    droneMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

    // Initialize pool offscreen
    for (let i = 0; i < maxDrones; i++) {
        dummy.position.set(0, -1000, 0);
        dummy.updateMatrix();
        droneMesh.setMatrixAt(i, dummy.matrix);
        droneMesh.setColorAt(i, colorObject.setHex(0x000000));
    }
    droneMesh.instanceMatrix.needsUpdate = true;
    if (droneMesh.instanceColor) droneMesh.instanceColor.needsUpdate = true;
    scene.add(droneMesh);

    // Event Listeners
    window.addEventListener('resize', onWindowResize);
    btnLoad.addEventListener('click', loadShow);
    btnUpload.addEventListener('click', handleUpload);
    btnPlay.addEventListener('click', () => { isPlaying = true; statusEl.innerText = "Status: Playing"; });
    btnPause.addEventListener('click', () => { isPlaying = false; statusEl.innerText = "Status: Paused"; });
    btnReset.addEventListener('click', () => { setFrame(0); isPlaying = false; statusEl.innerText = "Status: Stopped"; });
    slider.addEventListener('input', (e) => {
        setFrame(parseInt(e.target.value));
        isPlaying = false;
        statusEl.innerText = "Status: Scubbing Timeline";
    });

    // Start Loop
    fetchShows();
    requestAnimationFrame(animate);
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

// API Interaction
async function handleUpload() {
    const file = fileInput.files[0];
    if (!file) {
        alert("Please select a video file first.");
        return;
    }

    statusEl.innerText = "Status: Uploading and Processing Video... (this might take a minute)";
    btnUpload.disabled = true;
    btnUpload.innerText = "Processing...";

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch('http://localhost:8000/upload', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
        }

        const data = await res.json();
        statusEl.innerText = "Status: Upload Complete! Reloading shows...";

        // Refresh shows list
        await fetchShows();

        // Auto-select and load the new show
        selShow.value = data.show_id;
        if (selShow.value) {
            await loadShow();
        }

    } catch (e) {
        statusEl.innerText = "Status: Upload Error";
        console.error(e);
        alert("Failed to upload/process video. See console for details.");
    } finally {
        btnUpload.disabled = false;
        btnUpload.innerText = "Upload & Convert Video";
        fileInput.value = ""; // clear input
    }
}

async function fetchShows() {
    try {
        const res = await fetch('http://localhost:8000/shows');
        const shows = await res.json();
        shows.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s._id;
            opt.innerText = `${s.title} (${s.total_frames} frames)`;
            selShow.appendChild(opt);
        });
        statusEl.innerText = "Status: Ready";
    } catch (e) {
        statusEl.innerText = "Status: Error connecting to API";
        console.error(e);
    }
}

async function loadShow() {
    const showId = selShow.value;
    if (!showId) return;

    isPlaying = false;
    statusEl.innerText = `Status: Loading show ${showId}...`;

    try {
        // Fetch Metadata
        const metaRes = await fetch(`http://localhost:8000/shows/${showId}`);
        currentShowMeta = await metaRes.json();

        // Fetch Frames (Option A: Preload all for this implementation scale)
        const frameRes = await fetch(`http://localhost:8000/shows/${showId}/frames`);
        const frameData = await frameRes.json();
        showFrames = frameData.frames;

        // Setup Timeline
        slider.max = currentShowMeta.total_frames > 0 ? currentShowMeta.total_frames - 1 : 0;
        lblTotal.innerText = currentShowMeta.total_frames;

        setFrame(0);
        statusEl.innerText = "Status: Show Loaded. Ready to play.";

    } catch (e) {
        statusEl.innerText = "Status: Error loading show data";
        console.error(e);
    }
}

// Frame Management
function setFrame(idx) {
    if (!showFrames.length) return;
    currentFrameIdx = Math.max(0, Math.min(idx, showFrames.length - 1));

    const frame = showFrames[currentFrameIdx];
    slider.value = currentFrameIdx;
    lblFrame.innerText = currentFrameIdx;
    lblTime.innerText = frame.timestamp.toFixed(2);

    activeDroneCount = Math.min(frame.drones.length, maxDrones);
    lblDrones.innerText = activeDroneCount;

    // Update target positions for interpolation based on drone ID map? 
    // For simplicity, we assume drones array order is stable or we just match index
    for (let i = 0; i < maxDrones; i++) {
        if (i < activeDroneCount) {
            const d = frame.drones[i];
            // ThreeJS coordinate mapping: 
            // Our logic: x=horizontal, y=vertical(z natively), z=depth(y natively)
            // But we created points: x, y, z(depth). Let's map Z upward in 3D.
            targetPositions[i * 3] = d.x * spreadScale; // X = column (horizontal)
            targetPositions[i * 3 + 1] = d.y * spreadScale; // Y = row-flipped (vertical height) → text reads upright
            targetPositions[i * 3 + 2] = d.z * depthScale;  // Z = brightness depth (kept tiny so shape stays flat)

            // Set Color
            let c = d.light || "#ffffff";
            droneMesh.setColorAt(i, colorObject.set(c));

            // If teleporting (e.g. scrubbing), immediately jump current to target
            if (!isPlaying) {
                currentPositions[i * 3] = targetPositions[i * 3];
                currentPositions[i * 3 + 1] = targetPositions[i * 3 + 1];
                currentPositions[i * 3 + 2] = targetPositions[i * 3 + 2];
            }
        } else {
            // Hide unused drones far underground
            targetPositions[i * 3] = 0;
            targetPositions[i * 3 + 1] = -1000;
            targetPositions[i * 3 + 2] = 0;

            if (!isPlaying) {
                currentPositions[i * 3] = 0;
                currentPositions[i * 3 + 1] = -1000;
                currentPositions[i * 3 + 2] = 0;
            }
        }
    }

    if (droneMesh.instanceColor) droneMesh.instanceColor.needsUpdate = true;
}

// Animation Loop
function animate(time) {
    requestAnimationFrame(animate);

    // Calculate DeltaTime (in seconds)
    const dt = (time - lastTime) / 1000;
    lastTime = time;

    // Phase 7: Real-Time Timing Control
    if (isPlaying && currentShowMeta) {
        timeAccumulator += dt * playbackSpeed;
        const frameDuration = 1 / currentShowMeta.fps;

        if (timeAccumulator >= frameDuration) {
            timeAccumulator -= frameDuration; // Keep remainder for accurate pacing
            let nextIndex = currentFrameIdx + 1;

            if (nextIndex >= showFrames.length) {
                // Loop or Stop
                isPlaying = false;
                statusEl.innerText = "Status: Show Finished";
            } else {
                setFrame(nextIndex);
            }
        }
    }

    // Phase 5 & 6: Interpolation Layer
    // Interpolate from currentPositions towards targetPositions
    const alpha = isPlaying ? 0.6 : 1.0; // Faster snap = crisper letters, less ghosting

    for (let i = 0; i < maxDrones; i++) {
        const idxX = i * 3;
        const idxY = i * 3 + 1;
        const idxZ = i * 3 + 2;

        currentPositions[idxX] += (targetPositions[idxX] - currentPositions[idxX]) * alpha;
        currentPositions[idxY] += (targetPositions[idxY] - currentPositions[idxY]) * alpha;
        currentPositions[idxZ] += (targetPositions[idxZ] - currentPositions[idxZ]) * alpha;

        dummy.position.set(
            currentPositions[idxX],
            currentPositions[idxY],
            currentPositions[idxZ]
        );
        dummy.updateMatrix();
        droneMesh.setMatrixAt(i, dummy.matrix);
    }

    droneMesh.instanceMatrix.needsUpdate = true;

    controls.update();
    renderer.render(scene, camera);
}

// Start
init();
