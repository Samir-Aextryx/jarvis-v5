/** Reuse the pair buffer; expensive neighbor searches need not run every frame. */
export function findConnections(positions: Float32Array, stride: number, distance: number, pairs: Uint32Array): number {
  const count = positions.length / 3;
  const limit = pairs.length / 2;
  const distanceSq = distance * distance;
  let found = 0;
  for (let i = 0; i < count && found < limit; i += stride) {
    const i3 = i * 3;
    for (let j = i + stride; j < count && found < limit; j += stride) {
      const j3 = j * 3;
      const dx = positions[j3] - positions[i3];
      const dy = positions[j3 + 1] - positions[i3 + 1];
      const dz = positions[j3 + 2] - positions[i3 + 2];
      if (dx * dx + dy * dy + dz * dz < distanceSq) {
        pairs[found * 2] = i;
        pairs[found * 2 + 1] = j;
        found++;
      }
    }
  }
  return found;
}
