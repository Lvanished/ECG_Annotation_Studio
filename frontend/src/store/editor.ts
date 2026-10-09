import { create } from 'zustand';
import type { Annotation, BatchResult, Recording } from '../api/types';
import type { AnnMap } from '../lib/annotations';
import { centerOn, clampView, pan as panView, zoomAt, type View } from '../lib/viewport';

const HISTORY_LIMIT = 200;

export type Tool = 'select' | 'annotate';

export interface EditorState {
  // recording + shared viewport
  recording: Recording | null;
  view: View;
  cursor: number | null;
  selection: [number, number] | null; // half-open [a, b)
  // display / UI
  displayLeads: string[];
  annotationLead: string | null; // lead for new annotations; null = global
  activeTier: string;
  activeLabels: Record<string, string>;
  tool: Tool;
  hiddenTiers: string[];
  collapsedTiers: string[];
  selectedId: string | null;
  selectedPredictionId: string | null;
  predictionEdits: Record<string, number>; // prediction id -> moved start sample (before acceptance)
  mvPerStrip: number;
  status: { text: string; kind: 'info' | 'error' | 'ok' };
  // annotation document (working copy with undo/redo)
  server: AnnMap;
  working: AnnMap;
  undoStack: AnnMap[];
  redoStack: AnnMap[];
  docVersion: number;
  gestureOpen: boolean;

  setRecording: (r: Recording | null) => void;
  setView: (start: number, end: number) => void;
  zoom: (factor: number, anchor?: number) => void;
  pan: (deltaSamples: number) => void;
  center: (sample: number) => void;
  setCursor: (s: number | null) => void;
  setSelection: (sel: [number, number] | null) => void;
  setDisplayLeads: (leads: string[]) => void;
  setAnnotationLead: (lead: string | null) => void;
  setActiveTier: (t: string) => void;
  setActiveLabel: (tier: string, label: string) => void;
  setTool: (t: Tool) => void;
  toggleHidden: (t: string) => void;
  toggleCollapsed: (t: string) => void;
  select: (id: string | null) => void;
  selectPrediction: (id: string | null) => void;
  editPrediction: (id: string, start: number | null) => void;
  setMvPerStrip: (v: number) => void;
  setStatus: (text: string, kind?: 'info' | 'error' | 'ok') => void;

  loadDocument: (anns: Annotation[]) => void;
  commit: (fn: (w: AnnMap) => AnnMap) => void;
  beginGesture: () => void;
  live: (fn: (w: AnnMap) => AnnMap) => void;
  endGesture: (changed: boolean) => void;
  undo: () => void;
  redo: () => void;
  applySave: (res: BatchResult) => void;
  ingest: (anns: Annotation[]) => void;
}

const DEFAULT_TIER = 'Fiducial Points';

export const useEditor = create<EditorState>((set, get) => ({
  recording: null,
  view: { start: 0, end: 1 },
  cursor: null,
  selection: null,
  displayLeads: [],
  annotationLead: null,
  activeTier: DEFAULT_TIER,
  activeLabels: {
    'Fiducial Points': 'R_peak',
    'P Wave': 'P_wave',
    'QRS Complex': 'QRS_complex',
    'T Wave': 'T_wave',
    'ST Segment': 'ST_segment',
    'PR Segment': 'PR_segment',
    'U Wave': 'U_wave',
    Beat: 'normal_beat',
    Rhythm: 'sinus_rhythm',
    Morphology: 'notched',
    'Signal Quality': 'noise',
    Interpretation: 'uncertain_finding',
  },
  tool: 'select',
  hiddenTiers: [],
  collapsedTiers: [],
  selectedId: null,
  selectedPredictionId: null,
  predictionEdits: {},
  mvPerStrip: 3,
  status: { text: 'Select a dataset and recording.', kind: 'info' },
  server: {},
  working: {},
  undoStack: [],
  redoStack: [],
  docVersion: 0,
  gestureOpen: false,

  setRecording: (r) => {
    if (!r) return set({ recording: null });
    const lead = r.leads.includes('II') ? 'II' : r.leads[0];
    const span = Math.min(r.n_samples, Math.round(r.fs * 10));
    set({
      recording: r,
      view: clampView(0, span, r.n_samples),
      cursor: null,
      selection: null,
      displayLeads: r.leads.length <= 3 ? [...r.leads] : r.leads.length === 12 ? [...r.leads] : [lead],
      annotationLead: lead,
      selectedId: null,
      selectedPredictionId: null,
      predictionEdits: {},
      mvPerStrip: r.leads.length >= 12 ? 2.5 : 3,
    });
  },
  setView: (start, end) => {
    const r = get().recording;
    if (r) set({ view: clampView(start, end, r.n_samples) });
  },
  zoom: (factor, anchor) => {
    const { recording: r, view, cursor } = get();
    if (!r) return;
    const a = anchor ?? cursor ?? Math.round((view.start + view.end) / 2);
    set({ view: zoomAt(view, a, factor, r.n_samples) });
  },
  pan: (d) => {
    const { recording: r, view } = get();
    if (r) set({ view: panView(view, d, r.n_samples) });
  },
  center: (s) => {
    const { recording: r, view } = get();
    if (r) set({ view: centerOn(view, s, r.n_samples) });
  },
  setCursor: (cursor) => set({ cursor }),
  setSelection: (selection) => set({ selection }),
  setDisplayLeads: (displayLeads) => set({ displayLeads }),
  setAnnotationLead: (annotationLead) => set({ annotationLead }),
  setActiveTier: (activeTier) => set({ activeTier }),
  setActiveLabel: (tier, label) => set((s) => ({ activeLabels: { ...s.activeLabels, [tier]: label } })),
  setTool: (tool) => set({ tool }),
  toggleHidden: (t) =>
    set((s) => ({ hiddenTiers: s.hiddenTiers.includes(t) ? s.hiddenTiers.filter((x) => x !== t) : [...s.hiddenTiers, t] })),
  toggleCollapsed: (t) =>
    set((s) => ({
      collapsedTiers: s.collapsedTiers.includes(t) ? s.collapsedTiers.filter((x) => x !== t) : [...s.collapsedTiers, t],
    })),
  select: (selectedId) => set({ selectedId, selectedPredictionId: null }),
  selectPrediction: (selectedPredictionId) => set({ selectedPredictionId, selectedId: null }),
  editPrediction: (id, start) =>
    set((s) => {
      const next = { ...s.predictionEdits };
      if (start === null) delete next[id];
      else next[id] = start;
      return { predictionEdits: next };
    }),
  setMvPerStrip: (mvPerStrip) => set({ mvPerStrip }),
  setStatus: (text, kind = 'info') => set({ status: { text, kind } }),

  loadDocument: (anns) => {
    const m: AnnMap = {};
    for (const a of anns) m[a.id] = a;
    set({ server: m, working: m, undoStack: [], redoStack: [], docVersion: get().docVersion + 1, selectedId: null });
  },
  commit: (fn) => {
    const { working, undoStack } = get();
    const next = fn(working);
    if (next === working) return;
    set({
      working: next,
      undoStack: [...undoStack, working].slice(-HISTORY_LIMIT),
      redoStack: [],
      docVersion: get().docVersion + 1,
    });
  },
  beginGesture: () => {
    const { working, undoStack } = get();
    set({ undoStack: [...undoStack, working].slice(-HISTORY_LIMIT), redoStack: [], gestureOpen: true });
  },
  live: (fn) => set((s) => ({ working: fn(s.working), docVersion: s.docVersion + 1 })),
  endGesture: (changed) => {
    const { undoStack } = get();
    if (!changed) set({ undoStack: undoStack.slice(0, -1), gestureOpen: false });
    else set({ gestureOpen: false });
  },
  undo: () => {
    const { undoStack, redoStack, working, selectedId } = get();
    if (!undoStack.length) return;
    const prev = undoStack[undoStack.length - 1];
    set({
      working: prev,
      undoStack: undoStack.slice(0, -1),
      redoStack: [...redoStack, working],
      docVersion: get().docVersion + 1,
      selectedId: selectedId && prev[selectedId] ? selectedId : null,
    });
  },
  redo: () => {
    const { undoStack, redoStack, working, selectedId } = get();
    if (!redoStack.length) return;
    const next = redoStack[redoStack.length - 1];
    set({
      working: next,
      redoStack: redoStack.slice(0, -1),
      undoStack: [...undoStack, working],
      docVersion: get().docVersion + 1,
      selectedId: selectedId && next[selectedId] ? selectedId : null,
    });
  },
  applySave: (res) => {
    const { server, working, undoStack, redoStack, selectedId } = get();
    const remap = (m: AnnMap): AnnMap => {
      let changed = false;
      const out: AnnMap = {};
      for (const [id, a] of Object.entries(m)) {
        const nid = res.id_map[id];
        if (nid) {
          changed = true;
          out[nid] = { ...a, id: nid };
        } else out[id] = a;
      }
      return changed ? out : m;
    };
    const newServer: AnnMap = { ...server };
    for (const id of res.deleted) delete newServer[id];
    for (const a of [...res.created, ...res.updated]) newServer[a.id] = a;
    const newWorking: AnnMap = { ...remap(working) };
    for (const a of [...res.created, ...res.updated]) newWorking[a.id] = a;
    set({
      server: newServer,
      working: newWorking,
      undoStack: undoStack.map(remap),
      redoStack: redoStack.map(remap),
      selectedId: selectedId && res.id_map[selectedId] ? res.id_map[selectedId] : selectedId,
      docVersion: get().docVersion + 1,
    });
  },
  ingest: (anns) => {
    const { server, working } = get();
    const s2 = { ...server };
    const w2 = { ...working };
    for (const a of anns) {
      if (!server[a.id]) w2[a.id] = a;
      s2[a.id] = a;
    }
    set({ server: s2, working: w2, docVersion: get().docVersion + 1 });
  },
}));

export function dirtyCount(server: AnnMap, working: AnnMap): number {
  let n = 0;
  for (const [id, w] of Object.entries(working)) if (server[id] !== w) n++;
  for (const id of Object.keys(server)) if (!working[id]) n++;
  return n;
}
