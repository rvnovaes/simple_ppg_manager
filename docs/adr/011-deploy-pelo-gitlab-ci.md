# ADR-011: publicar em produção pelo GitLab CI, com imagens no registry e TLS no Caddy do host

- **Data**: 2026-09-29
- **Status**: aceito

## Contexto

Até aqui o pipeline só rodava `make ready`, e publicar era a Seção 10 do
`CLAUDE.md` feita à mão. O servidor de produção,
`ppgm.direito.ufmg.br` (150.164.104.58), já existe e **é compartilhado**: roda
o QA do Gestão Legal em containers, e as portas 80/443 pertencem a um
**Caddy do host**, que termina o TLS (certificado automático) e repassa para
containers presos em `127.0.0.1`. O GitLab da faculdade (`dso.direito.ufmg.br`)
tem registry de containers habilitado no projeto e um runner com executor
docker.

## Decisão

Todo push na `main` com `make ready` verde é publicado automaticamente:

1. **construir** — o CI gera duas imagens e as publica no registry do projeto
   com a tag do commit: `backend` (gunicorn, `backend/Dockerfile.prod`) e
   `web` (Nginx + build estático do front, `nginx/Dockerfile.prod`).
2. **publicar** — o CI entra por SSH, com chave de deploy própria, e roda
   `/opt/ppgm/deploy.sh`: pull, `migrate`, `collectstatic`, subir e conferir.
   O pull usa o token do próprio job, que expira ao fim dele — o servidor não
   guarda credencial do registry.

A stack de produção (`deploy/docker-compose.yml`) tem Postgres, backend e o
Nginx da origem única (ADR-004), publicado só em `127.0.0.1:8100`. O **Caddy
do host** atende `ppgm.direito.ufmg.br` e repassa para ele. O Nginx
continua sendo quem une front e API; o TLS é que sai dele e vai para o Caddy,
porque a 80/443 do servidor já são do Caddy.

Descartados: construir as imagens no próprio servidor (máquina compartilhada
compilando front e back a cada push, e sem imagem imutável para voltar
atrás); instalar um runner no servidor (mais um serviço rodando na máquina
compartilhada, quando o runner existente alcança o servidor por SSH).

## Consequências

- Voltar uma versão é reexecutar o job `publicar` de um pipeline antigo: a
  imagem daquela tag está no registry. **A migração não volta junto** — por
  isso continua valendo que toda migração seja retrocompatível com o código
  anterior (Seção 10).
- O job `construir` usa Docker-in-Docker: o runner precisa de
  `privileged = true`.
- Por estar atrás do Caddy, o Nginx de produção **repassa** o
  `X-Forwarded-Proto` recebido (e não `$scheme`, que seria `http` e causaria
  loop com o `SECURE_SSL_REDIRECT`) e reconstrói o IP do cliente a partir do
  `X-Forwarded-For`, sem o que o rate limit veria um IP só para todo mundo.
  Por isso há um `nginx.prod.conf` e um `proxy_headers.prod.conf` separados
  dos de desenvolvimento.
- O `.env` de produção vive só no servidor, em `/opt/ppgm/.env`
  (`deploy/.env.example` é o modelo). O Caddyfile do host também fica fora do
  repositório: é configuração da máquina, compartilhada com outros sistemas.
- Backup: volumes `ppgm_pgdata` (por `pg_dump`) e `ppgm_media`.
- Reabrir se o servidor deixar de ser compartilhado (aí o Nginx pode voltar a
  terminar o TLS, como a Seção 10 descreve) ou se o registry sair do ar.
