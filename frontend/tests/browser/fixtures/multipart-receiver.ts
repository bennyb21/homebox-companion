import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import type { Request, Route } from '@playwright/test';
import type { Handler } from './api';

export interface ReceivedUpload {
	url: string;
	body: Buffer;
	contentType: string;
	inspectorBody: Buffer | null;
}

type Pending = {
	request: Request;
	url: string;
	inspectorBody: Buffer | null;
	handler: Handler;
};

/** Test-only native HTTP sink, not a proxy to any upstream service. */
export class MultipartReceiver {
	readonly received: ReceivedUpload[] = [];
	private pending = new Map<string, Pending>();
	private server = createServer((request, response) => {
		void this.receive(request, response);
	});
	private listening?: Promise<number>;
	private closing?: Promise<void>;

	constructor(
		private origin: string,
		private onError: (message: string) => void
	) {
		const url = new URL(origin);
		if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.origin !== origin)
			throw new Error('Multipart fixture requires the loopback test origin');
	}

	async forward(route: Route, handler: Handler): Promise<void> {
		if (this.closing) throw new Error('Multipart receiver is closed');
		const request = route.request();
		const url = new URL(request.url());
		if (
			url.origin !== this.origin ||
			request.method() !== 'POST' ||
			!/^\/api\/items\/[^/]+\/attachments$/.test(url.pathname)
		)
			throw new Error('Unexpected multipart receiver route');
		this.listening ??= new Promise<number>((resolve, reject) => {
			this.server.once('error', reject);
			this.server.listen(0, '127.0.0.1', () => {
				const address = this.server.address();
				if (!address || typeof address === 'string') return reject(new Error('No receiver port'));
				resolve(address.port);
			});
		});
		const port = await this.listening;
		const token = `/${randomUUID()}`;
		this.pending.set(token, {
			request,
			url: request.url(),
			inspectorBody: request.postDataBuffer(),
			handler,
		});
		try {
			// WebKit's inspector omits file elements. Leave native body/headers untouched;
			// route.fetch() or replaying postDataBuffer() would send the truncated body.
			await route.continue({ url: `http://127.0.0.1:${port}${token}` });
		} catch (error) {
			this.pending.delete(token);
			throw error;
		}
	}

	private async receive(incoming: IncomingMessage, outgoing: ServerResponse): Promise<void> {
		const entry = this.pending.get(incoming.url ?? '');
		try {
			if (!entry || (incoming.headers.origin && incoming.headers.origin !== this.origin))
				throw new Error('Unknown multipart receiver request/origin');
			outgoing.setHeader('Access-Control-Allow-Origin', this.origin);
			outgoing.setHeader('Access-Control-Allow-Methods', 'POST');
			outgoing.setHeader(
				'Access-Control-Allow-Headers',
				'Content-Type, X-Companion-Request, X-Group-Id, Authorization'
			);
			if (incoming.method === 'OPTIONS') {
				outgoing.writeHead(204);
				outgoing.end();
				return;
			}
			if (incoming.method !== 'POST') throw new Error('Unexpected multipart receiver method');
			this.pending.delete(incoming.url!);
			const chunks: Buffer[] = [];
			let length = 0;
			for await (const chunk of incoming) {
				length += chunk.length;
				if (length > 8 * 1024 * 1024) throw new Error('Multipart fixture body exceeds 8 MiB');
				chunks.push(chunk);
			}
			const body = Buffer.concat(chunks);
			const contentType = incoming.headers['content-type'] ?? '';
			this.received.push({ url: entry.url, body, contentType, inspectorBody: entry.inspectorBody });
			// Keep the existing async handler API and original logical URL. Request.url()
			// may change after continue({url}); all body accessors use ONLY received bytes.
			const headers: Record<string, string> = {
				...entry.request.headers(),
				'content-type': contentType,
			};
			const receivedRequest = new Proxy(entry.request, {
				get(target, key) {
					if (key === 'url') return () => entry.url;
					if (key === 'headers') return () => ({ ...headers });
					if (key === 'allHeaders') return async () => ({ ...headers });
					if (key === 'headersArray')
						return async () => Object.entries(headers).map(([name, value]) => ({ name, value }));
					if (key === 'headerValue')
						return async (name: string) => headers[name.toLowerCase()] ?? null;
					if (key === 'postDataBuffer') return () => Buffer.from(body);
					if (key === 'postData') return () => body.toString('utf8');
					if (key === 'postDataJSON') return () => JSON.parse(body.toString('utf8'));
					const value = Reflect.get(target, key);
					return typeof value === 'function' ? value.bind(target) : value;
				},
			});
			const reply = await entry.handler(receivedRequest);
			outgoing.writeHead(reply.status, { 'content-type': reply.contentType });
			outgoing.end(reply.body);
		} catch (error) {
			this.onError(`${entry?.url ?? 'multipart receiver'}: ${String(error)}`);
			if (!outgoing.destroyed) {
				outgoing.writeHead(422, { 'content-type': 'application/json' });
				outgoing.end(JSON.stringify({ detail: 'Multipart fixture rejected request' }));
			}
		}
	}

	close(): Promise<void> {
		this.closing ??= (async () => {
			if (!this.listening) return;
			await this.listening;
			this.pending.clear();
			this.server.closeAllConnections();
			await new Promise<void>((resolve, reject) =>
				this.server.close((error) => (error ? reject(error) : resolve()))
			);
		})();
		return this.closing;
	}
}
