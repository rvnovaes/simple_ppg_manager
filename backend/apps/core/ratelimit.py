"""Limite de tentativas por IP — helper único do projeto.

Existe por causa das rotas públicas: onde não há sessão, não há conta para
responsabilizar, e o AuditLog sozinho registra o abuso depois de ele
acontecer. Rota autenticada não usa isto.

O contador vive no cache do Django. Com o cache local por processo (o
padrão em dev) o limite é por worker do gunicorn, e não global — é o
suficiente para frear script ingênuo, e o dia em que precisar ser exato o
caminho é configurar CACHES para Redis, sem tocar em quem chama.
"""

from django.core.cache import cache
from django.http import HttpRequest

from .exceptions import TooManyRequests


def client_ip(request: HttpRequest) -> str:
    """IP de quem chamou.

    `X-Real-IP` vem antes de `REMOTE_ADDR` porque atrás do Nginx da origem
    única (ADR-004) o segundo é sempre o IP do próprio proxy — todo mundo
    dividiria o mesmo contador. O header é confiável aqui justamente
    porque o nosso Nginx o SOBRESCREVE a cada requisição
    (`nginx/proxy_headers.conf`); nunca leia daí em deploy sem proxy.
    """
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def enforce_rate_limit(
    request: HttpRequest, *, scope: str, limit: int, window_seconds: int
) -> None:
    """Deixa passar até `limit` chamadas por IP na janela, e recusa o resto.

    Levanta TooManyRequests (429), traduzida pelo handler central como
    qualquer outro erro de negócio.
    """
    chave = f"ratelimit:{scope}:{client_ip(request)}"
    # add() só cria quando não existe: é ele que inicia a janela sem
    # reiniciá-la a cada chamada.
    cache.add(chave, 0, window_seconds)
    try:
        usos = cache.incr(chave)
    except ValueError:
        # A chave expirou entre o add e o incr. Recomeça a janela.
        cache.set(chave, 1, window_seconds)
        usos = 1

    if usos > limit:
        raise TooManyRequests(
            "Muitas tentativas a partir deste endereço. Tente mais tarde."
        )
