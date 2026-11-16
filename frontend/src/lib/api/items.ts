import { t } from '$lib/i18n/index.svelte';
/**
 * Items API endpoints
 */

import { normalizeAssetId } from '$lib/utils/assetId';
import { request, requestFormData, requestBlobUrl, type BlobUrlResult } from './client';
import { apiLogger as log } from '../utils/logger';
import type { BatchCreateRequest, BatchCreateResponse, ItemSummary } from '../types';

export type { BlobUrlResult };

export interface CreateOptions {
	signal?: AbortSignal;
}

export interface AttachmentReceipt {
	verified: true;
	entity_id: string;
	attachment_id: string;
	attempt_id: string;
	slot: string;
	original_filename: string;
	title: string;
	mime_type: string;
	byte_length: number;
	sha256: string;
}
export interface PhotoAttempt {
	slot: string;
	original_filename: string;
	attempt_id?: string;
	state: 'not_sent' | 'in_flight' | 'verified' | 'unconfirmed';
	receipt?: AttachmentReceipt;
}
export interface UploadOptions {
	signal?: AbortSignal;
	attemptId?: string;
	slot?: string;
	originalFilename?: string;
}

export interface ItemUpdateData {
	assetId?: string | null;
	name?: string;
	description?: string;
	// Add other updatable fields as needed
}

export const items = {
	list: (locationId?: string, signal?: AbortSignal) =>
		request<ItemSummary[]>(`/items${locationId ? `?location_id=${locationId}` : ''}`, { signal }),

	create: (data: BatchCreateRequest, options: CreateOptions = {}) =>
		request<BatchCreateResponse>('/items', {
			method: 'POST',
			body: JSON.stringify(data),
			signal: options.signal,
		}),

	/**
	 * Update an existing item.
	 * Used to set asset ID after creation (since asset ID cannot be set during creation).
	 */
	update: (itemId: string, data: ItemUpdateData, signal?: AbortSignal) => {
		if (data.assetId !== undefined) data = { ...data, assetId: normalizeAssetId(data.assetId) };
		log.debug(`Updating item ${itemId}:`, data);
		return request<unknown>(`/items/${itemId}`, {
			method: 'PUT',
			body: JSON.stringify(data),
			signal,
		});
	},

	uploadAttachment: (itemId: string, file: File, options: UploadOptions = {}) => {
		// Log file details for diagnostics - helps identify empty/corrupted uploads
		log.debug(`Uploading attachment: item=${itemId}, file="${file.name}", size=${file.size} bytes`);
		if (file.size === 0) {
			log.warn(`Empty file being uploaded to item ${itemId}: ${file.name}`);
		} else if (file.size < 1000) {
			log.warn(
				`Suspiciously small file being uploaded to item ${itemId}: ${file.name} (${file.size} bytes)`
			);
		}

		const formData = new FormData();
		formData.append('file', file);
		if (options.attemptId) formData.append('attempt_id', options.attemptId);
		if (options.slot) formData.append('slot', options.slot);
		if (options.originalFilename) formData.append('original_filename', options.originalFilename);
		return requestFormData<AttachmentReceipt>(`/items/${itemId}/attachments`, formData, {
			errorMessage: t('Photo upload not confirmed'),
			skipAuthRetry: true,
			signal: options.signal,
		});
	},

	/**
	 * Fetch a thumbnail image and return a blob URL with cleanup function.
	 *
	 * IMPORTANT: Call `result.revoke()` when done to avoid memory leaks.
	 *
	 * @throws {ApiError} When the server returns a non-OK response (e.g., 404 for missing thumbnail)
	 * @throws {NetworkError} When a network-level error occurs (connection, DNS, timeout)
	 */
	getThumbnail: (
		itemId: string,
		attachmentId: string,
		signal?: AbortSignal
	): Promise<BlobUrlResult> =>
		requestBlobUrl(`/items/${itemId}/attachments/${attachmentId}`, signal),

	/**
	 * Delete an item from Homebox.
	 * Used for cleanup when item creation succeeds but attachment upload fails.
	 */
	delete: (itemId: string, signal?: AbortSignal) => {
		log.debug(`Deleting item: ${itemId}`);
		return request<{ message: string }>(`/items/${itemId}`, {
			method: 'DELETE',
			signal,
		});
	},

	/**
	 * Trigger server-side label printing for an item.
	 * Requires HBOX_LABEL_MAKER_PRINT_COMMAND to be configured on the Homebox server.
	 */
	printLabel: (itemId: string, signal?: AbortSignal) => {
		log.debug(`Printing label for item: ${itemId}`);
		return request<{ message: string }>(`/items/${itemId}/print-label`, {
			method: 'POST',
			signal,
		});
	},
};
