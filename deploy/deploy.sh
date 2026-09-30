#!/usr/bin/env bash
# Publica uma versão em produção. Roda NO SERVIDOR, chamado por SSH pelo job
# `publicar` do .gitlab-ci.yml (ADR-011), com o código do commit chegando
# como tar pela entrada padrão:
#
#   git archive <commit> | ssh servidor /opt/ppgm/deploy.sh <tag>
#
# PROVISÓRIO: as imagens são construídas aqui, a partir de src/, porque o
# runner ainda não constrói imagem (sem privileged). Na volta ao registry, o
# bloco "código" e o `build` saem, e entra o `docker compose pull` com o
# token do job (ver o ADR-011).
#
# Ordem da Seção 10 do CLAUDE.md: migração primeiro, depois o código novo.
set -euo pipefail

TAG="${1:?uso: git archive <commit> | deploy.sh <tag>}"
DOMINIO="ppgm.direito.ufmg.br"

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "ERRO: $(pwd)/.env não existe. Crie a partir de deploy/.env.example." >&2
    exit 1
fi

# A versão publicada fica gravada no .env, para que um `docker compose` dado
# à mão depois (restart, logs, reboot do servidor) use as mesmas imagens. Só
# é gravada no fim, com a versão nova respondendo: até lá ela vale apenas
# para este script (o export abaixo vence o .env), e um deploy que quebra no
# meio deixa o .env apontando para a versão anterior, cujas imagens existem.
grava() {
    if grep -q "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}
ANTERIOR="$(sed -n 's/^IMAGE_TAG=//p' .env)"
echo "==> publicando $TAG (anterior: ${ANTERIOR:-nenhuma})"

# Código: extrai ao lado e só então troca, para que src/ nunca fique pela
# metade se o envio for interrompido.
echo "==> código"
rm -rf src.novo && mkdir src.novo
tar -x -C src.novo
rm -rf src && mv src.novo src

echo "==> build das imagens"
export IMAGE_TAG="$TAG"
docker compose build backend web

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
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null -H "Host: $DOMINIO" -H "X-Forwarded-Proto: https" \
            "http://127.0.0.1:$PORTA/admin/login/" \
       && curl -fsS -o /dev/null "http://127.0.0.1:$PORTA/"; then
        grava IMAGE_TAG "$TAG"
        echo "==> no ar: https://$DOMINIO ($TAG)"
        # Guarda a versão atual e a anterior (para voltar rápido); o resto sai.
        # O cache de build fica limitado a uma semana, para o disco da máquina
        # compartilhada não crescer sem fim.
        docker images --format '{{.Repository}}:{{.Tag}}' \
            | grep -E '^ppgm/(backend|web):' \
            | grep -vE ":(${TAG}|${ANTERIOR:-nenhuma})$" \
            | xargs -r docker rmi >/dev/null || true
        docker image prune -f >/dev/null
        docker builder prune -f --filter until=168h >/dev/null
        exit 0
    fi
    sleep 2
done

echo "ERRO: a versão $TAG subiu mas não respondeu em 60s." >&2
docker compose ps >&2
docker compose logs --tail 50 backend web >&2
exit 1
