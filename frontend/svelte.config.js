import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// SPA pura: o build é um punhado de arquivos estáticos servidos pelo
		// Nginx, sem processo Node em produção (ADR-005).
		adapter: adapter({
			fallback: 'index.html'
		})
	}
};

export default config;
