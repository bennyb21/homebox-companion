import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import { i18nModuleUrl } from '../i18n.js';
const source = await readFile(new URL('../../src/lib/api/research.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(
	source.replace("'$lib/i18n/index.svelte'", JSON.stringify(i18nModuleUrl)),
	{
		target: ts.ScriptTarget.ES2022,
		module: ts.ModuleKind.ES2022,
	}
);
const { researchOutcome } = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);

test('legacy failed status uses additive diagnostic for incomplete and refusal', () => {
	assert.match(
		researchOutcome('failed', { code: 'response_incomplete', stage: 'response' }),
		/Research incomplete/
	);
	assert.match(
		researchOutcome('failed', { code: 'response_refused', stage: 'response' }),
		/provider declined/
	);
});
test('unknown outcomes cannot become safe to repeat because of a diagnostic', () => {
	assert.match(
		researchOutcome('unknown_outcome', { code: 'response_incomplete', stage: 'response' }),
		/may already have incurred costs/
	);
});
test('legacy failures do not invent a key or quota cause', () => {
	assert.match(researchOutcome('failed'), /cause is unknown/);
});
