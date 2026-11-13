import type { Page } from '@playwright/test';

/** Generated fixture only; never load inventory photos or bundled example photos. */
export async function uploadSyntheticPhoto(page: Page) {
	const data = await page.evaluate(() => {
		const canvas = document.createElement('canvas');
		canvas.width = 640;
		canvas.height = 480;
		const ctx = canvas.getContext('2d')!;
		ctx.fillStyle = '#ffffff';
		ctx.fillRect(0, 0, 640, 480);
		ctx.fillStyle = '#000000';
		ctx.font = '32px sans-serif';
		ctx.fillText('SYNTHETIC TEST ONLY', 40, 100);
		ctx.fillText('Part number: 0007-SYN-A', 40, 220);
		return canvas.toDataURL('image/png').split(',')[1];
	});
	await page
		.locator('input[type="file"]')
		.first()
		.setInputFiles({
			name: 'synthetic-part.png',
			mimeType: 'image/png',
			buffer: Buffer.from(data, 'base64'),
		});
}
