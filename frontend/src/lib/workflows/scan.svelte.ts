import { t } from '$lib/i18n/index.svelte';
/**
 * ScanWorkflow - Coordinates the entire scan-to-submit workflow
 *
 * This class acts as a facade/coordinator that:
 * - Manages overall workflow status and transitions
 * - Manages location state
 * - Delegates to specialized services for each phase
 * - Maintains backward compatibility for existing page components
 *
 * Services:
 * - CaptureService: Image management
 * - AnalysisService: AI detection
 * - ReviewService: Item review and confirmation
 * - SubmissionService: Homebox submission
 */

import { fileToDataUrl } from '$lib/services/serialize';
import { itemValidationError } from '$lib/utils/itemValidation';
import { workflowLogger as log } from '$lib/utils/logger';
import { CaptureService } from './capture.svelte';
import { AnalysisService } from './analysis.svelte';
import { ReviewService } from './review.svelte';
import { SubmissionService } from './submission.svelte';
import type {
	ScanStateView,
	DeepReadonly,
	ScanStatus,
	CapturedImage,
	ReviewItem,
	SubmissionResult,
	ImageAnalysisStatus,
} from '$lib/types';
import {
	ScanPersistence,
	captureSessionScope,
	type SessionSummary,
} from '$lib/services/scanPersistence';

// =============================================================================
// CONSTANTS
// =============================================================================

/** Debounce delay for auto-persist in milliseconds */
const AUTO_PERSIST_DEBOUNCE_MS = 1000;

// =============================================================================
// SCAN WORKFLOW CLASS
// =============================================================================

class ScanWorkflow {
	// =========================================================================
	// SERVICES
	// =========================================================================

	private captureService = new CaptureService();
	private analysisService = new AnalysisService();
	private reviewService = new ReviewService();
	private submissionService = new SubmissionService(async () => {
		if (!(await this.persistAsync()))
			throw new Error(t('Cannot safely submit: draft checkpoint failed.'));
	});
	private persistence = new ScanPersistence();

	// =========================================================================
	// WORKFLOW STATE
	// =========================================================================

	/** Current workflow status */
	private _status = $state<ScanStatus>('idle');
	visitingLocation = $state(false);
	get submissionInFlight(): boolean {
		return this.submissionService.isSubmitting;
	}
	canVisitStep(step: number): boolean {
		if (this.captureLocked || this.isAnalyzing) return false;
		if (step === 1) return !!this._locationId;
		if (step === 2) return !!this._locationId;
		if (step === 3)
			return this._status === 'reviewing' || this.reviewService.confirmedItems.length > 0;
		return (
			step === 4 &&
			(this._status === 'confirming' ||
				(this.reviewService.detectedItems.length > 0 &&
					this.reviewService.detectedItems.every((item) =>
						this.reviewService.confirmedItems.some((row) => row.reviewId === item.reviewId)
					)))
		);
	}
	async visitStep(step: number): Promise<boolean> {
		if (!this.canVisitStep(step)) return false;
		this.visitingLocation = step === 1;
		if (step === 3 && this._status !== 'reviewing') {
			const focused = this.reviewService.confirmedItems.findIndex(
				(item) => item.reviewId === this.reviewService.activeDraft?.reviewId
			);
			this.reviewService.editConfirmedItem(focused >= 0 ? focused : 0);
			this._status = 'reviewing';
		}
		if (step === 4) {
			const draft = this.reviewService.activeDraft;
			const index = this.reviewService.confirmedItems.findIndex(
				(item) => item.reviewId === draft?.reviewId
			);
			if (draft && index >= 0) this.reviewService.replaceConfirmedItem(index, draft);
			this._status = 'confirming';
		}
		await this.persistAsync();
		return true;
	}
	analysisStale = $state(false);
	legacyGrouping = $state(false);
	get oneItemPerPhoto(): boolean {
		return this.captureService.oneItemPerPhoto;
	}
	get hasAnalysisResults(): boolean {
		return (
			this.reviewService.detectedItems.length > 0 || this.reviewService.confirmedItems.length > 0
		);
	}
	get captureLocked(): boolean {
		return (
			this._status === 'submitting' ||
			this._status === 'complete' ||
			Object.keys(this.submissionService.itemStatuses).length > 0
		);
	}
	private get canChangeInputs(): boolean {
		return !this.captureLocked && !this.isAnalyzing && !this.hasAnalysisResults;
	}

	private changingInputs = false;
	/** Only called after explicit discard confirmation. Keep photos, not inferred/manual fields. */
	async discardAnalysisForInputChange(): Promise<boolean> {
		if (this.captureLocked || this.isAnalyzing || this.changingInputs) return false;
		this.changingInputs = true;
		const generation = this.contextGeneration;
		try {
			const images = this.captureService.images.map((image) => ({
				...image,
				additionalFiles: [...(image.additionalFiles ?? [])],
				additionalDataUrls: [...(image.additionalDataUrls ?? [])],
			}));
			const items = [
				...this.reviewService.detectedItems,
				...this.reviewService.confirmedItems,
				...this.reviewService.removedItems.map((entry) => entry.item),
				...(this.reviewService.activeDraft ? [this.reviewService.activeDraft] : []),
			];
			for (const [index, image] of images.entries()) {
				const existing = await Promise.all(
					[image.file, ...image.additionalFiles].map(fileToDataUrl)
				);
				for (const item of items.filter((item) => item.sourceImageIndex === index)) {
					for (const file of [
						...(item.originalFile ? [item.originalFile] : []),
						...(item.additionalImages ?? []),
					]) {
						const dataUrl = await fileToDataUrl(file);
						if (existing.includes(dataUrl)) continue;
						existing.push(dataUrl);
						image.additionalFiles.push(file);
						image.additionalDataUrls.push(dataUrl);
					}
				}
			}
			if (generation !== this.contextGeneration || this.captureLocked || this.isAnalyzing)
				return false;
			this.captureService.images = images;
			// Per-photo sessions stay per-photo even when review added an attachment.
			if (this.oneItemPerPhoto && !this.legacyGrouping) {
				this.captureService.setOneItemPerPhoto(true);
			}
			this.reviewService.reset();
			this.analysisService.clearProgress();
			this.analysisService.imageStatuses = {};
			this.analysisStale = true;
			this._status = 'capturing';
			await this.persistAsync();
			return true;
		} catch {
			this._error = t(
				'Could not preserve the review photos. Your results have not been discarded.'
			);
			return false;
		} finally {
			this.changingInputs = false;
		}
	}

	setOneItemPerPhoto(value: boolean): boolean {
		if (!this.canChangeInputs) return false;
		const images = this.captureService.images;
		// Combining conflicting manual capture options is ambiguous: never pick a winner.
		const key = (image: CapturedImage) =>
			JSON.stringify([
				image.entity_type_id,
				image.template_id,
				image.extraInstructions,
				image.assetId ?? null,
			]);
		if (
			(!value && images.some((image) => key(image) !== key(images[0]))) ||
			(value && images.some((image) => image.assetId && image.additionalFiles?.length))
		) {
			this._error = t(
				'Align capture profiles, descriptions and asset IDs before regrouping; a shared asset ID cannot be copied to multiple items.'
			);
			return false;
		}
		this.captureService.setOneItemPerPhoto(value);
		this.legacyGrouping = false;
		this.schedulePersist();
		return true;
	}

	/** Selected location ID */
	private _locationId = $state<string | null>(null);

	/** Selected location name */
	private _locationName = $state<string | null>(null);

	/** Selected location path */
	private _locationPath = $state<string | null>(null);

	/** Selected parent item ID (for sub-item relationships) */
	private _parentItemId = $state<string | null>(null);

	/** Selected parent item name */
	private _parentItemName = $state<string | null>(null);

	/** Current error message */
	private _error = $state<string | null>(null);

	/** Debounce timer for auto-persist */
	private _persistTimeout: ReturnType<typeof setTimeout> | null = null;

	/** Flag to skip the initial effect run (avoids persist on construction) */
	private _isFirstEffectRun = true;
	private contextGeneration = 0;
	/** Changes synchronously whenever an analysis is started or invalidated. */
	private _analysisAttemptId = 0;
	private retryStartStatuses: Record<number, ImageAnalysisStatus> | null = null;

	/** Confirmed-item index currently being edited after a failed submission. */
	private failedItemEditIndex = $state<number | null>(null);
	private _saveState = $state<'saving' | 'saved' | 'error'>('saved');
	private saveRevision = 0;
	private persistAttempt = 0;

	get saveState(): 'saving' | 'saved' | 'error' {
		return this._saveState;
	}

	// =========================================================================
	// CONSTRUCTOR (auto-persist setup)
	// =========================================================================

	constructor() {
		if (typeof window !== 'undefined') {
			this.setupAutoPersist();
		}
	}

	/**
	 * Setup automatic persistence using Svelte 5 effects.
	 * State changes are debounced (1s) and persisted to IndexedDB.
	 */
	private setupAutoPersist(): void {
		// Use $effect.root to create effect outside component lifecycle
		// Note: For a singleton, we don't need to store/call the cleanup function
		$effect.root(() => {
			$effect(() => {
				// == Dependency tracking ==
				// Must explicitly read all state we want to track
				const status = this._status;
				const locationId = this._locationId;
				const locationName = this._locationName;
				const locationPath = this._locationPath;
				const parentItemId = this._parentItemId;
				const parentItemName = this._parentItemName;
				const images = this.captureService.images;
				const detectedItems = this.reviewService.detectedItems;
				const confirmedItems = this.reviewService.confirmedItems;
				const currentReviewIndex = this.reviewService.currentReviewIndex;
				const imageStatuses = this.analysisService.imageStatuses;
				const isEditingFailedItem = this.failedItemEditIndex !== null;

				// DEPENDENCY TRACKING:
				// Svelte 5's $effect tracks reads automatically. The void statements below
				// ensure we re-run when these values change, even though we don't use
				// them directly in this effect body. This is necessary because:
				// 1. Array lengths - Svelte tracks array references, not lengths
				// 2. Location/parent names - we persist them but don't act on them here
				// 3. Scalar values need void to satisfy ESLint unused-vars rule
				void images.length;
				void detectedItems.length;
				void confirmedItems.length;
				void Object.keys(imageStatuses).length;
				void locationId;
				void locationName;
				void locationPath;
				void parentItemName;
				void parentItemId;
				void currentReviewIndex;
				void isEditingFailedItem;

				// Skip the very first effect run (avoids persisting on construction)
				if (this._isFirstEffectRun) {
					this._isFirstEffectRun = false;
					return;
				}

				// Don't persist terminal/transient states
				if (
					isEditingFailedItem ||
					status === 'idle' ||
					status === 'complete' ||
					status === 'analyzing' ||
					status === 'submitting'
				) {
					return;
				}

				// Schedule debounced persist
				this.schedulePersist();
			});
			const flush = () => this.flushPendingPersist();
			window.addEventListener('beforeunload', flush);
			window.addEventListener('pagehide', flush);
			return () => {
				window.removeEventListener('beforeunload', flush);
				window.removeEventListener('pagehide', flush);
				if (this._persistTimeout) clearTimeout(this._persistTimeout);
			};
		});

		// Flush pending persist on tab close.
		// NOTE: beforeunload has very limited time for async operations.
		// Modern browsers may not wait for IndexedDB writes to complete.
		// This is a best-effort attempt - critical persists should use persistAsync().
	}

	/** Schedule a debounced persist (1 second delay) */
	private schedulePersist(): void {
		this._saveState = 'saving';
		this.saveRevision++;
		if (this._persistTimeout) {
			clearTimeout(this._persistTimeout);
		}
		this._persistTimeout = setTimeout(() => {
			this._persistTimeout = null;
			void this._doPersist();
		}, AUTO_PERSIST_DEBOUNCE_MS);
	}

	/**
	 * Flush any pending persist immediately (best-effort for beforeunload).
	 *
	 * IMPORTANT: This triggers an async persist but does NOT await it.
	 * Browser may not complete IndexedDB writes during beforeunload.
	 * For guaranteed persistence, call persistAsync() at critical points
	 * (e.g., after analysis completes, before navigation).
	 */
	private flushPendingPersist(): void {
		if (this.failedItemEditIndex !== null) return;

		if (this._persistTimeout) {
			clearTimeout(this._persistTimeout);
			this._persistTimeout = null;
			// Fire-and-forget: browser may not wait for this to complete
			void this._doPersist();
		}
	}

	/** Stable state view; mutations go through workflow methods. */
	private _stateView: ScanStateView | null = null;

	get state(): ScanStateView {
		if (!this._stateView) {
			// eslint-disable-next-line @typescript-eslint/no-this-alias -- Getters read live workflow state
			const workflow = this;
			this._stateView = Object.freeze({
				get status() {
					return workflow._status;
				},
				get locationId() {
					return workflow._locationId;
				},
				get locationName() {
					return workflow._locationName;
				},
				get locationPath() {
					return workflow._locationPath;
				},
				get parentItemId() {
					return workflow._parentItemId;
				},
				get parentItemName() {
					return workflow._parentItemName;
				},
				get images() {
					return workflow.captureService.images;
				},
				get analysisProgress() {
					return workflow.analysisService.progress;
				},
				get imageStatuses() {
					return workflow.analysisService.imageStatuses;
				},
				get detectedItems() {
					return workflow.reviewService.detectedItems;
				},
				get currentReviewIndex() {
					return workflow.reviewService.currentReviewIndex;
				},
				get confirmedItems() {
					return workflow.reviewService.confirmedItems;
				},
				get submissionProgress() {
					return workflow.submissionService.progress;
				},
				get itemStatuses() {
					return workflow.submissionService.itemStatuses;
				},
				get lastSubmissionResult() {
					return workflow.submissionService.lastResult;
				},
				get submissionErrors() {
					return workflow.submissionService.lastErrors;
				},
				get error() {
					return workflow._error;
				},
			});
		}
		return this._stateView;
	}

	// =========================================================================
	// LOCATION ACTIONS
	// =========================================================================

	/** Set the selected location (clears parent item since items are location-specific) */
	setLocation(id: string, name: string, path: string): void {
		if (this.captureLocked || this.isAnalyzing) return;
		// If changing to a different location, clear parent item
		if (this._locationId !== id) {
			this._parentItemId = null;
			this._parentItemName = null;
		}
		this._locationId = id;
		this._locationName = name;
		this._locationPath = path;
		if (!this.hasAnalysisResults) this._status = 'capturing';
		this._error = null;
	}

	/** Clear location selection (also clears parent item since it's location-specific) */
	clearLocation(): void {
		if (this.captureLocked || this.isAnalyzing || this.hasAnalysisResults) return;
		this._locationId = null;
		this._locationName = null;
		this._locationPath = null;
		this._parentItemId = null;
		this._parentItemName = null;
		this._status = 'location';
	}

	/** Set the parent item (for sub-item relationships) */
	setParentItem(id: string, name: string): void {
		this._parentItemId = id;
		this._parentItemName = name;
	}

	/** Clear parent item selection */
	clearParentItem(): void {
		this._parentItemId = null;
		this._parentItemName = null;
	}

	// =========================================================================
	// IMAGE CAPTURE ACTIONS (delegated to CaptureService)
	// =========================================================================

	/** Add a captured image */
	addImage(image: CapturedImage): void {
		if (!this.canChangeInputs) return;
		this.captureService.addImage(image);
	}

	/** Remove an image by index */
	removeImage(index: number): void {
		if (!this.canChangeInputs) return;
		this.captureService.removeImage(index);
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
		if (!this.canChangeInputs) return;
		this.captureService.updateImageOptions(index, { ...options, separateItems: false });
	}

	/** Add additional images to a captured image */
	addAdditionalImages(imageIndex: number, files: File[], dataUrls: string[]): void {
		if (!this.canChangeInputs) return;
		if (this.oneItemPerPhoto) {
			const source = this.captureService.images[imageIndex];
			if (!source) return;
			files.forEach((file, index) =>
				this.captureService.addImage({
					...source,
					file,
					dataUrl: dataUrls[index],
					assetId: null,
					additionalFiles: undefined,
					additionalDataUrls: undefined,
				})
			);
		} else this.captureService.addAdditionalImages(imageIndex, files, dataUrls);
	}

	/** Remove an additional image */
	removeAdditionalImage(imageIndex: number, additionalIndex: number): void {
		if (!this.canChangeInputs) return;
		this.captureService.removeAdditionalImage(imageIndex, additionalIndex);
	}

	/** Clear all captured images */
	clearImages(): void {
		if (!this.canChangeInputs) return;
		this.captureService.clear();
	}

	// =========================================================================
	// ANALYSIS (delegated to AnalysisService)
	// =========================================================================

	/** Start image analysis - coordinates with AnalysisService */
	async startAnalysis(): Promise<void> {
		log.info('ScanWorkflow.startAnalysis() called');
		if (this.captureLocked || this.hasAnalysisResults) return;

		// Prevent starting a new analysis if one is already in progress
		if (this._status === 'analyzing') {
			log.warn('Analysis already in progress (status check), ignoring duplicate request');
			this._error = t('Analysis already in progress');
			return;
		}

		if (!this.captureService.hasImages) {
			log.warn('No images to analyze, returning early');
			this._error = 'Please add at least one image';
			return;
		}

		log.info(`Starting analysis for ${this.captureService.count} image(s)`);
		const attemptId = ++this._analysisAttemptId;
		const generation = this.contextGeneration;
		this.retryStartStatuses = null;

		// Set status BEFORE any async operations to prevent duplicate triggers
		this._status = 'analyzing';
		this._error = null;
		log.debug('Status set to "analyzing", delegating to AnalysisService');

		const result = await this.analysisService.analyze(this.captureService.images);

		// Check if cancelled (status may have changed)
		if (
			attemptId !== this._analysisAttemptId ||
			generation !== this.contextGeneration ||
			this._status !== 'analyzing' ||
			result.cancelled
		) {
			log.debug('Analysis was cancelled or status changed during processing');
			return;
		}

		if (result.success) {
			this.analysisStale = false;
			this.reviewService.setDetectedItems(result.items);

			// Check if there were partial failures
			if (result.failedCount > 0) {
				this._status = 'partial_analysis';
				log.warn(
					`Analysis complete with partial failures: ${result.items.length} items detected, ${result.failedCount} image(s) failed`
				);
			} else {
				this._status = 'reviewing';
				log.info(
					`Analysis complete! Detected ${result.items.length} item(s), transitioning to review`
				);
			}
		} else {
			this._error = result.error || t('Analysis failed');
			this._status = 'capturing';
			log.error(`Analysis failed: ${this._error}, returning to capture mode`);
		}

		// Persist after analysis completes (success or partial)
		// IMPORTANT: Await persist to ensure data is saved before user can close tab
		if (this._status !== 'capturing') {
			await this.persistAsync();
		}
	}

	/** Retry analysis for failed images only */
	async retryFailedAnalysis(): Promise<void> {
		log.info('ScanWorkflow.retryFailedAnalysis() called');

		if (this._status !== 'partial_analysis') {
			log.warn('Not in partial_analysis state, ignoring retry request');
			return;
		}

		if (!this.analysisService.hasFailedImages()) {
			log.warn('No failed images to retry');
			await this.continueWithSuccessful();
			return;
		}

		log.info(`Retrying ${this.analysisService.failedCount} failed image(s)`);
		const attemptId = ++this._analysisAttemptId;
		const generation = this.contextGeneration;
		this.retryStartStatuses = { ...this.analysisService.imageStatuses };

		// Set status to analyzing
		this._status = 'analyzing';
		this._error = null;

		// Get existing items
		const existingItems = this.reviewService.detectedItems;

		// Retry failed images
		const result = await this.analysisService.retryFailed(
			this.captureService.images,
			existingItems
		);

		// Check if cancelled (status may have changed)
		if (
			attemptId !== this._analysisAttemptId ||
			generation !== this.contextGeneration ||
			this._status !== 'analyzing' ||
			result.cancelled
		) {
			log.debug('Retry was cancelled or status changed during processing');
			return;
		}

		if (result.success) {
			this.analysisStale = false;
			this.reviewService.setDetectedItems(result.items);

			// Check if there are still failures
			if (result.failedCount > 0) {
				this._status = 'partial_analysis';
				log.warn(
					`Retry complete with remaining failures: ${result.items.length} total items, ${result.failedCount} image(s) still failed`
				);
			} else {
				this._status = 'reviewing';
				log.info(
					`Retry complete! All images successfully analyzed, ${result.items.length} total item(s)`
				);
			}
		} else {
			// If retry completely failed, go back to partial_analysis state
			this._error = result.error || t('Retry failed');
			this._status = 'partial_analysis';
			log.error(`Retry failed: ${this._error}`);
		}

		this.retryStartStatuses = null;
		// Persist after retry completes
		// IMPORTANT: Await persist to ensure data is saved before user can close tab
		await this.persistAsync();
	}

	/** Continue to review with only successfully analyzed items */
	async continueWithSuccessful(): Promise<void> {
		log.info('ScanWorkflow.continueWithSuccessful() called');

		if (this._status !== 'partial_analysis') {
			log.warn('Not in partial_analysis state, ignoring continue request');
			return;
		}

		const itemCount = this.reviewService.detectedItems.length;
		if (itemCount === 0) {
			log.warn('No items to review, returning to capture');
			this._error = t('No items were successfully detected');
			this._status = 'capturing';
			return;
		}

		log.info(`Continuing with ${itemCount} successfully detected item(s)`);
		this._status = 'reviewing';
		this._error = null;

		// Persist immediately after transitioning to reviewing state
		await this.persistAsync();
	}

	/** Remove failed images and continue with successful ones */
	async removeFailedImages(): Promise<void> {
		log.info('ScanWorkflow.removeFailedImages() called');

		if (this._status !== 'partial_analysis') {
			log.warn('Not in partial_analysis state, ignoring remove request');
			return;
		}

		const failedIndices = this.analysisService.getFailedIndices();
		if (failedIndices.length === 0) {
			log.warn('No failed images to remove');
			await this.continueWithSuccessful();
			return;
		}

		log.info(`Removing ${failedIndices.length} failed image(s)`);

		// Update sourceImageIndex on detected items before removing images
		// This adjusts indices so they point to the correct images after removal
		this.reviewService.updateSourceImageIndices(failedIndices);

		// Remove images in reverse order to preserve indices during removal
		for (let i = failedIndices.length - 1; i >= 0; i--) {
			const index = failedIndices[i];
			this.captureService.removeImage(index);
		}

		// Re-index imageStatuses to match new image array positions
		const oldStatuses = this.analysisService.imageStatuses;
		const newStatuses: Record<number, (typeof oldStatuses)[number]> = {};

		// Build mapping: for each old index, calculate new index after removals
		const sortedRemovedIndices = [...failedIndices].sort((a, b) => a - b);
		for (const [oldIndexStr, status] of Object.entries(oldStatuses)) {
			const oldIndex = parseInt(oldIndexStr, 10);

			// Skip failed indices (they're being removed)
			if (sortedRemovedIndices.includes(oldIndex)) continue;

			// Calculate new index: subtract count of removed indices below this one
			let newIndex = oldIndex;
			for (const removed of sortedRemovedIndices) {
				if (removed < oldIndex) {
					newIndex--;
				}
			}
			newStatuses[newIndex] = status;
		}
		this.analysisService.imageStatuses = newStatuses;

		log.info(`Removed ${failedIndices.length} failed image(s), continuing with successful items`);
		await this.continueWithSuccessful();
	}

	/** Cancel ongoing analysis */
	async cancelAnalysis(): Promise<void> {
		this._analysisAttemptId++;
		this.analysisService.cancel();
		if (this._status === 'analyzing') {
			const wasRetry = this.retryStartStatuses !== null;
			if (this.retryStartStatuses) {
				this.analysisService.imageStatuses = this.retryStartStatuses;
			}
			this.retryStartStatuses = null;
			// If we had some successful items before cancellation, go to partial_analysis
			// Otherwise go back to capturing
			if (this.reviewService.detectedItems.length > 0) {
				this._status = 'partial_analysis';
			} else {
				this._status = 'capturing';
			}
			this.analysisService.clearProgress(wasRetry);

			// Persist after cancellation to save the current state
			await this.persistAsync();
		}
	}

	/** Clear analysis progress (called when animation completes) */
	clearAnalysisProgress(expectedAttemptId?: number): void {
		if (expectedAttemptId !== undefined && expectedAttemptId !== this._analysisAttemptId) return;
		this.analysisService.clearProgress();
	}

	get analysisAttemptId(): number {
		return this._analysisAttemptId;
	}

	/** Check if analysis is in progress */
	get isAnalyzing(): boolean {
		return this._status === 'analyzing';
	}

	// =========================================================================
	// REVIEW ACTIONS (delegated to ReviewService)
	// =========================================================================

	/** Get current item being reviewed */
	get currentItem(): DeepReadonly<ReviewItem> | null {
		return this.reviewService.currentItem;
	}

	get activeReviewDraft(): DeepReadonly<ReviewItem> | null {
		return this.reviewService.activeDraft;
	}

	beginReviewDraft(): void {
		// A departing editor must not recreate an obsolete detection overlay after confirmation.
		if (this._status !== 'reviewing') return;
		this.reviewService.beginDraft();
		if (!this.isEditingFailedItem) this.schedulePersist();
	}

	updateReviewDraft(updates: Partial<ReviewItem>, identity = this.currentItem?.reviewId): void {
		if (this.reviewService.updateDraft(updates, identity) && !this.isEditingFailedItem)
			this.schedulePersist();
	}

	discardReviewDraft(): void {
		this.reviewService.discardDraft();
		if (!this.isEditingFailedItem) this.schedulePersist();
	}

	/** Update the current item being reviewed */
	updateCurrentItem(updates: Partial<ReviewItem>): void {
		this.reviewService.updateCurrentItem(updates);
	}

	/** Navigate to previous item */
	previousItem(): void {
		this.reviewService.previousItem();
	}

	/** Navigate to next item */
	nextItem(): void {
		this.reviewService.nextItem();
	}

	/** Skip current item and move to next */
	async skipItem(): Promise<void> {
		const result = this.reviewService.skipCurrentItem();
		if (result === 'empty') {
			// An empty draft stays visible; never reset it through implicit back navigation.
			this._status = 'confirming';
			await this.persistAsync();
		} else if (result === 'complete') {
			await this.finishReview();
		} else await this.persistAsync();
	}

	/** Confirm current item and move to next */
	async confirmItem(item: ReviewItem): Promise<void> {
		if (this._status !== 'reviewing' || item.reviewId !== this.currentItem?.reviewId) return;
		const validationError = itemValidationError(item);
		if (validationError) {
			this._error = validationError;
			return;
		}
		if (this.failedItemEditIndex !== null) {
			const editIndex = this.failedItemEditIndex;
			if (this.reviewService.replaceConfirmedItem(editIndex, item)) {
				this.reviewService.discardDraft();
				this.failedItemEditIndex = null;
				this._status = 'confirming';
				await this.persistAsync();
			}
			return;
		}

		const hasMore = this.reviewService.confirmCurrentItem(item);
		if (!hasMore) {
			await this.finishReview();
		} else await this.persistAsync();
	}

	/** Confirm all remaining items from current index onwards */
	async confirmAllRemainingItems(currentItemOverride?: ReviewItem): Promise<number> {
		const remaining = this.reviewService.detectedItems.slice(this.reviewService.currentReviewIndex);
		if (
			remaining.some((item, index) =>
				itemValidationError(index === 0 && currentItemOverride ? currentItemOverride : item)
			)
		) {
			this._error = t('Fix the invalid item fields before confirming.');
			return 0;
		}
		const count = this.reviewService.confirmAllRemainingItems(currentItemOverride);
		await this.finishReview();
		return count;
	}

	/** Finish review and move to confirmation */
	async finishReview(): Promise<void> {
		if (!this.reviewService.hasConfirmedItems) {
			this._error = t('Please confirm at least one item');
			return;
		}
		this._status = 'confirming';

		// Persist after moving to confirmation state
		await this.persistAsync();
	}

	/** Return to capture mode from review */
	async backToCapture(): Promise<void> {
		if (this.captureLocked || this.isAnalyzing) return;
		// Keep the review/summary checkpoint; capture displays a source preview.
		if (!this.hasAnalysisResults) this._status = 'capturing';
		this._error = null;

		// Persist the state change
		await this.persistAsync();
	}

	// =========================================================================
	// CONFIRMATION ACTIONS (delegated to ReviewService)
	// =========================================================================

	/** Remove a confirmed item */
	async removeConfirmedItem(index: number): Promise<void> {
		if (this.captureLocked || this._status !== 'confirming') return;
		this.reviewService.removeConfirmedItem(index);

		// Persist after removal
		await this.persistAsync();
	}

	get canUndoRemoval(): boolean {
		return !this.captureLocked && this.reviewService.removedItems.length > 0;
	}
	async undoRemoval(): Promise<void> {
		if (!this.canUndoRemoval) return;
		this.reviewService.undoRemoval();
		await this.persistAsync();
	}

	/** Edit a confirmed item (move back to review) */
	async editConfirmedItem(index: number): Promise<void> {
		if (this.captureLocked) return;
		const item = this.reviewService.editConfirmedItem(index);
		if (item) {
			this._status = 'reviewing';

			// Persist the state change
			await this.persistAsync();
		}
	}

	/** Open one failed submission in the existing item editor without changing list indexes. */
	async editFailedItem(index: number): Promise<void> {
		if (this.submissionService.itemStatuses[index] !== 'failed') return;

		const item = this.reviewService.stageConfirmedItemForEdit(index);
		if (!item) return;

		// The focused edit is ephemeral. Keep the last persisted summary as the
		// reload recovery point and prevent an already scheduled autosave from
		// writing the staged review state.
		if (this._persistTimeout) {
			clearTimeout(this._persistTimeout);
			this._persistTimeout = null;
		}
		this.failedItemEditIndex = index;
		this._status = 'reviewing';
	}

	/** Cancel a failed-item edit and return to the unchanged submission summary. */
	async cancelFailedItemEdit(): Promise<void> {
		if (this.failedItemEditIndex === null) return;

		this.failedItemEditIndex = null;
		this.reviewService.discardDraft();
		this._status = 'confirming';
		await this.persistAsync();
	}

	/** Whether review is currently editing an item that failed submission. */
	get isEditingFailedItem(): boolean {
		return this.failedItemEditIndex !== null;
	}

	// =========================================================================
	// SUBMISSION (delegated to SubmissionService)
	// =========================================================================

	/**
	 * Submit all confirmed items to Homebox.
	 * @param options.validateAuth - If true, validate auth token before submitting (default: true)
	 * @returns Object with success, counts, and sessionExpired flag
	 */
	async submitAll(options?: { validateAuth?: boolean }): Promise<{
		success: boolean;
		successCount: number;
		partialSuccessCount: number;
		failCount: number;
		sessionExpired: boolean;
	}> {
		const generation = this.contextGeneration;
		if (!captureSessionScope()) {
			throw new Error(t('Cannot submit without a verified Homebox context and collection'));
		}
		const items = this.reviewService.confirmedItems;

		if (items.length === 0) {
			this._error = t('No items to submit');
			return {
				success: false,
				successCount: 0,
				partialSuccessCount: 0,
				failCount: 0,
				sessionExpired: false,
			};
		}

		if (items.some((item) => itemValidationError(item))) {
			this._error = t('Fix the invalid item fields before submitting.');
			return {
				success: false,
				successCount: 0,
				partialSuccessCount: 0,
				failCount: items.length,
				sessionExpired: false,
			};
		}

		this._status = 'submitting';
		this._error = null;

		const result = await this.submissionService.submitAll(
			items,
			this._locationId,
			this._parentItemId,
			options
		);
		if (generation !== this.contextGeneration) return result;

		if (result.sessionExpired) {
			await this.persistAsync();
			return result;
		}

		// Handle results
		if (result.failCount > 0 && result.successCount === 0 && result.partialSuccessCount === 0) {
			this._error = t('All items failed to create');
			this._status = 'confirming';
		} else if (result.failCount > 0) {
			this._error = t('Created {p0} items, {p1} failed', {
				p0: result.successCount + result.partialSuccessCount,
				p1: result.failCount,
			});
			// Keep status as 'submitting' to show per-item status UI
		} else if (Object.values(this.submissionService.itemStatuses).includes('partial_success')) {
			this._error = t('Some items need attention in Homebox; the draft is retained.');
			this.submissionService.saveResult(items, this._locationName, this._locationId);
			// Keep original fields/photos and known IDs recoverable for incomplete work.
			this._status = 'confirming';
			await this.persistAsync();
			if (generation !== this.contextGeneration) return result;
			this._status = 'complete';
		} else if (result.success) {
			this.submissionService.saveResult(items, this._locationName, this._locationId);
			this._status = 'complete';
			await this.clearPersistedSession();
		}

		if (generation !== this.contextGeneration) return result;
		if (this._status !== 'complete') await this.persistAsync();
		return result;
	}

	/**
	 * Retry only failed items.
	 * @returns Object with success flag, counts, and sessionExpired flag
	 */
	async retryFailed(): Promise<{
		success: boolean;
		successCount: number;
		partialSuccessCount: number;
		failCount: number;
		sessionExpired: boolean;
	}> {
		const generation = this.contextGeneration;
		if (!captureSessionScope()) {
			throw new Error(t('Cannot submit without a verified Homebox context and collection'));
		}
		const items = this.reviewService.confirmedItems;

		if (!this.submissionService.hasFailedItems()) {
			return {
				success: true,
				successCount: 0,
				partialSuccessCount: 0,
				failCount: 0,
				sessionExpired: false,
			};
		}

		this._error = null;

		const result = await this.submissionService.retryFailed(
			items,
			this._locationId,
			this._parentItemId
		);
		if (generation !== this.contextGeneration) return result;

		if (result.sessionExpired) {
			await this.persistAsync();
			return result;
		}

		// Check if all items are now successful
		if (
			Object.keys(this.submissionService.itemStatuses).length > 0 &&
			Object.values(this.submissionService.itemStatuses).every(
				(s) => s === 'success' || s === 'partial_success'
			)
		) {
			this.submissionService.saveResult(items, this._locationName, this._locationId);
			if (Object.values(this.submissionService.itemStatuses).includes('partial_success')) {
				this._status = 'confirming';
				await this.persistAsync();
			} else await this.clearPersistedSession();
			if (generation !== this.contextGeneration) return result;
			this._status = 'complete';
		} else if (result.failCount > 0) {
			this._error = t('Retried: {p0} succeeded, {p1} still failing', {
				p0: result.successCount + result.partialSuccessCount,
				p1: result.failCount,
			});
		}

		if (generation !== this.contextGeneration) return result;
		if (this._status !== 'complete') await this.persistAsync();
		return result;
	}

	/** Check if there are any failed items */
	hasFailedItems(): boolean {
		return this.submissionService.hasFailedItems();
	}

	/** Check if all items were successfully submitted */
	allItemsSuccessful(): boolean {
		return this.submissionService.allItemsSuccessful();
	}

	// =========================================================================
	// SESSION PERSISTENCE (Crash Recovery)
	// =========================================================================

	/**
	 * Persist current workflow state to IndexedDB and wait for completion.
	 *
	 * Use this when the data MUST be saved before continuing
	 * (e.g., after analysis completes before navigation can occur).
	 */
	async persistAsync(): Promise<boolean> {
		if (this.isEditingFailedItem) return false;
		if (this._persistTimeout) {
			clearTimeout(this._persistTimeout);
			this._persistTimeout = null;
		}
		// Don't persist terminal states
		if (this._status === 'idle' || this._status === 'complete') {
			return false;
		}

		return this._doPersist();
	}

	/**
	 * Internal persist implementation - serializes and saves to IndexedDB.
	 */
	private async _doPersist(): Promise<boolean> {
		if (this.isEditingFailedItem) return false;
		// A queued autosave/pagehide flush may run after submission completes.
		// Keep the last recoverable checkpoint instead of storing a terminal draft.
		if (this._status === 'idle' || this._status === 'complete') return false;
		const attempt = ++this.persistAttempt;
		const generation = this.contextGeneration;
		const revision = this.saveRevision;
		this._saveState = 'saving';
		const saved = await this.persistence.save(
			() => ({
				status: this._status,
				oneItemPerPhoto: this.oneItemPerPhoto,
				analysisStale: this.analysisStale,
				legacyGrouping: this.legacyGrouping,
				locationId: this._locationId,
				locationName: this._locationName,
				locationPath: this._locationPath,
				parentItemId: this._parentItemId,
				parentItemName: this._parentItemName,
				images: this.captureService.images,
				detectedItems: this.reviewService.detectedItems,
				confirmedItems: this.reviewService.confirmedItems,
				removedItems: this.reviewService.removedItems,
				activeReviewDraft: this.reviewService.activeDraft ?? undefined,
				currentReviewIndex: this.reviewService.currentReviewIndex,
				imageStatuses: this.analysisService.imageStatuses,
				submission: this.submissionService.snapshot(),
			}),
			() => generation === this.contextGeneration
		);
		if (
			generation === this.contextGeneration &&
			revision === this.saveRevision &&
			attempt === this.persistAttempt
		)
			this._saveState = saved ? 'saved' : 'error';
		// A superseded/no-op save is not acknowledgement of this checkpoint.
		return saved && generation === this.contextGeneration;
	}

	/**
	 * Recover workflow state from IndexedDB.
	 * Returns true if recovery was successful.
	 */
	async recover(): Promise<boolean> {
		const scope = captureSessionScope();
		const generation = this.contextGeneration;
		if (!scope) return false;
		try {
			const session = await this.persistence.recover(
				scope,
				() => generation === this.contextGeneration
			);
			if (!session) {
				return false;
			}
			if (generation !== this.contextGeneration) return false;

			log.info(`Recovering session: status=${session.status}, images=${session.images.length}`);

			// Restore location state
			this._locationId = session.locationId;
			this._locationName = session.locationName;
			this._locationPath = session.locationPath;
			this._parentItemId = session.parentItemId;
			this._parentItemName = session.parentItemName;

			// Apply the adapter's fully hydrated image and review data.
			this.captureService.images = session.images;
			// Legacy drafts retain their exact grouping and write checkpoint until explicit regrouping.
			this.captureService.oneItemPerPhoto = session.oneItemPerPhoto ?? session.images.length > 1;
			this.legacyGrouping = session.legacyGrouping ?? session.oneItemPerPhoto === undefined;
			this.analysisStale = session.analysisStale ?? false;
			if (session.detectedItems.length > 0) {
				this.reviewService.setDetectedItems(session.detectedItems);
			}
			if (session.confirmedItems.length > 0) {
				// Restore directly without changing review navigation.
				this.reviewService.setConfirmedItems(session.confirmedItems);
			}

			// Restore review index
			if (session.currentReviewIndex > 0) {
				this.reviewService.setCurrentReviewIndex(session.currentReviewIndex);
			}
			this.reviewService.restoreDraft(session.activeReviewDraft);
			this.reviewService.removedItems = session.removedItems ?? [];
			this._saveState = 'saved';

			// Restore image statuses (for partial_analysis recovery)
			if (session.imageStatuses) {
				this.analysisService.imageStatuses = session.imageStatuses;
			}

			// Restore status - handle mid-analysis state
			if (session.submission)
				this.submissionService.restore(session.submission, session.confirmedItems);

			if (session.status === 'analyzing') {
				// If crashed during analysis, go back to capturing
				this._status = 'capturing';
			} else if (session.status === 'submitting') {
				// No request is running after recovery. Show the saved row outcomes.
				this._status = 'confirming';
			} else {
				this._status = session.status;
			}

			this._error = null;

			log.info('Session recovered successfully');
			return true;
		} catch (error) {
			// Extract meaningful error info for logging (avoids minified stack traces)
			const errorMessage = error instanceof Error ? error.message : String(error);
			const errorName = error instanceof Error ? error.name : 'Unknown';
			log.error(`Failed to recover session: [${errorName}] ${errorMessage}`);
			// Keep the on-disk recovery evidence; only explicit discard may remove it.
			return false;
		}
	}

	/**
	 * Check if a recoverable session exists.
	 */
	async hasRecoverableSession(): Promise<boolean> {
		return this.persistence.hasRecoverableSession();
	}

	/**
	 * Get summary of recoverable session for UI display.
	 */
	async getRecoverySummary(): Promise<SessionSummary | null> {
		return this.persistence.getRecoverySummary();
	}

	/**
	 * Clear the persisted session from IndexedDB.
	 */
	async clearPersistedSession(): Promise<void> {
		const scope = captureSessionScope();
		if (scope) await this.persistence.clear(scope);
	}

	// =========================================================================
	// RESET
	// =========================================================================

	/** Reset workflow to initial state */
	get submissionCheckpoint() {
		return this.submissionService.snapshot();
	}

	reset(clearPersisted = true): boolean {
		if (
			clearPersisted &&
			Object.values(this.submissionService.itemStatuses).some(
				(s) => s === 'partial_success' || s === 'creating'
			)
		) {
			if (
				!window.confirm(
					t(
						'Discard retained photos and unconfirmed upload records? Download the originals and check the known Homebox items first. This cannot undo any Homebox writes.'
					)
				)
			)
				return false;
		}
		const scope = captureSessionScope();
		this.contextGeneration++;
		this.saveRevision++;
		this._saveState = 'saved';
		// Cancel any pending debounced persist to prevent stale writes after reset
		if (this._persistTimeout) {
			clearTimeout(this._persistTimeout);
			this._persistTimeout = null;
		}
		this._analysisAttemptId++;
		this.analysisService.invalidateContext();
		this.retryStartStatuses = null;
		this.analysisService.clearProgress();
		this.captureService.clear();
		this.reviewService.reset();
		this.submissionService.reset();
		this.failedItemEditIndex = null;
		this._status = 'idle';
		this.visitingLocation = false;
		this.captureService.oneItemPerPhoto = false;
		this.analysisStale = false;
		this.legacyGrouping = false;
		this._locationId = null;
		this._locationName = null;
		this._locationPath = null;
		this._parentItemId = null;
		this._parentItemName = null;
		this._error = null;
		this.persistence.resetMetadata();
		if (clearPersisted && scope) void this.persistence.clear(scope);
		return true;
	}

	/** Drop in-memory work when changing collection while preserving the old scoped draft. */
	switchContext(): void {
		this.reset(false);
	}

	/** Start a new scan (keeps location and parent item if set) */
	startNew(): boolean {
		const locationId = this._locationId;
		const locationName = this._locationName;
		const locationPath = this._locationPath;
		const parentItemId = this._parentItemId;
		const parentItemName = this._parentItemName;

		if (!this.reset()) return false;

		if (locationId && locationName && locationPath) {
			this._locationId = locationId;
			this._locationName = locationName;
			this._locationPath = locationPath;
			this._parentItemId = parentItemId;
			this._parentItemName = parentItemName;
			this._status = 'capturing';
		} else {
			this._status = 'location';
		}
		return true;
	}

	// =========================================================================
	// HELPERS
	// =========================================================================

	/** Clear error */
	clearError(): void {
		this._error = null;
	}

	/** Get source image for a review/confirmed item */
	getSourceImage(item: Pick<ReviewItem, 'sourceImageIndex'>): DeepReadonly<CapturedImage> | null {
		return this.captureService.getImage(item.sourceImageIndex);
	}

	/** Get last submission result (preserved after workflow completion) */
	get submissionResult(): DeepReadonly<SubmissionResult> | null {
		return this.submissionService.lastResult;
	}
}

// =============================================================================
// SINGLETON EXPORT
// =============================================================================

export const scanWorkflow = new ScanWorkflow();
