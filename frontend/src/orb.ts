/**
 * JARVIS — Multi-mode particle visualization.
 *
 * Floating particles with line connections between nearby ones.
 * Lines fade in/out based on state. Transition tumble on state change.
 * Speaking pulls particles closer for denser connections.
 */

import * as THREE from "three";
import { findConnections } from "./orb-connections";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

export interface Orb {
  setSuspended(suspended: boolean): void;
  setState(s: OrbState): void;
  setAnalyser(a: AnalyserNode | null): void;
  destroy(): void;
}

export function createOrb(canvas: HTMLCanvasElement): Orb {
  let destroyed = false;
  let suspended = false;
  const N = 1200;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x050508, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 1, 1000);
  camera.position.z = 80;

  // ── Particles ──
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(N * 3);
  const vel = new Float32Array(N * 3);
  const phase = new Float32Array(N);

  for (let i = 0; i < N; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = Math.pow(Math.random(), 0.5) * 25;
    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = r * Math.cos(phi);
    phase[i] = Math.random() * 1000;
  }

  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));

  const mat = new THREE.PointsMaterial({
    color: 0x4ca8e8, size: 0.4, transparent: true, opacity: 0.6,
    sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const points = new THREE.Points(geo, mat);
  scene.add(points);

  // ── Connection lines ──
  const MAX_LINES = 8000;
  const connectionPairs = new Uint32Array(MAX_LINES * 2);
  let connectionCount = 0;
  let lastConnectionSearch = -Infinity;
  const thinkingColor = new THREE.Color(0x6ec4ff);
  const speakingColor = new THREE.Color(0x5ab8f0);
  const idleColor = new THREE.Color(0x4ca8e8);
  const linePos = new Float32Array(MAX_LINES * 6);
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
  lineGeo.setDrawRange(0, 0);

  const lineMat = new THREE.LineBasicMaterial({
    color: 0x4ca8e8, transparent: true, opacity: 0.0,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const lines = new THREE.LineSegments(lineGeo, lineMat);
  scene.add(lines);

  // ── Electrons — bright dots that travel along connections ──
  const MAX_ELECTRONS = 200;
  const electronGeo = new THREE.BufferGeometry();
  const electronPos = new Float32Array(MAX_ELECTRONS * 3);
  electronGeo.setAttribute("position", new THREE.BufferAttribute(electronPos, 3));
  electronGeo.setDrawRange(0, 0);

  const electronMat = new THREE.PointsMaterial({
    color: 0xffffff, size: 0.8, transparent: true, opacity: 1.0,
    sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const electrons = new THREE.Points(electronGeo, electronMat);
  scene.add(electrons);

  // Each electron: start point, end point, progress (0-1), speed
  interface Electron { sx: number; sy: number; sz: number; ex: number; ey: number; ez: number; t: number; speed: number; }
  const activeElectrons: Electron[] = [];
  let electronSpawnRate = 0;
  let targetElectronRate = 0;
  let lastElectronSpawn = 0; // timestamp of last spawn

  // Store active connections for electron spawning
  let activeConnections: { x1: number; y1: number; z1: number; x2: number; y2: number; z2: number }[] = [];

  // ── State ──
  let state: OrbState = "idle";
  let targetRadius = 25, currentRadius = 25;
  let targetSpeed = 0.3, currentSpeed = 0.3;
  let targetBright = 0.6, currentBright = 0.6;
  let targetSize = 0.4, currentSize = 0.4;
  let lineAmount = 0, targetLineAmount = 0;
  let lineDistance = 8;

  // Transition tumble
  let spinX = 0, spinY = 0, spinZ = 0;
  let transitionEnergy = 0;
  let lastState: OrbState = "idle";

  // Depth Z
  let cloudZ = 0, cloudZVel = 0;

  // ── Audio ──
  let analyser: AnalyserNode | null = null;
  let freqData = new Uint8Array(64);
  let bass = 0, mid = 0;

  const clock = new THREE.Clock();

  let lastFrame = 0;
  let lastSimulation = 0;
  function animate() {
    if (destroyed) return;
    requestAnimationFrame(animate);
    if (document.hidden || suspended) { lastSimulation = 0; return; }
    const now = performance.now();
    const interval = 1000 / (state === "idle" ? 30 : 60);
    if (now - lastFrame < interval) return;
    lastFrame = now - ((now - lastFrame) % interval);
    const dt = lastSimulation ? Math.min(3, (now - lastSimulation) / (1000 / 60)) : 1;
    lastSimulation = now;
    const smoothing = 1 - Math.pow(0.98, dt);
    const t = clock.getElapsedTime();

    switch (state) {
      case "idle":
        targetRadius = 28; targetSpeed = 0.2; targetBright = 0.5; targetSize = 0.35;
        targetLineAmount = 0.15; targetElectronRate = 0; break;
      case "listening":
        targetRadius = 22; targetSpeed = 0.3; targetBright = 0.65; targetSize = 0.4;
        targetLineAmount = 0.4; targetElectronRate = 0; break;
      case "thinking":
        targetRadius = 16; targetSpeed = 0.5; targetBright = 0.7; targetSize = 0.3;
        targetLineAmount = 1.0; targetElectronRate = 0.015; break;
      case "speaking":
        targetRadius = 18; targetSpeed = 0.2; targetBright = 0.7; targetSize = 0.4;
        targetLineAmount = 0.8; targetElectronRate = 0; break;
    }

    currentRadius += (targetRadius - currentRadius) * smoothing;
    currentSpeed += (targetSpeed - currentSpeed) * smoothing;
    currentBright += (targetBright - currentBright) * smoothing;
    currentSize += (targetSize - currentSize) * smoothing;
    lineAmount += (targetLineAmount - lineAmount) * smoothing;
    electronSpawnRate += (targetElectronRate - electronSpawnRate) * smoothing;

    // Transition energy
    if (state !== lastState) { transitionEnergy = 1.0; lastState = state; }
    transitionEnergy *= Math.pow(0.985, dt);
    if (transitionEnergy > 0.05) {
      spinX += transitionEnergy * 0.012 * Math.sin(t * 1.7) * dt;
      spinY += transitionEnergy * 0.015 * dt;
      spinZ += transitionEnergy * 0.008 * Math.cos(t * 1.3) * dt;
    }

    // Audio
    bass = 0; mid = 0;
    if (analyser) {
      analyser.getByteFrequencyData(freqData);
      let bSum = 0, mSum = 0;
      for (let i = 0; i < 8; i++) bSum += freqData[i];
      for (let i = 8; i < 24; i++) mSum += freqData[i];
      bass = bSum / (8 * 255); mid = mSum / (16 * 255);
    }

    // Depth Z breathing
    let zTarget = Math.sin(t * 0.12) * 8;
    if (state === "thinking") zTarget = Math.sin(t * 0.3) * 15 + Math.sin(t * 0.9) * 6;
    else if (state === "speaking") zTarget = Math.sin(t * 0.15) * 6 - bass * 10;
    cloudZVel += (zTarget - cloudZ) * 0.008 * dt;
    cloudZVel *= Math.pow(0.94, dt);
    cloudZ += cloudZVel * dt;

    points.rotation.x = spinX; points.rotation.y = spinY; points.rotation.z = spinZ;
    points.position.z = cloudZ;
    lines.rotation.x = spinX; lines.rotation.y = spinY; lines.rotation.z = spinZ;
    lines.position.z = cloudZ;

    // ── Update particles ──
    const p = geo.getAttribute("position") as THREE.BufferAttribute;
    const a = p.array as Float32Array;

    for (let i = 0; i < N; i++) {
      const i3 = i * 3;
      let x = a[i3], y = a[i3 + 1], z = a[i3 + 2];
      const px = phase[i];

      vel[i3] += Math.sin(t * 0.05 + px) * 0.001 * currentSpeed * dt;
      vel[i3 + 1] += Math.cos(t * 0.06 + px * 1.3) * 0.001 * currentSpeed * dt;
      vel[i3 + 2] += Math.sin(t * 0.055 + px * 0.7) * 0.001 * currentSpeed * dt;
      vel[i3] += Math.sin(t * 0.02 + px * 2.1 + y * 0.1) * 0.0008 * currentSpeed * dt;
      vel[i3 + 1] += Math.cos(t * 0.025 + px * 1.7 + z * 0.1) * 0.0008 * currentSpeed * dt;
      vel[i3 + 2] += Math.sin(t * 0.022 + px * 0.9 + x * 0.1) * 0.0008 * currentSpeed * dt;

      const dist = Math.sqrt(x * x + y * y + z * z) || 0.01;
      const pull = Math.max(0, dist - currentRadius) * 0.002 + 0.0003;
      vel[i3] -= (x / dist) * pull * dt;
      vel[i3 + 1] -= (y / dist) * pull * dt;
      vel[i3 + 2] -= (z / dist) * pull * dt;

      if (bass > 0.05) {
        vel[i3] += (x / dist) * bass * 0.02 * dt;
        vel[i3 + 1] += (y / dist) * bass * 0.02 * dt;
        vel[i3 + 2] += (z / dist) * bass * 0.02 * dt;
      }
      if (state === "speaking" && mid > 0.1) {
        const pulse = Math.sin(t * 8 + px);
        vel[i3] += (x / dist) * mid * 0.012 * pulse * dt;
        vel[i3 + 1] += (y / dist) * mid * 0.012 * pulse * dt;
      }

      vel[i3] *= Math.pow(0.992, dt); vel[i3 + 1] *= Math.pow(0.992, dt); vel[i3 + 2] *= Math.pow(0.992, dt);
      a[i3] += vel[i3] * dt; a[i3 + 1] += vel[i3 + 1] * dt; a[i3 + 2] += vel[i3 + 2] * dt;
    }
    p.needsUpdate = true;

    // ── Update lines ──
    if (lineAmount > 0.01) {
      const lp = lineGeo.getAttribute("position") as THREE.BufferAttribute;
      const la = lp.array as Float32Array;
      if (now - lastConnectionSearch >= 100) {
        connectionCount = findConnections(a, Math.max(1, Math.floor(N / 600)), lineDistance * (1 + bass * 0.5), connectionPairs);
        lastConnectionSearch = now;
      }
      const lineCount = connectionCount;
      for (let c = 0; c < lineCount; c++) {
        const start = connectionPairs[c * 2] * 3;
        const end = connectionPairs[c * 2 + 1] * 3;
        const offset = c * 6;
        la[offset] = a[start]; la[offset + 1] = a[start + 1]; la[offset + 2] = a[start + 2];
        la[offset + 3] = a[end]; la[offset + 4] = a[end + 1]; la[offset + 5] = a[end + 2];
      }
      lineGeo.setDrawRange(0, lineCount * 2);
      lp.needsUpdate = true;
      lineMat.opacity = lineAmount * 0.12;

      // Store connections for electron spawning
      activeConnections.length = Math.min(lineCount, 500);
      for (let c = 0; c < Math.min(lineCount, 500); c++) {
        const ci = c * 6;
        const conn = activeConnections[c] || (activeConnections[c] = {x1:0,y1:0,z1:0,x2:0,y2:0,z2:0});
        conn.x1 = la[ci]; conn.y1 = la[ci+1]; conn.z1 = la[ci+2];
        conn.x2 = la[ci+3]; conn.y2 = la[ci+4]; conn.z2 = la[ci+5];
      }
    } else {
      lineGeo.setDrawRange(0, 0);
      activeConnections.length = 0;
      lastConnectionSearch = -Infinity;
    }

    // ── Update electrons — only during thinking ──
    // One fires off every ~1 second, max 3 alive, takes 2-4s to travel
    if (activeConnections.length > 0 && electronSpawnRate > 0.005) {
      if (activeElectrons.length < 3 && (t - lastElectronSpawn) > 1.0) {
        const conn = activeConnections[Math.floor(Math.random() * activeConnections.length)];
        // speed: 1/fps * speed = progress per frame. At 60fps, speed 0.005 = 200 frames = 3.3s
        activeElectrons.push({
          sx: conn.x1, sy: conn.y1, sz: conn.z1,
          ex: conn.x2, ey: conn.y2, ez: conn.z2,
          t: 0,
          speed: 0.003 + Math.random() * 0.003, // 2-4 seconds to travel
        });
        lastElectronSpawn = t;
      }
    }

    // Update electron positions
    const ep = electronGeo.getAttribute("position") as THREE.BufferAttribute;
    const ea = ep.array as Float32Array;
    let aliveCount = 0;

    for (let e = activeElectrons.length - 1; e >= 0; e--) {
      const el = activeElectrons[e];
      el.t += el.speed * dt;
      if (el.t >= 1) {
        activeElectrons.splice(e, 1);
        continue;
      }
      const ei = aliveCount * 3;
      ea[ei] = el.sx + (el.ex - el.sx) * el.t;
      ea[ei + 1] = el.sy + (el.ey - el.sy) * el.t;
      ea[ei + 2] = el.sz + (el.ez - el.sz) * el.t;
      aliveCount++;
    }

    electronGeo.setDrawRange(0, aliveCount);
    ep.needsUpdate = true;

    // Electrons follow the same rotation/position as the main group
    electrons.rotation.x = spinX; electrons.rotation.y = spinY; electrons.rotation.z = spinZ;
    electrons.position.z = cloudZ;

    mat.opacity = currentBright + bass * 0.08;
    mat.size = currentSize + bass * 0.05;

    if (state === "thinking") { mat.color.lerp(thinkingColor, 1 - Math.pow(0.985, dt)); lineMat.color.lerp(thinkingColor, 1 - Math.pow(0.985, dt)); }
    else if (state === "speaking") { mat.color.lerp(speakingColor, 1 - Math.pow(0.985, dt)); lineMat.color.lerp(speakingColor, 1 - Math.pow(0.985, dt)); }
    else { mat.color.lerp(idleColor, 1 - Math.pow(0.985, dt)); lineMat.color.lerp(idleColor, 1 - Math.pow(0.985, dt)); }

    camera.position.x = Math.sin(t * 0.02) * 5;
    camera.position.y = Math.cos(t * 0.03) * 3;
    camera.lookAt(0, 0, cloudZ * 0.2);

    renderer.render(scene, camera);
  }

  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }

  window.addEventListener("resize", onResize);
  animate();

  return {
    setSuspended(value: boolean) { suspended = value; lastSimulation = 0; lastFrame = 0; },
    setState(s: OrbState) { state = s; },
    setAnalyser(a: AnalyserNode | null) {
      analyser = a;
      if (a) freqData = new Uint8Array(a.frequencyBinCount);
    },
    destroy() {
      destroyed = true;
      window.removeEventListener("resize", onResize);
      renderer.dispose();
    },
  };
}
