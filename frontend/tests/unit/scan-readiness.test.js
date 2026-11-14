import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

test('analyzePhotos does not report ready at URL commit before the review editor mounts', async () => {
	let ready = false;
	let release;
	const mounted = new Promise((resolve) => {
		release = resolve;
	});
	globalThis.scanReadiness = {
		expect: () => ({ toHaveURL: async () => {} }),
		fileURLToPath: () => 'synthetic.jpg',
	};
	const source = readFileSync(new URL('../browser/helpers/scan.ts', import.meta.url), 'utf8');
	const compiled = ts.transpile(
		source
			.replace(/^import[^\n]+\n/gm, '')
			.replaceAll(
				'import.meta.url',
				JSON.stringify(new URL('../browser/helpers/scan.ts', import.meta.url).href)
			),
		{ target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }
	);
	const { analyzePhotos } = await import(
		`data:text/javascript,${encodeURIComponent('const {expect,fileURLToPath} = globalThis.scanReadiness;\n' + compiled)}`
	);
	const page = {
		getByRole: () => ({ click: async () => {} }),
		getByLabel: () => ({ waitFor: () => mounted }),
	};
	const operation = analyzePhotos(page).then(() => {
		ready = true;
	});
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(ready, false, 'URL alone is not review readiness');
	release();
	await operation;
	assert.equal(ready, true);
});
