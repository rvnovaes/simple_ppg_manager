# ADR-006: Django Admin só para sysadmin; usuário de negócio sempre no front

- **Data**: 2026-07-30
- **Status**: aceito
- **Substitui**: a orientação da Seção 2 de "tentar o Admin primeiro para
  tela de operador interno mantendo cadastro"

## Contexto

A decisão original usava o Django Admin como atalho: telas internas de
cadastro da secretaria sairiam de graça, sem escrever formulário nem
endpoint, poupando um time iniciante em desenvolvimento. O raciocínio de
economia estava certo; o efeito colateral não foi medido.

Dois problemas apareceram ao montar a primeira fatia vertical.

O primeiro é técnico e mais grave que o de UX: **o Admin desvia do
domínio**. Ele edita campos direto. No Admin, arquivar uma pessoa é
trocar `status` para `archived` num `<select>` — `Person.archive()` nunca
é chamado, e o invariante que ele protege (não arquivar duas vezes) não
existe naquele caminho. O mesmo vale para qualquer regra futura. São duas
portas para o mesmo dado, e uma delas ignora as regras do model. Isso
torna a regra de negócio uma sugestão, não uma garantia — o oposto do que
o ADR-002 estabelece.

O segundo é de produto: a diferença de linguagem visual entre o Admin e o
frontend faz o usuário não-técnico perceber **dois sistemas** em vez de
um. Secretaria, coordenação, docentes e discentes são todos usuários do
mesmo produto e precisam de uma experiência só.

Some-se que a escrita feita pelo Admin hoje não gera `AuditLog`, o que
contraria a Seção 3.

## Decisão

O Django Admin é ferramenta de **operação da plataforma**, restrita a
superusuários (sysadmins).

No Admin: criar programas (novos tenants), ler a auditoria e corrigir
dados quando o sistema errou. Correção é quebra-vidro, não rotina, e é
sempre auditada.

Todo o resto — qualquer tela usada por alguém do programa — é **tela
Svelte**, com endpoint, schema, permissão e auditoria. Não existe
encaminhar usuário de negócio para o Admin.

A restrição é de código, não de combinado: `admin.site.has_permission`
exige `is_superuser`. `is_staff` sozinho não abre a porta. Papel de
domínio é Group e nunca recebe `is_staff` nem `is_superuser`.

## Consequências

- A regra de negócio volta a ser garantia: existe um caminho só para
  escrever dado de negócio, e ele passa pelo model.
- Usuário final vê um produto só.
- **Entidade nova fica cara.** Onde antes bastava um `ModelAdmin` de três
  linhas, agora é uma fatia vertical inteira: model, schema, service se
  precisar, router com permissão e auditoria, tipos e tela. A estimativa
  de ~6 arquivos da Seção 6 continua valendo para campo novo em entidade
  existente, não para entidade nova.
- **Há um período de desconforto deliberado.** A secretaria fica sem
  ferramenta para o que ainda não tem tela, e o pedido passa por um
  sysadmin. Isso é pressão para construir o front, e não para acomodar o
  desvio. Reabrir o Admin "temporariamente" é justamente o que este ADR
  proíbe.
- Auditar a escrita no Admin passa a ser obrigatório e prioritário: quem
  escreve por lá tem poder total e desvia das regras do model.
- Reabrir exige ADR novo. Argumento de prazo não basta — o custo aqui é
  de correção e de confiança no dado, não de velocidade.
