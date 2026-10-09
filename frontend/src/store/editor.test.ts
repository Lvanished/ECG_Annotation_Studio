import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dirtyCount, useEditor } from './editor';
import { addAnnotation, deleteSelected, save, updateAnnotation } from './actions';
import { ann, ONTO, resetEditor } from '../test/fixtures';

const st = useEditor.getState;

beforeEach(() => resetEditor([ann('srv-1', { start_sample: 1000 })]));
afterEach(() => vi.unstubAllGlobals());

describe('undo / redo', () => {
  it('undoes and redoes create, update and delete', () => {
    const created = addAnnotation(ONTO, 'Fiducial Points', 2000, null)!;
    expect(created.lead).toBe('II');
    updateAnnotation(created.id, { start_sample: 2010 });
    st().select('srv-1');
    deleteSelected();
    expect(Object.keys(st().working).sort()).toEqual([created.id]);
    expect(dirtyCount(st().server, st().working)).toBe(2);

    st().undo(); // delete
    expect(st().working['srv-1']).toBeDefined();
    st().undo(); // update
    expect(st().working[created.id].start_sample).toBe(2000);
    st().undo(); // create
    expect(st().working[created.id]).toBeUndefined();
    expect(dirtyCount(st().server, st().working)).toBe(0);
    st().undo(); // nothing left
    expect(Object.keys(st().working)).toEqual(['srv-1']);

    st().redo();
    st().redo();
    expect(st().working[created.id].start_sample).toBe(2010);
    st().redo();
    expect(st().working['srv-1']).toBeUndefined();
  });

  it('records a drag gesture as a single undo step', () => {
    st().beginGesture();
    for (const s of [1001, 1005, 1020]) st().live((w) => ({ ...w, 'srv-1': { ...w['srv-1'], start_sample: s } }));
    st().endGesture(true);
    expect(st().undoStack).toHaveLength(1);
    st().undo();
    expect(st().working['srv-1'].start_sample).toBe(1000);
  });

  it('drops the undo entry for a gesture that changed nothing', () => {
    st().beginGesture();
    st().endGesture(false);
    expect(st().undoStack).toHaveLength(0);
  });

  it('a new edit clears the redo stack', () => {
    updateAnnotation('srv-1', { start_sample: 1100 });
    st().undo();
    expect(st().redoStack).toHaveLength(1);
    updateAnnotation('srv-1', { start_sample: 1200 });
    expect(st().redoStack).toHaveLength(0);
  });

  it('rejects intervals that violate the tier overlap policy', () => {
    useEditor.setState({ annotationLead: 'II' });
    expect(addAnnotation(ONTO, 'QRS Complex', 100, 150)).not.toBeNull();
    expect(addAnnotation(ONTO, 'QRS Complex', 140, 180)).toBeNull();
    expect(st().status.kind).toBe('error');
    expect(addAnnotation(ONTO, 'QRS Complex', 150, 180)).not.toBeNull();
  });

  it('refuses point labels on interval tiers', () => {
    expect(addAnnotation(ONTO, 'QRS Complex', 100, null)).toBeNull();
  });
});

describe('save', () => {
  it('sends a single batch and remaps temporary ids, keeping undo history consistent', async () => {
    const created = addAnnotation(ONTO, 'Fiducial Points', 2000, null)!;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      expect(body.operations).toEqual([expect.objectContaining({ op: 'create', client_id: created.id })]);
      const saved = { ...created, id: 'srv-2', revision: 1 };
      return new Response(JSON.stringify({ batch_id: 'b1', created: [saved], updated: [], deleted: [], id_map: { [created.id]: 'srv-2' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    expect(await save(() => true)).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/recordings/rec-1/annotations/batch');
    expect(st().working['srv-2']).toBeDefined();
    expect(st().working[created.id]).toBeUndefined();
    expect(st().selectedId).toBe('srv-2');
    expect(dirtyCount(st().server, st().working)).toBe(0);
    st().undo();
    expect(st().working['srv-2']).toBeUndefined();
    st().redo();
    expect(st().working['srv-2'].start_sample).toBe(2000);
  });

  it('asks before touching reviewed annotations and flags confirmed ops', async () => {
    resetEditor([ann('rv', { start_sample: 500, review_status: 'reviewed' })]);
    updateAnnotation('rv', { start_sample: 510 });
    const fetchMock = vi.fn(async (_u: string, init: RequestInit) => {
      const op = JSON.parse(init.body as string).operations[0];
      expect(op).toMatchObject({ op: 'update', id: 'rv', confirm_reviewed_change: true });
      return new Response(JSON.stringify({ batch_id: 'b', created: [], updated: [{ ...st().working.rv, revision: 2 }], deleted: [], id_map: {} }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    expect(await save(() => false)).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await save(() => true)).toBe(true);
    expect(st().server.rv.revision).toBe(2);
  });

  it('keeps the working copy intact when the server rejects the batch', async () => {
    updateAnnotation('srv-1', { start_sample: 1500 });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'revision_conflict', message: 'stale', annotation_ids: ['srv-1'] } }), { status: 409 })),
    );
    expect(await save(() => true)).toBe(false);
    expect(st().working['srv-1'].start_sample).toBe(1500);
    expect(st().server['srv-1'].start_sample).toBe(1000);
    expect(st().status.text).toMatch(/nothing was written/);
  });
});
