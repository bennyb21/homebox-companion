import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

async function capture() {
	const source = await readFile(
		new URL('../../src/lib/workflows/capture.svelte.ts', import.meta.url),
		'utf8'
	);
	const code = ts.transpile(source.replace(/^import[\s\S]*?;\s*$/gm, ''), {
		target: ts.ScriptTarget.ES2022,
		module: ts.ModuleKind.ES2022,
	});
	const { CaptureService } = await import(
		`data:text/javascript,${encodeURIComponent('const $state = x => x; const log = {debug(){},info(){}}; const revokeImageObjectUrls = () => {};\n' + code)}`
	);
	return new CaptureService();
}
const photo = (name) => ({
	file: new File([name], name),
	dataUrl: `blob:${name}`,
	separateItems: false,
	extraInstructions: '',
	entity_type_id: '__auto__',
});

test('regrouping additional photos never duplicates a primary asset ID', async () => {
	const service = await capture();
	service.addImage({
		...photo('front'),
		assetId: '0007',
		additionalFiles: [photo('label').file],
		additionalDataUrls: ['blob:label'],
	});
	service.setOneItemPerPhoto(true);
	assert.equal(service.images[0].assetId, '0007');
	assert.equal(service.images[1].assetId, null);
});

test('new captures combine every selected photo, and regroup without losing bytes or order', async () => {
	const service = await capture();
	const photos = ['front', 'back', 'label'].map(photo);
	for (const image of photos) service.addImage(image);
	assert.equal(service.oneItemPerPhoto, false);
	assert.equal(service.images.length, 1);
	assert.deepEqual(
		[service.images[0].file, ...service.images[0].additionalFiles],
		photos.map((p) => p.file)
	);
	service.setOneItemPerPhoto(true);
	assert.deepEqual(
		service.images.map((p) => p.file),
		photos.map((p) => p.file)
	);
	assert.ok(service.images.every((p) => !p.separateItems && !p.additionalFiles?.length));
	service.setOneItemPerPhoto(false);
	assert.equal(service.images.length, 1);
	assert.deepEqual(
		[service.images[0].file, ...service.images[0].additionalFiles],
		photos.map((p) => p.file)
	);
});
