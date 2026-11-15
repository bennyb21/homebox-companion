import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

function load(path, imports = {}) {
	const source = readFileSync(new URL(`../../src/lib/${path}`, import.meta.url), 'utf8');
	const { outputText } = ts.transpileModule(source, {
		compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
	});
	const exports = {};
	runInNewContext(outputText, {
		exports,
		require: (name) => imports[name] ?? {},
		$state: (value) => value,
	});
	return exports;
}
const { ReviewService } = load('workflows/review.svelte.ts', {
	'$lib/services/reviewEditor.svelte': load('services/reviewEditor.svelte.ts'),
});
const row = (reviewId) => ({
	reviewId,
	name: reviewId,
	quantity: 1,
	sourceImageIndex: 0,
	originalFile: new File([reviewId], `${reviewId}.png`),
	additionalImages: [new File(['label'], 'label.png')],
	custom_fields: { Code: '0007', Condition: 'Keep default' },
});
const plain = (value) => JSON.parse(JSON.stringify(value));

for (const method of ['confirmCurrentItem', 'confirmAllRemainingItems']) {
	test(`${method} applies a focused middle-row draft without reordering or losing photos`, () => {
		const review = new ReviewService();
		review.setConfirmedItems(['first', 'middle', 'last'].map(row));
		const before = [...review.confirmedItems];
		review.editConfirmedItem(1);
		review.beginDraft();
		review.updateDraft(
			{ name: 'Manual corrected', custom_fields: { Code: '0007-MANUAL', Condition: '' } },
			'middle'
		);
		const edited = review.activeDraft;
		review[method](edited);
		assert.deepEqual(plain(review.confirmedItems.map((item) => item.reviewId)), [
			'first',
			'middle',
			'last',
		]);
		assert.equal(review.confirmedItems[0], before[0]);
		assert.equal(review.confirmedItems[2], before[2]);
		assert.equal(review.confirmedItems[1].name, 'Manual corrected');
		assert.deepEqual(plain(review.confirmedItems[1].custom_fields), {
			Code: '0007-MANUAL',
			Condition: '',
		});
		assert.equal(review.confirmedItems[1].originalFile, before[1].originalFile);
		assert.equal(review.confirmedItems[1].additionalImages[0], before[1].additionalImages[0]);
		assert.equal(review.activeDraft, null);
		// A repeated bulk invocation without an override must not restore the stale detected row.
		review.confirmAllRemainingItems();
		assert.equal(review.confirmedItems[1].name, 'Manual corrected');
		assert.equal(review.confirmedCount, 3);
		review.removeConfirmedItem(1);
		review.undoRemoval();
		assert.equal(review.confirmedItems[1].name, 'Manual corrected');
		assert.equal(review.confirmedItems[1].originalFile, before[1].originalFile);
	});
}

test('bulk confirmation edits only the current existing identity and appends only new rows', () => {
	const review = new ReviewService();
	const rows = ['first', 'middle', 'last', 'new'].map(row);
	review.setDetectedItems(rows);
	review.setConfirmedItems(
		rows.slice(0, 3).map((item) => ({ ...item, name: `Saved ${item.name}` }))
	);
	review.setCurrentReviewIndex(1);
	const before = [...review.confirmedItems];
	const count = review.confirmAllRemainingItems({ ...review.currentItem, name: 'Edited middle' });
	assert.equal(count, 1); // Existing-row replacement is not a newly appended item.
	assert.deepEqual(plain(review.confirmedItems.map((item) => item.name)), [
		'Saved first',
		'Edited middle',
		'Saved last',
		'new',
	]);
	assert.equal(review.confirmedItems[0], before[0]);
	assert.equal(review.confirmedItems[2], before[2]);
	assert.equal(review.confirmAllRemainingItems(), 0);
	assert.equal(review.confirmedCount, 4);
	assert.equal(review.confirmedItems[1].name, 'Edited middle');
});

test('bulk new rows apply the override once and reject a stale identity without clearing the draft', () => {
	const review = new ReviewService();
	review.setDetectedItems(['first', 'second', 'third'].map(row));
	review.beginDraft();
	const draft = review.activeDraft;
	assert.equal(review.confirmAllRemainingItems({ ...draft, reviewId: 'stale' }), 0);
	assert.equal(review.activeDraft, draft);
	assert.equal(review.confirmedCount, 0);
	assert.equal(review.confirmAllRemainingItems({ ...draft, name: 'Manual first' }), 3);
	assert.deepEqual(plain(review.confirmedItems.map((item) => item.name)), [
		'Manual first',
		'second',
		'third',
	]);
	assert.equal(review.confirmAllRemainingItems(), 0);
	assert.equal(review.confirmedCount, 3);
});
