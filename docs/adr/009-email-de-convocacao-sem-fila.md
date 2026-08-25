# ADR-009: enviar e-mail do processo seletivo pelo `django.core.mail`, sem fila

- **Data**: 2026-08-25
- **Status**: aceito

## Contexto

O processo seletivo é o primeiro módulo do sistema que **fala com gente de
fora**. São dois e-mails, e só dois:

1. **Convocação de etapa** — a secretaria seleciona os candidatos convocáveis de
   um edital × etapa e dispara em lote, com o texto do template do próprio
   edital.
2. **Link de assinatura do examinador externo** — mensagem unitária, com um
   token de uso único, para quem não tem login no sistema.

Até aqui o projeto não enviava nada: o `CLAUDE.md` registrava, na régua dos
gates, que "hoje este projeto não tem nenhum" efeito irreversível sobre
terceiro, e o corte do módulo de disciplinas isoladas foi justamente **não
enviar e-mail** — a secretaria comunica o resultado do ciclo por fora do
sistema. Aquele corte foi uma decisão de escopo daquele módulo, e **não** uma
proibição geral de SMTP; aqui a convocação precisa sair do sistema porque é ela
que carrega o horário e o local da etapa para dezenas de candidatos de uma vez,
e refazer isso à mão a cada etapa é o trabalho que o módulo existe para tirar.

A alternativa natural para envio em lote seria uma fila (Celery + Redis, ou
`django-q`). Isso significa um processo a mais para operar, um broker a mais
para monitorar e uma classe nova de bug — a tarefa que falhou em silêncio numa
fila que ninguém olha.

## Decisão

Usamos **`django.core.mail` direto, dentro do request**, sem fila, sem
agendador e sem retry automático. O backend vem de `EMAIL_BACKEND` (default:
console), e o Compose de desenvolvimento aponta para um **Mailpit** interno à
stack, que captura tudo e não entrega nada à internet.

Cada e-mail enviado vira uma linha de `ConvocationEmail` com status
(`pending`/`sent`/`failed`) e a mensagem do erro. **Falha é dado, não exceção
perdida**: o lote não aborta no primeiro erro, a tela mostra quem falhou e a
secretaria reenvia só esses. É a substituição consciente do retry automático —
quem decide reenviar é uma pessoa, que sabe se o endereço estava errado.

Descartadas: **Celery/Redis** (peça de infraestrutura nova para um lote de
dezenas de mensagens, algumas vezes por ano — ver a régua do `CLAUDE.md` sobre
menos peças móveis); **`send_mass_mail`** (uma falha derruba o lote inteiro sem
dizer qual endereço quebrou); **serviço externo com SDK próprio** (SendGrid e
afins) — se um dia for preciso, entra como relay SMTP, sem tocar no código.

## Consequências

- **Fica mais fácil**: o caminho do e-mail é um `send_mail` legível, testável
  com `locmem` (o `pytest-django` troca o backend sozinho — nenhum teste
  envia nada de verdade) e verificável no canteiro pelo Mailpit.
- **Fica mais difícil**: lote grande segura o request. O tamanho real aqui é de
  dezenas de destinatários, o que cabe folgado no timeout; se um dia um lote
  passar de poucas centenas, a tela precisa paginar o envio — ou o assunto
  reabre.
- **Não há retry**: mensagem que falhou fica `failed` até alguém reenviar. Isso
  é intencional, mas exige que a tela de convocações mostre o status com
  destaque — falha invisível é o único jeito de esse desenho dar errado.
- **`SITE_URL` passa a ser configuração obrigatória de verdade** em qualquer
  ambiente que envie e-mail: o link de assinatura é absoluto e não pode ser
  deduzido do request. Errado, o examinador externo recebe um link que não
  abre.
- **Para a infra**: em produção é preciso um relay SMTP autenticado e o domínio
  remetente com **SPF e DKIM** publicados — sem isso a convocação cai em spam,
  e o candidato perde a etapa. Alinhar `EMAIL_HOST`, `EMAIL_PORT`,
  `EMAIL_USE_TLS`, credenciais e `DEFAULT_FROM_EMAIL` no `.env` de produção.
- **Reabre o assunto**: envio que precise de agendamento (lembrete na véspera),
  volume que passe do request, ou necessidade de retry automático com
  backoff. Aí sim se discute fila — com número em mãos, não por antecipação.
