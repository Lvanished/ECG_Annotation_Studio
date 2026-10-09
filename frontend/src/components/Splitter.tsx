interface Props {
  dir: 'x' | 'y';
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  invert?: boolean;
}

/** Drag handle that resizes an adjacent panel (value in px). */
export function Splitter({ dir, value, min, max, onChange, invert }: Props) {
  const onDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const p0 = dir === 'x' ? e.clientX : e.clientY;
    const v0 = value;
    const move = (ev: PointerEvent) => {
      const d = (dir === 'x' ? ev.clientX : ev.clientY) - p0;
      onChange(Math.max(min, Math.min(max, v0 + (invert ? -d : d))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div
      onPointerDown={onDown}
      className={`shrink-0 bg-slate-300 hover:bg-blue-400 ${dir === 'x' ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize'}`}
    />
  );
}
