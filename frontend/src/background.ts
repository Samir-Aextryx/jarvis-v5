/**
 * Selectable animated background (Settings → Background). Keeps the voice
 * state, audio analyser and suspension when switching renderers.
 */

import { createOrb, type Orb, type OrbState } from "./orb";
import { createSolarSystem } from "./solar";

export type BackgroundMode = "particles" | "solar";

const STORAGE_KEY = "jarvis_background";
const CHANGE_EVENT = "jarvis-background-change";

export function getBackgroundMode(): BackgroundMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === "solar" ? "solar" : "particles";
  } catch {
    return "particles";
  }
}

export function setBackgroundMode(mode: BackgroundMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Storage can be unavailable; the switch still applies to this session.
  }
  window.dispatchEvent(new CustomEvent<BackgroundMode>(CHANGE_EVENT, { detail: mode }));
}

export function createBackground(initialCanvas: HTMLCanvasElement): Orb {
  let canvas = initialCanvas;
  let mode = getBackgroundMode();
  let state: OrbState = "idle";
  let analyser: AnalyserNode | null = null;
  let suspended = false;
  let impl = build();

  function build(): Orb {
    const next = mode === "solar" ? createSolarSystem(canvas) : createOrb(canvas);
    next.setState(state);
    next.setAnalyser(analyser);
    next.setSuspended(suspended);
    return next;
  }

  function onChange(event: Event) {
    const next = (event as CustomEvent<BackgroundMode>).detail === "solar" ? "solar" : "particles";
    if (next === mode) return;
    impl.destroy();
    // A fresh canvas gets a fresh WebGL context for the new renderer.
    const fresh = canvas.cloneNode(false) as HTMLCanvasElement;
    canvas.replaceWith(fresh);
    canvas = fresh;
    mode = next;
    impl = build();
  }

  window.addEventListener(CHANGE_EVENT, onChange);

  return {
    setSuspended(value: boolean) { suspended = value; impl.setSuspended(value); },
    setState(s: OrbState) { state = s; impl.setState(s); },
    setAnalyser(a: AnalyserNode | null) { analyser = a; impl.setAnalyser(a); },
    destroy() {
      window.removeEventListener(CHANGE_EVENT, onChange);
      impl.destroy();
    },
  };
}
