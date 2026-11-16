/** Fit research prose to its content; retain scrolling for very long text. */
export function autosize(node: HTMLTextAreaElement, _value: string) {
	let frame: number | undefined;
	function resize() {
		frame = undefined;
		node.style.height = 'auto';
		node.style.height = `${node.scrollHeight}px`;
	}
	function scheduleResize() {
		// Do not mutate geometry inside ResizeObserver delivery (WebKit loop error).
		if (frame === undefined) frame = requestAnimationFrame(resize);
	}
	let width = 0;
	const observer = new ResizeObserver(() => {
		if (node.clientWidth !== width) {
			width = node.clientWidth;
			scheduleResize();
		}
	});
	observer.observe(node);
	scheduleResize();
	return {
		update(_value: string) {
			scheduleResize();
		},
		destroy() {
			observer.disconnect();
			if (frame !== undefined) cancelAnimationFrame(frame);
		},
	};
}
