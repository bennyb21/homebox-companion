/** Fit research prose to its content; retain scrolling for very long text. */
export function autosize(node: HTMLTextAreaElement, _value: string) {
	function resize() {
		node.style.height = 'auto';
		node.style.height = `${node.scrollHeight}px`;
	}
	let width = 0;
	const observer = new ResizeObserver(() => {
		if (node.clientWidth !== width) {
			width = node.clientWidth;
			resize();
		}
	});
	observer.observe(node);
	queueMicrotask(resize);
	return {
		update(_value: string) {
			queueMicrotask(resize);
		},
		destroy() {
			observer.disconnect();
		},
	};
}
