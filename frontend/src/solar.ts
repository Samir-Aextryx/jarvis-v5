/**
 * JARVIS — Solar system background.
 *
 * The sun and eight planets on their orbits. Same interface as the particle
 * orb: thinking speeds the orbits up, listening highlights the orbit rings
 * and speaking makes the sun pulse with the voice.
 */

import * as THREE from "three";
import type { Orb, OrbState } from "./orb";

interface PlanetSpec {
  name: string;
  radius: number;
  distance: number;
  colors: [number, number];
  bands: number;
  tilt: number;
  spin: number;
  ring?: boolean;
  moon?: boolean;
}

const PLANETS: PlanetSpec[] = [
  { name: "Mercury", radius: 0.7, distance: 12, colors: [0x8c8c8c, 0x5e5e5e], bands: 0, tilt: 0.0, spin: 0.2 },
  { name: "Venus", radius: 1.2, distance: 16.5, colors: [0xe8c27a, 0xc99a4f], bands: 3, tilt: 0.05, spin: -0.1 },
  { name: "Earth", radius: 1.3, distance: 21.5, colors: [0x2f6fd1, 0x3f9a4a], bands: 0, tilt: 0.41, spin: 1.0, moon: true },
  { name: "Mars", radius: 0.95, distance: 27, colors: [0xc1440e, 0x8a2f0a], bands: 0, tilt: 0.44, spin: 0.95 },
  { name: "Jupiter", radius: 3.1, distance: 37, colors: [0xd8a36b, 0x9c6b42], bands: 9, tilt: 0.05, spin: 2.2 },
  { name: "Saturn", radius: 2.6, distance: 48, colors: [0xe3cf8f, 0xb59b5b], bands: 7, tilt: 0.47, spin: 2.0, ring: true },
  { name: "Uranus", radius: 1.8, distance: 57, colors: [0x8fdde6, 0x6cbfcb], bands: 2, tilt: 1.7, spin: -1.4 },
  { name: "Neptune", radius: 1.75, distance: 65, colors: [0x3f61d6, 0x2a3f9c], bands: 3, tilt: 0.49, spin: 1.5 },
];

/** Procedural surface: bands for gas giants, speckles for rocky planets. */
function planetTexture(spec: PlanetSpec): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 128;
  const g = c.getContext("2d")!;
  const [a, b] = spec.colors.map((v) => `#${v.toString(16).padStart(6, "0")}`);
  g.fillStyle = a;
  g.fillRect(0, 0, c.width, c.height);
  if (spec.bands > 0) {
    for (let i = 0; i < spec.bands * 2; i++) {
      g.globalAlpha = 0.18 + Math.random() * 0.3;
      g.fillStyle = i % 2 ? b : a;
      const y = Math.random() * c.height;
      g.fillRect(0, y, c.width, 3 + Math.random() * 12);
    }
  } else {
    for (let i = 0; i < 160; i++) {
      g.globalAlpha = 0.25 + Math.random() * 0.45;
      g.fillStyle = b;
      g.beginPath();
      g.arc(Math.random() * c.width, Math.random() * c.height, 2 + Math.random() * 10, 0, Math.PI * 2);
      g.fill();
    }
    if (spec.name === "Earth") {
      g.globalAlpha = 0.5;
      g.fillStyle = "#ffffff";
      g.fillRect(0, 0, c.width, 7);
      g.fillRect(0, c.height - 7, c.width, 7);
    }
  }
  g.globalAlpha = 1;
  const texture = new THREE.CanvasTexture(c);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Soft radial glow used for the sun's corona. */
function glowTexture(inner: string, outer: string): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const gradient = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  gradient.addColorStop(0, inner);
  gradient.addColorStop(0.25, outer);
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = gradient;
  g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

export function createSolarSystem(canvas: HTMLCanvasElement): Orb {
  let destroyed = false;
  let suspended = false;
  const disposables: { dispose(): void }[] = [];
  const keep = <T extends { dispose(): void }>(item: T): T => { disposables.push(item); return item; };

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x020206, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.5, 2000);

  // ── Stars ──
  const STARS = 2200;
  const starPos = new Float32Array(STARS * 3);
  for (let i = 0; i < STARS; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = 420 + Math.random() * 300;
    starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    starPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    starPos[i * 3 + 2] = r * Math.cos(phi);
  }
  const starGeo = keep(new THREE.BufferGeometry());
  starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
  const starMat = keep(new THREE.PointsMaterial({ color: 0xcfe3ff, size: 1.4, sizeAttenuation: true, transparent: true, opacity: 0.8, depthWrite: false }));
  scene.add(new THREE.Points(starGeo, starMat));

  // ── Sun ──
  const sunGeo = keep(new THREE.SphereGeometry(5.5, 48, 48));
  const sunMat = keep(new THREE.MeshBasicMaterial({ color: 0xffc35a }));
  const sun = new THREE.Mesh(sunGeo, sunMat);
  scene.add(sun);
  const coronaTex = keep(glowTexture("rgba(255,236,170,1)", "rgba(255,150,40,0.55)"));
  const coronaMat = keep(new THREE.SpriteMaterial({ map: coronaTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
  const corona = new THREE.Sprite(coronaMat);
  corona.scale.set(34, 34, 1);
  scene.add(corona);
  const haloTex = keep(glowTexture("rgba(110,196,255,0.5)", "rgba(76,168,232,0.18)"));
  const haloMat = keep(new THREE.SpriteMaterial({ map: haloTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0 }));
  const halo = new THREE.Sprite(haloMat);
  halo.scale.set(60, 60, 1);
  scene.add(halo);

  scene.add(new THREE.AmbientLight(0x334466, 0.35));
  const sunLight = new THREE.PointLight(0xfff1d6, 3.2, 0, 0);
  scene.add(sunLight);

  // ── Planets, orbits, moon and Saturn's ring ──
  const orbitMats: THREE.LineBasicMaterial[] = [];
  const planets = PLANETS.map((spec) => {
    const pivot = new THREE.Object3D();
    pivot.rotation.y = Math.random() * Math.PI * 2;
    scene.add(pivot);
    const holder = new THREE.Object3D();
    holder.position.x = spec.distance;
    holder.rotation.z = spec.tilt;
    pivot.add(holder);
    const texture = keep(planetTexture(spec));
    const mesh = new THREE.Mesh(
      keep(new THREE.SphereGeometry(spec.radius, 32, 32)),
      keep(new THREE.MeshStandardMaterial({ map: texture, roughness: 0.92, metalness: 0 })),
    );
    holder.add(mesh);
    if (spec.ring) {
      const ring = new THREE.Mesh(
        keep(new THREE.RingGeometry(spec.radius * 1.35, spec.radius * 2.3, 96)),
        keep(new THREE.MeshBasicMaterial({ color: 0xd9c48f, side: THREE.DoubleSide, transparent: true, opacity: 0.55, depthWrite: false })),
      );
      ring.rotation.x = Math.PI / 2;
      holder.add(ring);
    }
    let moonPivot: THREE.Object3D | null = null;
    if (spec.moon) {
      moonPivot = new THREE.Object3D();
      const moon = new THREE.Mesh(
        keep(new THREE.SphereGeometry(0.36, 16, 16)),
        keep(new THREE.MeshStandardMaterial({ color: 0xbbbbbb, roughness: 1 })),
      );
      moon.position.x = spec.radius + 1.3;
      moonPivot.add(moon);
      holder.add(moonPivot);
    }
    const points: THREE.Vector3[] = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      points.push(new THREE.Vector3(Math.cos(a) * spec.distance, 0, Math.sin(a) * spec.distance));
    }
    const orbitMat = keep(new THREE.LineBasicMaterial({ color: 0x4ca8e8, transparent: true, opacity: 0.14, depthWrite: false }));
    orbitMats.push(orbitMat);
    scene.add(new THREE.LineLoop(keep(new THREE.BufferGeometry().setFromPoints(points)), orbitMat));
    // Kepler-like: angular speed falls with distance^1.5.
    const speed = 13 / Math.pow(spec.distance, 1.5);
    return { spec, pivot, mesh, moonPivot, speed };
  });

  // ── State ──
  let state: OrbState = "idle";
  let speedFactor = 1, targetSpeed = 1;
  let orbitOpacity = 0.14, targetOrbit = 0.14;
  let haloAmount = 0, targetHalo = 0;
  let zoom = 1, targetZoom = 1;
  let analyser: AnalyserNode | null = null;
  let freqData = new Uint8Array(64);
  const idleOrbit = new THREE.Color(0x4ca8e8);
  const thinkingOrbit = new THREE.Color(0x6ec4ff);

  const clock = new THREE.Clock();
  let lastFrame = 0;
  let lastSimulation = 0;
  let cameraAngle = Math.random() * Math.PI * 2;

  function animate() {
    if (destroyed) return;
    requestAnimationFrame(animate);
    if (document.hidden || suspended) { lastSimulation = 0; return; }
    const now = performance.now();
    const interval = 1000 / (state === "idle" ? 30 : 60);
    if (now - lastFrame < interval) return;
    lastFrame = now - ((now - lastFrame) % interval);
    const dt = lastSimulation ? Math.min(0.1, (now - lastSimulation) / 1000) : 1 / 60;
    lastSimulation = now;
    const smoothing = 1 - Math.pow(0.02, dt);
    const t = clock.getElapsedTime();

    switch (state) {
      case "idle": targetSpeed = 1; targetOrbit = 0.14; targetHalo = 0; targetZoom = 1; break;
      case "listening": targetSpeed = 0.6; targetOrbit = 0.32; targetHalo = 0.35; targetZoom = 0.94; break;
      case "thinking": targetSpeed = 4; targetOrbit = 0.42; targetHalo = 0.75; targetZoom = 0.86; break;
      case "speaking": targetSpeed = 1.2; targetOrbit = 0.22; targetHalo = 0.25; targetZoom = 0.92; break;
    }
    speedFactor += (targetSpeed - speedFactor) * smoothing;
    orbitOpacity += (targetOrbit - orbitOpacity) * smoothing;
    haloAmount += (targetHalo - haloAmount) * smoothing;
    zoom += (targetZoom - zoom) * smoothing;

    let bass = 0;
    if (analyser) {
      analyser.getByteFrequencyData(freqData);
      let sum = 0;
      for (let i = 0; i < 8; i++) sum += freqData[i];
      bass = sum / (8 * 255);
    }

    for (const p of planets) {
      p.pivot.rotation.y += p.speed * speedFactor * dt * 0.35;
      p.mesh.rotation.y += p.spec.spin * dt * 0.6;
      if (p.moonPivot) p.moonPivot.rotation.y += dt * 1.6 * speedFactor;
    }
    sun.rotation.y += dt * 0.05;

    const pulse = 1 + bass * 0.35 + Math.sin(t * 1.3) * 0.015;
    sun.scale.setScalar(1 + bass * 0.12);
    corona.scale.set(34 * pulse, 34 * pulse, 1);
    coronaMat.opacity = 0.85 + bass * 0.15;
    haloMat.opacity = haloAmount * (0.6 + 0.4 * Math.sin(t * (state === "thinking" ? 3 : 1.2)) ** 2);
    sunLight.intensity = 3.2 + bass * 2;

    const orbitColor = state === "thinking" || state === "listening" ? thinkingOrbit : idleOrbit;
    for (const m of orbitMats) {
      m.opacity = orbitOpacity;
      m.color.lerp(orbitColor, smoothing);
    }

    cameraAngle += dt * 0.012 * (state === "thinking" ? 2.5 : 1);
    const radius = 118 * zoom;
    camera.position.set(Math.sin(cameraAngle) * radius, 46 * zoom + Math.sin(t * 0.07) * 4, Math.cos(cameraAngle) * radius);
    camera.lookAt(0, 0, 0);

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
      for (const item of disposables) item.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
