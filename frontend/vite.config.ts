import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		port: 5173,
		strictPort: true,
		// O Nginx do compose alcança o Vite pelo host; sem isso o HMR não conecta.
		host: '0.0.0.0',
		hmr: { clientPort: 8080 }
	}
});
