import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import type { MockApi, Reply } from '../fixtures/api';

export interface Evidence {
	wire: Array<{
		method: string;
		model: string;
		endpoint: string;
		scenario?: string;
		reasoning?: unknown;
	}>;
	network_attempts: number;
	inventory_writes: number;
	api_calls: Array<{ method: string; path: string; body: Record<string, unknown> | null }>;
}

/** No fixture JSON on research/settings/test paths: forward actual browser bodies into ASGI. */
export async function researchAsgi(api: MockApi) {
	const root = path.resolve('..');
	const state = await mkdtemp(path.join(process.env.TMPDIR || tmpdir(), 'hbc-research-asgi-'));
	const child = spawn(
		path.join(root, '.venv/bin/python'),
		['-B', path.join(root, 'tests/research_browser_bridge.py'), state],
		{ env: {}, stdio: ['pipe', 'pipe', 'pipe'] }
	);
	let stderr = '';
	child.stderr.on('data', (chunk) => {
		stderr += chunk.toString();
	});
	const pending: Array<{ resolve: (value: unknown) => void; reject: (reason: Error) => void }> = [];
	const lines = createInterface({ input: child.stdout });
	lines.on('line', (line) => pending.shift()?.resolve(JSON.parse(line)));
	const exited = new Promise<number | null>((resolve) =>
		child.on('exit', (code) => {
			for (const p of pending.splice(0))
				p.reject(new Error(`ASGI bridge exited ${code}: ${stderr}`));
			resolve(code);
		})
	);
	const rpc = <T>(command: object): Promise<T> =>
		new Promise((resolve, reject) => {
			pending.push({ resolve: (v) => resolve(v as T), reject });
			child.stdin.write(JSON.stringify(command) + '\n');
		});
	for (const method of ['GET', 'POST', 'PUT', 'DELETE']) {
		api.on(
			method,
			/^\/api\/(research(?:\/|$)|settings\/research$|llm\/profiles(?:\/|$))/,
			(request) =>
				rpc<Reply>({
					method,
					path: new URL(request.url()).pathname,
					body: request.postData() ? request.postDataJSON() : null,
				})
		);
	}
	return {
		scenario: (scenario: string) => rpc({ scenario }),
		inspect: () => rpc<Evidence>({ inspect: true }),
		request: (method: string, path: string, body?: unknown) => rpc<Reply>({ method, path, body }),
		async close() {
			child.stdin.end();
			const code = await exited;
			lines.close();
			await rm(state, { recursive: true, force: true });
			if (code !== 0) throw new Error(`ASGI bridge failed ${code}: ${stderr}`);
			for (const canary of [
				'KEY-CONFIDENTIALITY-CANARY',
				'RAW-PROVIDER-CONFIDENTIALITY-CANARY',
				'QUERY-CONFIDENTIALITY-CANARY',
			]) {
				if (stderr.includes(canary)) throw new Error('Confidentiality canary in backend logs');
			}
		},
	};
}
