import { useEffect } from 'react';
import type { Ontology, Prediction } from '../api/types';
import { beatAnchors, nextAnchor, tierAccepts } from '../lib/annotations';
import { useEditor } from '../store/editor';
import { addAnnotation, deleteSelected, save } from '../store/actions';

let currentPredictions: Prediction[] = [];

export function goBeat(dir: 1 | -1): void {
  const st = useEditor.getState();
  const anchors = beatAnchors(Object.values(st.working), currentPredictions, st.annotationLead);
  const from = st.cursor ?? Math.round((st.view.start + st.view.end) / 2);
  const next = nextAnchor(anchors, from, dir);
  if (next === null) {
    st.setStatus(anchors.length ? 'No further beat in that direction' : 'No beats: add R_peak/Beat annotations or run R-peak detection');
    return;
  }
  st.setCursor(next);
  st.center(next);
}

const isTyping = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable);

export function useKeyboard(onto: Ontology | undefined, predictions: Prediction[]): void {
  currentPredictions = predictions;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const st = useEditor.getState();
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void save();
        return;
      }
      if (isTyping(e.target)) return;
      if (!st.recording) return;
      const n = st.recording.n_samples;
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) st.redo();
        else st.undo();
        return;
      }
      if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        st.redo();
        return;
      }
      if (mod) return;
      switch (e.key) {
        case 'Delete':
        case 'Backspace':
          e.preventDefault();
          deleteSelected();
          return;
        case '+':
        case '=':
          st.zoom(1 / 1.5);
          return;
        case '-':
        case '_':
          st.zoom(1.5);
          return;
        case ']':
          goBeat(1);
          return;
        case '[':
          goBeat(-1);
          return;
        case 'ArrowLeft':
        case 'ArrowRight': {
          e.preventDefault();
          const d = (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 10 : 1);
          const sel = st.selectedId ? st.working[st.selectedId] : null;
          if (e.altKey && sel) {
            const start = Math.max(0, Math.min(n - 1, sel.start_sample + d));
            const end = sel.end_sample === null ? null : Math.max(start + 1, Math.min(n, sel.end_sample + d));
            if (end === null || end - start === sel.end_sample! - sel.start_sample)
              st.commit((w) => ({ ...w, [sel.id]: { ...sel, start_sample: start, end_sample: end } }));
            return;
          }
          const c = Math.max(0, Math.min(n - 1, (st.cursor ?? st.view.start) + d));
          st.setCursor(c);
          if (c < st.view.start || c >= st.view.end) st.center(c);
          return;
        }
        case 'Enter': {
          if (!onto) return;
          const tier = onto.tiers.find((t) => t.name === st.activeTier);
          if (st.selection && tierAccepts(tier, 'interval')) addAnnotation(onto, st.activeTier, st.selection[0], st.selection[1]);
          else if (st.cursor !== null && tierAccepts(tier, 'point')) addAnnotation(onto, st.activeTier, st.cursor, null);
          else st.setStatus('Enter: place the cursor (point tiers) or select a range (interval tiers) first');
          return;
        }
        case 'Escape':
          st.setSelection(null);
          st.select(null);
          return;
        case 'v':
        case 'V':
          st.setTool('select');
          return;
        case 'a':
        case 'A':
          st.setTool('annotate');
          return;
        case 'f':
        case 'F':
          st.setView(0, n);
          return;
        case 'z':
        case 'Z':
          if (st.selection) st.setView(st.selection[0], st.selection[1]);
          return;
        default:
          if (/^[1-9]$/.test(e.key) && onto) {
            const tiers = [...onto.tiers].sort((a, b) => a.order - b.order).filter((t) => !st.hiddenTiers.includes(t.name));
            const t = tiers[Number(e.key) - 1];
            if (t) st.setActiveTier(t.name);
          }
      }
    };
    const onUnload = (e: BeforeUnloadEvent) => {
      const st = useEditor.getState();
      if (Object.keys(st.working).some((k) => st.working[k] !== st.server[k]) || Object.keys(st.server).some((k) => !st.working[k])) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('beforeunload', onUnload);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('beforeunload', onUnload);
    };
  }, [onto]);
}
