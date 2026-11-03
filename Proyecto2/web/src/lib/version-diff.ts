import type { DatasetVersion } from './api';

export const MIN_IMAGES = 300;

export function qualityDiff(previous: DatasetVersion, current: DatasetVersion) {
  const before = previous.quality_summary;
  const after = current.quality_summary;
  if (!before || !after) return null;
  const names = [...new Set([
    ...Object.keys(before.distinct_images_per_class),
    ...Object.keys(after.distinct_images_per_class),
  ])].sort();
  const crossed = names.flatMap((name) => {
    const previousCount = before.distinct_images_per_class[name] ?? 0;
    const currentCount = after.distinct_images_per_class[name] ?? 0;
    if ((previousCount >= MIN_IMAGES) === (currentCount >= MIN_IMAGES)) return [];
    return [{ name, previousCount, currentCount, gained: currentCount >= MIN_IMAGES }];
  });
  const smallObjects = before.small_objects_ratio != null && after.small_objects_ratio != null
    ? {
        before: before.small_objects_ratio * 100,
        after: after.small_objects_ratio * 100,
        delta: (after.small_objects_ratio - before.small_objects_ratio) * 100,
      }
    : null;
  return { crossed, smallObjects };
}
