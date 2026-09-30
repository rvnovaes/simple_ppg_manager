---
title: "PPGM — Roteiro de testes por papel"
subtitle: "Teste inicial de usuários em https://ppgm.direito.ufmg.br"
date: "Setembro de 2026"
lang: pt-BR
---

# Antes de começar

**Endereço:** <https://ppgm.direito.ufmg.br>

**Senha:** a mesma para todas as contas de teste, **informada pela equipe de
desenvolvimento** (ela não fica neste documento, que é público).

Este é um **ambiente de teste**, carregado com dados fictícios do programa
PPGD. Pode clicar, salvar, deferir e indeferir à vontade: nada aqui é
definitivo, e o banco será recriado do zero antes do uso real. Pelo mesmo
motivo, **não digite dados reais** (CPF, documentos, nomes de alunos de
verdade).

**E-mails não são enviados.** Convocações e links de assinatura são gerados
normalmente, mas a mensagem fica só no registro do servidor. Se um teste
depender de receber e-mail, anote "e-mail esperado" e siga adiante.

## Como relatar um problema

Para cada coisa estranha, anote na tabela do fim do documento (ou envie em
mensagem):

1. **Conta** usada (ex.: `secretaria@ppgd.test`).
2. **Caso** deste roteiro (ex.: `SEC-04`), ou "fora do roteiro".
3. **O que fez**, passo a passo.
4. **O que esperava** e **o que aconteceu**.
5. **Captura de tela**, se possível.

Vale relatar também o que não é erro, mas confunde: rótulo que não se
entende, botão difícil de achar, mensagem que não explica o que fazer.

## Dica para testar vários papéis

O sistema guarda uma sessão por navegador. Para trocar de papel, use
**Sair** no canto da tela antes de entrar com outra conta, ou abra outra
conta numa **janela anônima** para ver dois papéis lado a lado.

# Quem é quem

| Conta | Papel | Situação preparada |
|---|---|---|
| `secretaria@ppgd.test` | Secretaria | Opera o programa: cadastros, editais, análises |
| `coordenacao@ppgd.test` | Coordenação | Acompanha tudo, sem editar |
| `comissao@ppgd.test` | Comissão de Seleção | Pode realocar vaga no processo seletivo |
| `comissao.bolsas@ppgd.test` | Comissão de Bolsas | Tem análise de barema pela metade |
| `ana.matos@ppgd.test` | Docente | Orientadora, com acerto de matrícula de orientando esperando decisão |
| `bruno.rocha@ppgd.test` | Docente | Oferta disciplina isolada, classifica candidatos |
| `nubia.prates@ppgd.test` | Docente | Preside banca do processo seletivo |
| `daniel.prado@ppgd.test` | Discente | Tem acerto de matrícula aberto |
| `renata.sarmento@ppgd.test` | Discente | Candidata a bolsa (faixa de ação afirmativa) |
| `vera.toledo@ppgd.test` | Discente | Candidata a bolsa (faixa de serviço público) |
| `isabela.fontes@externo.test` | Candidato | Requerimento de disciplina isolada em rascunho |
| `karina.belo@externo.test` | Candidato | Requerimento de disciplina isolada já deferido |

## O que cada papel vê no menu

| Menu | Secr. | Coord. | Com. Seleção | Com. Bolsas | Docente | Discente | Candidato |
|----------------------------------|:----:|:----:|:----:|:----:|:----:|:----:|:----:|
| Pessoas (professores, alunos, candidatos, administrativo, solicitações) | ✔ | ✔ | | | | | |
| Estrutura (linhas, períodos, disciplinas) | ✔ | ✔ | | | ✔ | ✔ | |
| Disciplina isolada › Análise | ✔ | | | | | | |
| Disciplina isolada › Editais | ✔ | ✔ | | | | | |
| Classificação (isolada) | | | | | ✔ | | |
| Inscrição / Acompanhamento (isolada) | | | | | | | ✔ |
| Processo seletivo (editais, bancas, inscrições, convocações, atas, resultado) | ✔ | ✔ | ✔ | | ✔ | | |
| Minhas bancas | | | | | ✔ | | |
| Acerto de matrícula › Meus acertos | | | | | | ✔ | |
| Acerto de matrícula › Orientandos | | | | | ✔ | | |
| Acerto de matrícula › Do programa | ✔ | ✔ | | | | | |
| Bolsas › Edital | ✔ | ✔ | | | | | |
| Bolsas › Análise | ✔ | ✔ | | ✔ | | | |
| Bolsas › Resultado | ✔ | ✔ | | ✔ | | ✔ | |
| Minha bolsa / Recurso da bolsa | | | | | | ✔ | |

**Teste transversal, vale para todo papel:** entre com a conta e confira se o
menu mostra **exatamente** a coluna dela nesta tabela. Item a mais é tão
importante de relatar quanto item a menos.

# Roteiros por papel

Cada caso tem um código, os passos e o **resultado esperado**. Os casos
"não deve" conferem que o sistema recusa o que aquele papel não pode fazer.

## Secretaria — `secretaria@ppgd.test`

A Secretaria opera o programa: é o papel com mais telas.

**SEC-01 — Cadastro de pessoas.** Em *Pessoas › Professores*, abra um
docente e confira os dados. Em *Pessoas › Alunos*, localize os alunos
regulares e a aluna de disciplina isolada do semestre anterior.
*Esperado:* listas preenchidas; a aluna isolada aparece com modalidade
"Isolada", separada da situação (ativo, trancado, excluído).

**SEC-02 — Incluir e editar.** Cadastre um professor fictício, salve,
reabra e altere um campo.
*Esperado:* a pessoa aparece na lista com o dado alterado.

**SEC-03 — Solicitações de acesso.** Em *Pessoas › Solicitações de acesso*,
veja se há pedidos pendentes. Se estiver vazio, faça antes o caso PUB-01
(auto-cadastro) numa janela anônima e volte.
*Esperado:* o pedido aparece e pode ser aprovado ou recusado; depois de
aprovado, a pessoa consegue entrar.

**SEC-04 — Estrutura do programa.** Em *Estrutura*, crie uma linha de
pesquisa, um período letivo e uma disciplina de teste.
*Esperado:* os três aparecem nas respectivas listas.

**SEC-05 — Edital de disciplina isolada.** Em *Disciplina isolada ›
Editais*, abra o edital 2026/2 (inscrições abertas) e confira ofertas e
datas.
*Esperado:* edital com janela de inscrição aberta e as ofertas das
disciplinas.

**SEC-06 — Análise de requerimentos de isolada.** Em *Disciplina isolada ›
Análise*, percorra os requerimentos. Há um em cada situação (enviado,
deferido, indeferido, matriculado). Abra um **enviado**, baixe um anexo,
defira ou indefira informando o motivo.
*Esperado:* anexo baixa; a decisão exige motivo e muda a situação.
Requerimento de oferta ainda não classificada pelo docente deve ser
recusado com aviso.

**SEC-07 — Processo seletivo: edital e vagas.** Em *Processo seletivo ›
Editais*, abra o edital publicado; confira etapas e grade de vagas.
*Esperado:* etapas e vagas por nível e linha visíveis.

**SEC-08 — Bancas.** Em *Processo seletivo › Bancas*, confira as quatro
bancas (presidente, membros, suplente), incluindo a que tem examinador
externo.
*Esperado:* composição completa; o externo aparece sem conta de acesso.

**SEC-09 — Inscrições.** Em *Processo seletivo › Inscrições*, percorra as
inscrições (há uma em cada situação) e baixe um documento de candidato.
*Esperado:* documentos baixam; a situação de cada inscrição está clara.

**SEC-10 — Convocações.** Em *Processo seletivo › Convocações*, veja o lote
da primeira etapa.
*Esperado:* cada envio aparece com seu status. (E-mail não sai deste
ambiente; confira só que o registro existe.)

**SEC-11 — Atas.** Em *Processo seletivo › Atas*, abra a ata assinada da
etapa 1 (mestrado, primeiro projeto) e baixe o PDF.
*Esperado:* PDF abre com o texto da ata e as assinaturas; quem ficou abaixo
do corte aparece eliminado.

**SEC-12 — Resultado e matrícula.** Em *Processo seletivo › Resultado*,
confira a classificação do doutorado: a primeira colocada já virou aluna;
a segunda está aprovada. Matricule a segunda.
*Esperado:* ela passa a constar em *Pessoas › Alunos*.

**SEC-13 — Acertos do programa.** Em *Acerto de matrícula › Do programa*,
confira os três acertos (aberto, aprovado, recusado) e seus motivos.
*Esperado:* lista com os três estados e as justificativas.

**SEC-14 — Bolsas: edital.** Em *Bolsas › Edital*, confira a edição do ano
passado (encerrada) e a deste ano (em análise): cronograma, barema e
comissão.
*Esperado:* a edição atual traz o barema copiado da anterior.

**SEC-15 — Bolsas: FUMP e faixa.** Em *Bolsas › Análise*, lance o nível
FUMP de um candidato e, em outro, sobrescreva a faixa.
*Esperado:* a mudança aparece na linha do candidato.

**SEC-16 — Bolsas: resultado.** Em *Bolsas › Resultado*, abra o resultado
final do ano passado e baixe o PDF.
*Esperado:* PDF com valores em reais bem formatados (ex.: `3.200,00`).

## Coordenação — `coordenacao@ppgd.test`

A Coordenação **acompanha** o programa: vê o mesmo que a Secretaria, mas
não edita.

**COO-01 — Leitura geral.** Percorra *Pessoas*, *Estrutura*, *Disciplina
isolada › Editais*, *Processo seletivo*, *Acerto de matrícula › Do
programa* e *Bolsas*.
*Esperado:* todas as telas abrem com os mesmos dados que a Secretaria vê.

**COO-02 — Não deve editar.** Nas telas acima, procure botões de incluir,
editar, deferir, publicar ou matricular.
*Esperado:* não aparecem, ou, se aparecerem, o sistema recusa a ação.
Relate qualquer ação que funcione.

**COO-03 — Não deve analisar isolada.** Confira que *Disciplina isolada ›
Análise* **não** aparece no menu.

**COO-04 — Documentos de bolsa.** Em *Bolsas › Análise*, abra um candidato
e tente ver um comprovante.
*Esperado:* a Coordenação consegue visualizar os documentos da inscrição.

## Comissão de Seleção — `comissao@ppgd.test`

**CSE-01 — Acompanhar o processo.** Percorra *Processo seletivo* (editais,
bancas, inscrições, convocações, atas, resultado).
*Esperado:* tudo em modo de leitura.

**CSE-02 — Realocar vaga.** No edital ou no resultado, localize a opção de
realocar uma vaga não preenchida para outra linha ou nível, e realoque.
*Esperado:* a realocação fica registrada e a grade de vagas muda.

**CSE-03 — Não deve.** Confira que não há opção de criar edital, montar
banca, lançar nota ou matricular.

## Comissão de Bolsas — `comissao.bolsas@ppgd.test`

**CBO-01 — Fila de análise.** Em *Bolsas › Análise*, use o filtro "somente
candidatos com itens a analisar".
*Esperado:* o filtro separa quem ainda tem itens pendentes de quem já foi
analisado por completo.

**CBO-02 — Avaliar lançamento.** Abra um candidato pendente, baixe um
comprovante e avalie cada item. Em um deles, dê nota **diferente** da do
candidato.
*Esperado:* nota divergente **exige** observação; sem ela o sistema recusa.

**CBO-03 — Comprovante faltando.** Procure o candidato com resposta "Sim"
no questionário e comprovante não enviado.
*Esperado:* o caso aparece sinalizado na fila.

**CBO-04 — Recurso julgado.** Em *Bolsas › Resultado*, na edição do ano
passado, confira o recurso deferido parcialmente e a nota refeita.
*Esperado:* o resultado final reflete a nota revista.

**CBO-05 — Não deve.** Confira que não há opção de editar o edital, o
barema ou a comissão.

## Docente — orientação: `ana.matos@ppgd.test`

**DOC-01 — Acerto de orientando.** Em *Acerto de matrícula › Orientandos*,
abra o acerto **aberto** (troca de optativa para conciliar com o estágio
docente) e decida, com justificativa.
*Esperado:* a decisão exige justificativa; o acerto sai da fila e o aluno
vê a decisão (confira depois com `daniel.prado@ppgd.test`, DIS-02).

**DOC-02 — Estrutura.** Consulte *Estrutura* (linhas, períodos,
disciplinas).
*Esperado:* só leitura.

## Docente — disciplina isolada: `bruno.rocha@ppgd.test`

**DOC-03 — Classificar candidatos.** Em *Classificação*, abra a oferta da
sua disciplina, veja os candidatos inscritos e ordene-os.
*Esperado:* a ordem é salva; candidato em rascunho não aparece para
classificação.

**DOC-04 — Efeito na Secretaria.** Depois de classificar, entre como
Secretaria e confira em *Disciplina isolada › Análise* que o requerimento
pode ser deferido.

## Docente — banca: `nubia.prates@ppgd.test`

**DOC-05 — Minhas bancas.** Em *Minhas bancas*, abra uma banca que você
preside, veja os candidatos e as notas.
*Esperado:* só as bancas de que ela participa.

**DOC-06 — Lançar nota e ata.** Numa banca com etapa em aberto, lance ou
altere uma nota; gere a ata e assine.
*Esperado:* a ata só congela com as notas lançadas; depois de assinada por
todos os titulares, a etapa fecha e quem ficou abaixo do corte é
eliminado.

**DOC-07 — Não deve.** Confira que a docente não vê *Pessoas* nem as
bancas de que não participa em *Minhas bancas*.

## Discente — `daniel.prado@ppgd.test`

**DIS-01 — Meus acertos.** Em *Acerto de matrícula › Meus acertos*, veja o
acerto aberto.
*Esperado:* situação "aberto", com as disciplinas a incluir e retirar.

**DIS-02 — Decisão do orientador.** Depois do DOC-01, volte a esta tela.
*Esperado:* a decisão e a justificativa da orientadora aparecem.

**DIS-03 — Novo acerto.** Tente abrir outro pedido de acerto.
*Esperado:* ou o sistema aceita, ou explica claramente por que não pode
haver dois abertos ao mesmo tempo.

## Discentes candidatos a bolsa — `renata.sarmento@ppgd.test` e `vera.toledo@ppgd.test`

**BOL-01 — Minha bolsa.** Em *Minha bolsa*, confira a inscrição na edição
deste ano: questionário, comprovantes e itens lançados.
*Esperado:* com a edição em análise, a inscrição aparece só para leitura.

**BOL-02 — Faixa.** Confira a faixa calculada: 2.1-I (ação afirmativa)
para Renata, 2.4-V (serviço público) para Vera.

**BOL-03 — Resultado.** Em *Bolsas › Resultado*, veja o resultado
publicado do ano passado.
*Esperado:* a lista aparece; dados de outros candidatos, se mostrados, são
só os que o edital manda publicar.

**BOL-04 — Recurso.** Em *Recurso da bolsa*, veja se há prazo aberto.
*Esperado:* com a edição atual ainda em análise, o sistema informa que não
há prazo de recurso, em vez de mostrar erro.

## Candidato a disciplina isolada — `isabela.fontes@externo.test`

**CAN-01 — Completar o rascunho.** Em *Inscrição*, abra o requerimento em
rascunho, confira a disciplina escolhida, anexe os documentos pedidos e
envie.
*Esperado:* sem todos os documentos obrigatórios o envio é recusado com
aviso claro; completo, passa a "enviado".

**CAN-02 — Acompanhamento.** Em *Acompanhamento*, confira a situação do
requerimento.
*Esperado:* "enviado", aguardando classificação e análise.

## Candidato a disciplina isolada — `karina.belo@externo.test`

**CAN-03 — Requerimento deferido.** Em *Acompanhamento*, confira o
requerimento.
*Esperado:* situação "deferido", com o motivo "Documentação completa." e a
situação do pagamento.

**CAN-04 — Não deve.** Confira que o candidato não vê *Pessoas*,
*Estrutura* nem nenhuma tela de outro papel.

# Fluxos sem login (público)

Faça numa **janela anônima**, sem estar logado.

**PUB-01 — Auto-cadastro.** Em *Cadastrar* (tela de login), crie uma conta
com e-mail fictício (ex.: `teste.seunome@exemplo.test`).
*Esperado:* a conta fica "aguardando confirmação" até a Secretaria aprovar
(SEC-03).

**PUB-02 — Inscrição no processo seletivo.** Acesse
<https://ppgm.direito.ufmg.br/selecao/inscricao>, preencha com dados
fictícios (use um CPF gerado por ferramenta de teste), anexe PDFs
quaisquer e envie.
*Esperado:* o sistema devolve um **número de protocolo**. Anexos grandes
(até 80 MB no total) devem subir.

**PUB-03 — Consulta de protocolo.** Em
<https://ppgm.direito.ufmg.br/selecao/protocolo>, consulte o protocolo do
PUB-02.
*Esperado:* a inscrição aparece com a situação atual.

**PUB-04 — Acesso indevido.** Sem login, tente abrir
<https://ppgm.direito.ufmg.br/pessoas>.
*Esperado:* o sistema leva à tela de login.

# Registro de problemas

| # | Conta | Caso | O que aconteceu | Esperado | Print? |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |
| 7 | | | | | |
| 8 | | | | | |
