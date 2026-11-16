import { detectLocale, translate, type Locale, type MessageKey, type Params } from './messages';
export { detectLocale, type Locale, type MessageKey } from './messages';
export const UI_LANGUAGE_KEY = 'hbc.ui-language';

function initialLocale(): Locale {
	if (typeof window === 'undefined') return 'en';
	let stored: string | null = null;
	try {
		stored = window.localStorage.getItem(UI_LANGUAGE_KEY);
	} catch {
		/* Private/storage-blocked browsers still work. */
	}
	return detectLocale(
		navigator.languages?.length ? navigator.languages : [navigator.language],
		stored
	);
}

const state = $state({ locale: initialLocale() });
export const uiLanguage = {
	get current() {
		return state.locale;
	},
};

/** Only browser UI state. No workflow/settings API, reload, or remount. */
export function setUiLanguage(locale: Locale): boolean {
	state.locale = locale;
	if (typeof document !== 'undefined') document.documentElement.lang = locale;
	try {
		if (typeof window !== 'undefined') window.localStorage.setItem(UI_LANGUAGE_KEY, locale);
		return true;
	} catch {
		return false;
	}
}

export function initializeUiLanguage(): void {
	if (typeof document !== 'undefined') document.documentElement.lang = state.locale;
}

export function t(key: MessageKey, params?: Params): string {
	return translate(state.locale, key, params);
}
