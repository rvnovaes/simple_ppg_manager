// SPA pura: nada de renderização no servidor, nada de processo Node em
// produção (ADR-005). O build sai como arquivos estáticos.
export const ssr = false;
export const prerender = false;
