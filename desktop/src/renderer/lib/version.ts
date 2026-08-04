// Vite injects __APP_VERSION__ at build time from desktop/package.json.
declare const __APP_VERSION__: string;

/** Current app version, sourced from package.json at build time. */
export const APP_VERSION: string = __APP_VERSION__;
