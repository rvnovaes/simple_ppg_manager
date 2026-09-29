#!/usr/bin/env bash
# Publica uma versão em produção. Roda NO SERVIDOR, chamado por SSH pelo job
# `publicar` do .gitlab-ci.yml (ADR-011):
#
#   printf '%s' "$CI_JOB_TOKEN" | ssh servidor /opt/ppgm/deploy.sh <tag> <imagem>
#
# O token do job chega pela entrada padrão, não pela linha de comando, para
# não aparecer no `ps` do servidor. Ele só vale enquanto o job roda: serve
# para o pull e expira logo depois — o servidor não guarda credencial do
# registry.
#
# Ordem da Seção 10 do CLAUDE.md: migração primeiro, depois o código novo.
set -euo pipefail

TAG="${1:?uso: deploy.sh <tag> <imagem-do-registry>}"
REGISTRY_IMAGE="${2:?uso: deploy.sh <tag> <imagem-do-registry>}"
REGISTRY_HOST="${REGISTRY_IMAGE%%/*}"
DOMINIO="ppgm.direito.ufmg.br"

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "ERRO: $(pwd)/.env não existe. Crie a partir de deploy/.env.example." >&2
    exit 1
fi

# A versão publicada fica gravada no .env, para que um `docker compose` dado
# à mão depois (restart, logs, reboot do servidor) use as mesmas imagens.
grava() {
    if grep -q "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}
ANTERIOR="$(sed -n 's/^IMAGE_TAG=//p' .env)"
grava REGISTRY_IMAGE "$REGISTRY_IMAGE"
grava IMAGE_TAG "$TAG"
echo "==> publicando $TAG (anterior: ${ANTERIOR:-nenhuma})"

echo "==> pull das imagens"
docker login "$REGISTRY_HOST" -u gitlab-ci-token --password-stdin
trap 'docker logout "$REGISTRY_HOST" >/dev/null' EXIT
docker compose pull backend web

echo "==> banco"
docker compose up -d --wait db

echo "==> migrate (antes do código novo entrar no ar)"
docker compose run --rm backend python manage.py migrate --noinput

echo "==> collectstatic"
docker compose run --rm backend python manage.py collectstatic --noinput

echo "==> subindo a versão nova"
docker compose up -d --remove-orphans

# Fumaça: a SPA e o Django (via Nginx) respondem. Os cabeçalhos imitam o que o
# Caddy manda; sem eles o prod.py redirecionaria para https.
echo "==> conferindo"
PORTA="$(sed -n 's/^HTTP_PORT=//p' .env)"
PORTA="${PORTA:-8100}"
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null -H "Host: $DOMINIO" -H "X-Forwarded-Proto: https" \
            "http://127.0.0.1:$PORTA/admin/login/" \
       && curl -fsS -o /dev/null "http://127.0.0.1:$PORTA/"; then
        echo "==> no ar: https://$DOMINIO ($TAG)"
        docker image prune -f >/dev/null
        exit 0
    fi
    sleep 2
done

echo "ERRO: a versão $TAG subiu mas não respondeu em 60s." >&2
docker compose ps >&2
docker compose logs --tail 50 backend web >&2
exit 1
