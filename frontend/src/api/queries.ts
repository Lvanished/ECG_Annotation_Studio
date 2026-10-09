import { useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { api } from './client';
import type { Annotation, Chunk, Dataset, Ontology, PredictionRun, Recording, Snapshot } from './types';
import { chunkIndices } from '../lib/lod';

export const useDatasets = () => useQuery({ queryKey: ['datasets'], queryFn: () => api<Dataset[]>('/datasets') });

export const useRecordings = () =>
  useQuery({ queryKey: ['recordings'], queryFn: () => api<Recording[]>('/recordings') });

export const useOntology = () =>
  useQuery({ queryKey: ['ontology'], queryFn: () => api<Ontology>('/ontology'), staleTime: 60_000 });

export const fetchAnnotations = (rid: string) => api<Annotation[]>(`/recordings/${rid}/annotations`);

export const usePredictionRuns = (rid: string | undefined) =>
  useQuery({
    queryKey: ['runs', rid],
    queryFn: () => api<PredictionRun[]>(`/recordings/${rid}/prediction-runs`),
    enabled: !!rid,
  });

export const useSnapshots = () => useQuery({ queryKey: ['exports'], queryFn: () => api<Snapshot[]>('/exports') });

const chunkKey = (rid: string, leads: string[], bucket: number, index: number) =>
  ['chunk', rid, leads.join(','), bucket, index] as const;

export function useChunks(rec: Recording | null, leads: string[], start: number, end: number, bucket: number) {
  const indices = rec ? chunkIndices(start, end, bucket, rec.n_samples) : [];
  return useQueries({
    queries: indices.map((i) => ({
      queryKey: chunkKey(rec?.id ?? '', leads, bucket, i),
      queryFn: () =>
        api<Chunk>(`/recordings/${rec!.id}/chunk?bucket=${bucket}&index=${i}&leads=${encodeURIComponent(leads.join(','))}`),
      enabled: !!rec && leads.length > 0,
      staleTime: Infinity,
      gcTime: 5 * 60_000,
    })),
  });
}

/** All cached chunks for this recording and lead set (any bucket) - used as fallback while loading. */
export function cachedChunks(qc: QueryClient, rid: string, leads: string[]): Chunk[] {
  return qc
    .getQueriesData<Chunk>({ queryKey: ['chunk', rid, leads.join(',')] })
    .map(([, d]) => d)
    .filter((d): d is Chunk => !!d);
}

export { useQueryClient };
