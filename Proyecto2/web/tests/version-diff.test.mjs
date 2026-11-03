import assert from 'node:assert/strict';
import { test } from 'node:test';
import { qualityDiff } from '../src/lib/version-diff.ts';

const version = (classes, small = 0) => ({
  quality_summary: { distinct_images_per_class: classes, small_objects_ratio: small },
});

test('el mínimo inclusivo es 300 y muestra cruces en ambos sentidos', () => {
  const diff = qualityDiff(version({ dog: 299, cat: 300 }), version({ dog: 300, cat: 299 }));
  assert.deepEqual(diff.crossed, [
    { name: 'cat', previousCount: 300, currentCount: 299, gained: false },
    { name: 'dog', previousCount: 299, currentCount: 300, gained: true },
  ]);
});

test('clases añadidas y eliminadas se comparan contra cero', () => {
  assert.deepEqual(qualityDiff(version({ cat: 300 }), version({ dog: 300 })).crossed, [
    { name: 'cat', previousCount: 300, currentCount: 0, gained: false },
    { name: 'dog', previousCount: 0, currentCount: 300, gained: true },
  ]);
});

test('sin cruces, la lista queda vacía', () => {
  assert.deepEqual(qualityDiff(version({ dog: 300 }), version({ dog: 348 })).crossed, []);
});

test('el cambio porcentual usa puntos porcentuales y conserva el signo', () => {
  const { smallObjects } = qualityDiff(version({}, 0.2), version({}, 0.1));
  assert.equal(smallObjects.before, 20);
  assert.equal(smallObjects.after, 10);
  assert.equal(smallObjects.delta, -10);
});

test('los datos ausentes no se interpretan como cero', () => {
  assert.equal(qualityDiff({}, version({ dog: 300 })), null);
  assert.equal(qualityDiff(version({}, null), version({}, 0)).smallObjects, null);
  assert.equal(qualityDiff(version({}, 0), version({}, 0)).smallObjects.delta, 0);
});
