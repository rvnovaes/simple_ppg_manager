import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

// A porta publicada do Nginx — a que o NAVEGADOR vê. Vem do compose, que a
// recebe do .env; numa worktree é 8080 + o offset do canteiro.
const nginxPort = Number(process.env.NGINX_PORT ?? 8080);

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		// Porta INTERNA da rede do compose. Não é publicada e não colide com a de
		// outro canteiro, por isso continua fixa.
		port: 5173,
		strictPort: true,
		// Escutar em 0.0.0.0: dentro do container, `localhost` só aceitaria
		// conexão de dentro dele mesmo, e quem chega é o Nginx.
		host: '0.0.0.0',
		hmr: {
			// O WebSocket de HMR sai do navegador, então usa a porta do Nginx — não
			// a 5173, que não existe fora da rede do compose. Estava cravado em
			// 8080: todo canteiro fora dessa porta perdia o HMR em silêncio (a
			// página carrega, só não atualiza) ou o pedia ao canteiro alheio.
			clientPort: nginxPort
		}
	}
});
