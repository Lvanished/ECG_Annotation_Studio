/**
 * Level-of-detail chunking for long recordings. The backend serves chunks of
 * CHUNK_BUCKETS buckets; a bucket of size b holds the min/max of b consecutive
 * samples (b = 1 -> raw samples). Chunk i at bucket b covers samples
 * [i * CHUNK_BUCKETS * b, (i + 1) * CHUNK_BUCKETS * b).
 */
export const CHUNK_BUCKETS = 1024;

/** Largest power-of-two bucket not exceeding samples-per-pixel (min 1). */
export function bucketFor(spanSamples: number, widthPx: number): number {
  const spp = spanSamples / Math.max(1, widthPx);
  if (spp <= 1) return 1;
  return 2 ** Math.floor(Math.log2(spp));
}

export function chunkSpan(bucket: number): number {
  return CHUNK_BUCKETS * bucket;
}

export function chunkIndices(start: number, end: number, bucket: number, n: number, prefetch = 1): number[] {
  const cs = chunkSpan(bucket);
  const last = Math.max(0, Math.ceil(n / cs) - 1);
  const a = Math.max(0, Math.floor(start / cs) - prefetch);
  const b = Math.min(last, Math.floor(Math.max(start, end - 1) / cs) + prefetch);
  const out: number[] = [];
  for (let i = a; i <= b; i++) out.push(i);
  return out;
}
