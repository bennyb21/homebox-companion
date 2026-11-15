/**
 * CaptureService - Manages image capture state and operations
 *
 * Responsibilities:
 * - Image collection management (add, remove, update, clear)
 * - Additional images per capture (multi-angle shots)
 * - Image options (separateItems, extraInstructions)
 */

import { workflowLogger as log } from '$lib/utils/logger';
import { revokeImageObjectUrls } from '$lib/services/serialize';
import type { CapturedImage } from '$lib/types';

// =============================================================================
// CAPTURE SERVICE CLASS
// =============================================================================

export class CaptureService {
	/** Captured images ready for analysis */
	images = $state<CapturedImage[]>([]);

	// =========================================================================
	// IMAGE OPERATIONS
	// =========================================================================

	oneItemPerPhoto = $state(false);

	/** Regroup only photos, never inferred objects. Files and preview URLs remain intact. */
	setOneItemPerPhoto(value: boolean): void {
		const photos = this.images.flatMap((image) => [
			{ ...image, additionalFiles: undefined, additionalDataUrls: undefined },
			...(image.additionalFiles ?? []).map((file, index) => ({
				...image,
				file,
				assetId: null,
				dataUrl: image.additionalDataUrls?.[index] ?? '',
				additionalFiles: undefined,
				additionalDataUrls: undefined,
			})),
		]);
		this.oneItemPerPhoto = value;
		this.images = value
			? photos.map((image) => ({ ...image, separateItems: false }))
			: photos.length
				? [
						{
							...photos[0],
							separateItems: false,
							additionalFiles: photos.slice(1).map((image) => image.file),
							additionalDataUrls: photos.slice(1).map((image) => image.dataUrl),
						},
					]
				: [];
	}

	/** Add a photo in selection order to this session's grouping. */
	addImage(image: CapturedImage): void {
		if (!this.oneItemPerPhoto && this.images.length) {
			this.addAdditionalImages(
				0,
				[image.file, ...(image.additionalFiles ?? [])],
				[image.dataUrl, ...(image.additionalDataUrls ?? [])]
			);
		} else this.images = [...this.images, { ...image, separateItems: false }];
	}

	/** Remove an image by index */
	removeImage(index: number): void {
		const removedImage = this.images[index];
		if (removedImage) {
			log.debug(`Removing image at index ${index}: file="${removedImage.file.name}"`);
			// Revoke Object URLs to prevent memory leaks
			revokeImageObjectUrls(removedImage);
		}
		this.images = this.images.filter((_, i) => i !== index);
		log.info(`Image removed. Total images: ${this.images.length}`);
	}

	/** Update image options (separateItems, extraInstructions, assetId) */
	updateImageOptions(
		index: number,
		options: Partial<
			Pick<
				CapturedImage,
				'separateItems' | 'extraInstructions' | 'assetId' | 'entity_type_id' | 'template_id'
			>
		>
	): void {
		log.debug(`Updating options for image ${index}:`, options);
		this.images = this.images.map((img, i) => (i === index ? { ...img, ...options } : img));
	}

	/** Add additional images to a captured image (multi-angle shots) */
	addAdditionalImages(imageIndex: number, files: File[], dataUrls: string[]): void {
		log.debug(`Adding ${files.length} additional image(s) to image ${imageIndex}`);
		this.images = this.images.map((img, i) => {
			if (i !== imageIndex) return img;
			const newAdditionalCount = (img.additionalFiles?.length ?? 0) + files.length;
			log.info(`Image ${imageIndex} now has ${newAdditionalCount} additional image(s)`);
			return {
				...img,
				additionalFiles: [...(img.additionalFiles || []), ...files],
				additionalDataUrls: [...(img.additionalDataUrls || []), ...dataUrls],
			};
		});
	}

	/** Remove an additional image from a captured image */
	removeAdditionalImage(imageIndex: number, additionalIndex: number): void {
		log.debug(`Removing additional image ${additionalIndex} from image ${imageIndex}`);

		// Revoke Object URL for the removed additional image to prevent memory leak
		const img = this.images[imageIndex];
		if (img?.additionalDataUrls?.[additionalIndex]?.startsWith('blob:')) {
			URL.revokeObjectURL(img.additionalDataUrls[additionalIndex]);
		}

		this.images = this.images.map((img, i) => {
			if (i !== imageIndex) return img;
			return {
				...img,
				additionalFiles: img.additionalFiles?.filter((_, j) => j !== additionalIndex),
				additionalDataUrls: img.additionalDataUrls?.filter((_, j) => j !== additionalIndex),
			};
		});
	}

	/** Clear all captured images */
	clear(): void {
		log.debug(`Clearing all images (was: ${this.images.length})`);
		// Revoke all Object URLs to prevent memory leaks
		for (const image of this.images) {
			revokeImageObjectUrls(image);
		}
		this.images = [];
	}

	// =========================================================================
	// GETTERS
	// =========================================================================

	/** Check if there are any captured images */
	get hasImages(): boolean {
		return this.images.length > 0;
	}

	/** Get the count of captured images */
	get count(): number {
		return this.images.length;
	}

	/** Get an image by index */
	getImage(index: number): CapturedImage | null {
		return this.images[index] ?? null;
	}
}
