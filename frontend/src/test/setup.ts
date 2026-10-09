import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

// jsdom has no PointerEvent; without it pointer events lose clientX/buttons.
if (typeof window.PointerEvent === 'undefined') {
  class PE extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  (window as unknown as { PointerEvent: typeof PE }).PointerEvent = PE;
  Element.prototype.setPointerCapture = () => undefined;
  Element.prototype.releasePointerCapture = () => undefined;
}

// jsdom has no canvas implementation; provide a recording 2D context stub.
const calls: string[] = [];
(globalThis as unknown as { __canvasCalls: string[] }).__canvasCalls = calls;
const ctx = new Proxy(
  {},
  {
    get: (_t, prop: string) => {
      if (prop === 'measureText') return () => ({ width: 10 });
      if (prop === 'createLinearGradient') return () => ({ addColorStop: () => undefined });
      return (...args: unknown[]) => {
        calls.push(`${prop}(${args.length})`);
      };
    },
    set: () => true,
  },
);
HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement['getContext'];

class RO {
  cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }
  observe(el: Element) {
    this.cb([{ target: el, contentRect: { width: 1000, height: 400 } } as unknown as ResizeObserverEntry], this);
  }
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
