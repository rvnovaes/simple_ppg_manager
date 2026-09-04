# PPGM — Pós-Graduação Manager

Sistema de gestão para programa de pós-graduação. Nasceu para o PPGD (o
repositório e o banco ainda se chamam `ppgd-manager`), mas é multi-tenant
desde a primeira migração: todo dado de negócio carrega a chave do programa.

Backend em Django + Django Ninja, frontend em SvelteKit como SPA estática,
tudo servido por um Nginx em **uma origem só**.

> **As regras do projeto estão no [CLAUDE.md](CLAUDE.md)**, não aqui. Este
> arquivo é o "como rodar" e o "como o sistema é por dentro"; aquele é o
> "como fazer". Em caso de conflito, o CLAUDE.md vence. As decisões de
> arquitetura estão em [`docs/adr/`](docs/adr/).

Este README tem duas partes independentes. Leia a que corresponde ao seu
papel:

- **[Manual do Usuário](#manual-do-usuário)** — para quem usa o sistema:
  secretaria, coordenação, docentes, discentes, comissões e candidatos.
- **[Manual do Desenvolvedor](#manual-do-desenvolvedor)** — para quem
  escreve código.

---

# Manual do Usuário

Para quem usa o sistema: secretaria, coordenação, docentes, discentes,
comissões e candidatos — ao processo seletivo ou a disciplina isolada. Nada
aqui pressupõe conhecimento técnico.

## Sumário

- [Como entrar](#como-entrar)
- [O que cada perfil enxerga](#o-que-cada-perfil-enxerga)
- [Duas convenções que valem para o sistema inteiro](#duas-convenções-que-valem-para-o-sistema-inteiro)
- [Secretaria e coordenação](#secretaria-e-coordenação)
- [Docente](#docente)
- [Discente](#discente)
- [Candidato a disciplina isolada](#candidato-a-disciplina-isolada)
- [Processo seletivo](#processo-seletivo)
- [Bolsas](#bolsas)
- [Quando algo dá errado](#quando-algo-dá-errado)

## Como entrar

Acesse o endereço que a secretaria informou e entre com **o seu e-mail
completo** (não a parte antes do `@`) e a sua senha.

**Primeiro acesso.** Há dois caminhos, e os dois terminam na mesma conta:

- **A secretaria cadastra você.** Ela cria a pessoa e define a senha do
  primeiro acesso, que informa a você. Depois disso, a senha é sua: nem a
  secretaria pode trocá-la sozinha.
- **Você se cadastra.** Na tela de login, embaixo do botão **Entrar**,
  clique em **Cadastre-se** ("Ainda não tem conta no programa?"). Informe
  nome, e-mail, senha, o programa e o seu perfil:
  - **Candidato** (a disciplina isolada) entra na hora.
  - **Docente** e **discente** ficam em espera: a tela mostra "Aguardando a
    secretaria" até que ela confirme o vínculo. Docente informa também a
    categoria, a titulação e o Lattes; quem é de outra instituição,
    informa qual. Quando a secretaria confirma, o menu aparece completo no
    próximo acesso. Se ela recusar, a mesma tela mostra o motivo — e a
    saída é procurá-la, porque o sistema não aceita um segundo cadastro com
    o mesmo e-mail.

Só aparecem na lista os programas que aceitam autocadastro. Se o seu não
aparece, fale com a secretaria dele.

**Candidato ao processo seletivo não tem conta.** A inscrição é pública e
o acompanhamento é por protocolo — veja [Processo seletivo](#processo-seletivo).

Para sair, use o botão **Sair** no canto superior direito.

## O que cada perfil enxerga

O menu superior muda conforme o seu papel — você só vê o que pode usar.
Alguns itens abrem submenus.

| Menu                                     | Submenu                                                                 | Quem vê                                                    |
| ---------------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------- |
| **Pessoas**                              | Professores, Alunos, Candidatos, Administrativo, Solicitações de acesso | Secretaria e coordenação                                   |
| **Estrutura**                            | Linhas de Pesquisa, Períodos Letivos, Disciplinas                       | Secretaria e coordenação                                   |
| **Disciplina isolada**                   | Análise, Editais                                                        | Secretaria (análise) e coordenação (leitura)               |
| **Inscrição**, **Acompanhamento**        | —                                                                       | Candidato a disciplina isolada                             |
| **Classificação**                        | —                                                                       | Docente responsável por oferta de isolada                  |
| **Processo seletivo**                    | Editais, Bancas, Inscrições, Convocações, Atas, Resultado               | Secretaria, Comissão de Seleção e coordenação              |
| **Minhas bancas**                        | —                                                                       | Docente que compõe banca                                   |
| **Acerto de matrícula**                  | Meus acertos, Orientandos, Do programa                                  | Cada papel vê só a sua parte                               |
| **Bolsas**                               | Edital, Análise, Resultado                                              | Secretaria, Comissão de Bolsas e coordenação               |
| **Minha bolsa**, **Recurso da bolsa**    | —                                                                       | Discente                                                   |

Se um item que você espera não aparece, o motivo quase sempre é o papel da
sua conta. Fale com a secretaria — link que só levaria a uma tela negada
não é exibido de propósito.

## Duas convenções que valem para o sistema inteiro

**1. O sistema não apaga ninguém.** Onde você lê "excluir", "arquivar" ou
"descredenciar", o registro continua existindo e apenas muda de situação:

- **professor** → recebe uma data de descredenciamento;
- **aluno** → passa para a situação _Excluído_;
- **pessoa** (candidato, administrativo) → passa para _Arquivada_.

Isso é intencional. O professor descredenciado continua sendo quem
orientou os alunos dele, e o aluno desligado continua sendo quem cursou o
que cursou. Nenhum histórico se perde.

**2. Modalidade e situação são coisas separadas** no cadastro do aluno:

- **modalidade**: Regular, Isolada ou Eletiva — como a pessoa está no
  programa;
- **situação**: Ativo, Trancado ou Excluído — como está esse vínculo agora.

Um aluno pode ser _Regular_ e _Trancado_ ao mesmo tempo. Trancamento só se
aplica ao regular; isolada e eletiva duram um semestre e terminam
excluídas.

**Os três botões das listagens.** Em Professores, Alunos, Candidatos e
Administrativo, cada linha traz até três ícones à direita:

| Ícone | O que faz                                                   |
| ----- | ----------------------------------------------------------- |
| 👁     | abre a página de detalhes, com todos os dados do registro   |
| ✏️    | abre o formulário de edição, na própria lista               |
| 🗄     | desativa (arquiva, descredencia ou exclui, conforme o caso) |

Quando o registro já está desativado, o terceiro botão aparece
desabilitado — passe o mouse para ver o motivo.

## Secretaria e coordenação

A secretaria opera; a coordenação acompanha, em geral apenas lendo.

### Estrutura do programa

Menu **Estrutura**. É a base de tudo, e costuma ser o primeiro cadastro do
semestre:

- **Linhas de pesquisa** — agrupam os projetos.
- **Projetos coletivos** — pertencem a uma linha; é o projeto que
  professores e alunos citam no vínculo.
- **Períodos letivos** — o semestre, escrito sempre como `2026/1`. O
  período é da instituição inteira, não do programa: o mesmo `2026/1` vale
  para todos os cursos.

Linhas e projetos podem ser **desativados** em vez de apagados; quem já se
vinculou a eles continua vinculado.

### Catálogo de disciplinas

Menu **Disciplinas**. Cada disciplina tem código (por exemplo `DIR801`) e
nome. É deste catálogo que saem tanto as disciplinas do acerto de
matrícula quanto as ofertas do edital de isoladas. O código não se repete
dentro do programa.

### Cadastro de professores

Menu **Pessoas → Professores**. Ao cadastrar, informe categoria CAPES
(permanente, colaborador ou visitante), titulação, data de credenciamento
e, se quiser, Lattes e instituição de origem. Também é aqui que se marcam
as linhas de pesquisa e os projetos do professor.

Se a pessoa **já existe** no programa, digite o e-mail e use **Procurar**
antes de preencher o resto: o sistema reaproveita o cadastro em vez de
criar outro. Quando a conta ainda não tem senha, aparece o botão **Definir
senha inicial**.

Para descredenciar, use o terceiro ícone da linha. A data registrada é a
de hoje; se a portaria for retroativa, use a edição e informe a data
correta em "credenciado até".

### Cadastro de alunos

Menu **Pessoas → Alunos**. O formulário muda conforme a modalidade:

- **Regular** exige nível (mestrado ou doutorado), projeto coletivo e data
  de ingresso. O prazo de conclusão é calculado sozinho — 2 anos no
  mestrado, 4 no doutorado — e pode ser editado depois, no caso de
  prorrogação.
- **Isolada** e **Eletiva** exigem o período letivo e não têm campos de
  grau.

### Candidatos e administrativo

Menu **Pessoas → Candidatos** e **Pessoas → Administrativo**. As duas são
listas de leitura, e cada uma explica na própria tela de onde vêm os
nomes:

- **Candidatos** são as pessoas que se inscreveram em disciplina isolada.
  Quem já virou aluno continua aparecendo — o requerimento não deixa de
  existir quando a matrícula sai.
- **Administrativo** são as contas com papel de Secretaria ou Coordenação.
  Esse papel é atribuído pela equipe que opera a plataforma, não por esta
  tela.

As quatro listas de Pessoas **não são exclusivas**: quem coordena e dá
aula aparece em Professores _e_ em Administrativo, porque é uma pessoa só
com dois vínculos.

### Solicitações de acesso

Menu **Pessoas → Solicitações de acesso**. É a fila de quem se cadastrou
sozinho como docente ou discente e está esperando a confirmação. Cada
linha mostra o que a pessoa declarou; você decide:

- **Aprovar** completa o cadastro com o que só a secretaria sabe: para
  docente, a data de credenciamento; para discente, o nível, o projeto
  coletivo, o orientador e a data de ingresso. O aluno nasce **regular e
  ativo** — isolada e eletiva não passam por aqui, entram pelo edital.
  A pessoa passa a aparecer em Professores ou em Alunos, e o menu dela
  abre no próximo acesso.
- **Recusar** exige motivo, que é o que a pessoa lê na tela de espera. A
  pessoa fica arquivada e não consegue se recadastrar com o mesmo e-mail;
  se foi engano, reative-a pela lista correspondente.

Candidato não passa por esta fila: entra sozinho, porque só enxerga a
própria inscrição.

### Edital de disciplina isolada

Menu **Disciplina isolada → Editais**. Um edital por semestre. O
calendário tem seis marcos, e é ele que faz o sistema aceitar ou recusar
cada ação na data certa, sem ninguém conferir à mão:

1. abertura das inscrições;
2. encerramento das inscrições;
3. publicação do resultado;
4. abertura dos recursos;
5. encerramento dos recursos;
6. prazo final de pagamento da GRU.

As datas precisam estar em ordem — o sistema recusa um calendário em que a
janela de recurso abra antes de as inscrições fecharem.

Na mesma tela ficam as **disciplinas ofertadas**: cada oferta tem uma
disciplina do catálogo, o docente responsável (que será quem classifica os
candidatos) e o número de vagas.

**Encerrar o período** fecha o edital e desliga os alunos de isolada
daquele semestre. Antes de confirmar, o sistema informa quantos vínculos
serão encerrados. Não há encerramento automático por data: a decisão é da
secretaria.

### Análise das inscrições

Menu **Disciplina isolada → Análise**. É a fila de trabalho da secretaria.
Para cada inscrição você vê os documentos anexados e decide:

- **Deferir** — reserva a vaga. Informe o link da GRU para o candidato
  pagar. Servidor da UFMG entra como isento automaticamente.
- **Indeferir** — exige motivo. O motivo é o que o candidato lê e o que
  ele contesta no recurso, então escreva o que precisa ser corrigido.
- **Cancelar** — devolve a vaga à fila. É a única saída de um deferido que
  não pagou; nada expira sozinho.

Duas travas que você vai encontrar: não é possível deferir enquanto **o
docente não tiver classificado** os candidatos da oferta, nem quando a
oferta **não tem mais vaga**.

Depois do pagamento, a matrícula é efetivada e o candidato vira aluno de
isolada naquele semestre.

### Acompanhar acertos de matrícula

Menu **Acerto de matrícula → Do programa**. Lista, apenas para leitura,
de todas as solicitações do programa em um período, com a situação de cada
uma. Quem decide é o orientador.

## Docente

### Classificar candidatos das suas ofertas

Menu **Classificação**. Aparece para o docente responsável por alguma
oferta do edital. A tela separa **o que falta classificar** do que você já
respondeu.

Classificar é ordenar os inscritos: 1º, 2º, 3º. Essa ordem é o que a
secretaria usa para cortar pelas vagas disponíveis. Enquanto uma oferta
não estiver classificada, nenhuma inscrição dela pode ser deferida.

### Decidir os acertos dos seus orientandos

Menu **Acerto de matrícula → Orientandos**. Cada solicitação mostra o
aluno, o período, a justificativa e a lista de disciplinas a incluir ou
excluir. Você **aprova** ou **recusa**:

- aprovar não exige justificativa;
- recusar **exige motivo** — é o que o aluno lê para saber o que fazer.

A decisão é definitiva: uma solicitação já decidida não volta a ficar
aberta. Se algo mudar, o aluno abre outra.

## Discente

### Pedir acerto de matrícula

Menu **Acerto de matrícula → Meus acertos**. Use **Nova solicitação** para
montar um pedido: escolha o período, escreva a justificativa e liste as
disciplinas que quer **incluir** e as que quer **excluir**. Tudo vai num
pedido só, para o orientador decidir de uma vez.

Duas condições para abrir uma solicitação, e a tela avisa quando faltam:

- você precisa ser **aluno regular** — isolada e eletiva não abrem acerto;
- você precisa **ter orientador** — sem ele não haveria quem decidisse.

Depois de enviada, a solicitação fica _Aberta_ até o orientador decidir.
Quando ele decide, a situação passa a _Aprovada_ ou _Recusada_, e a recusa
sempre vem com o motivo.

## Candidato a disciplina isolada

Fluxo de quem não tem vínculo com a instituição e quer cursar até **duas
disciplinas** da pós num semestre.

### 1. Criar a conta

Na tela de login, embaixo do botão **Entrar**, clique em **Cadastre-se**,
escolha o programa, o perfil **Candidato** e informe nome, e-mail e senha.
A conta abre na hora, sem confirmação da secretaria — mas a inscrição só
existe enquanto houver edital com inscrições abertas.

### 2. Fazer a inscrição

Menu **Inscrição**. Escolha uma ou duas disciplinas entre as ofertadas e
anexe a documentação:

- identidade e CPF;
- diploma de graduação ou certidão de conclusão;
- currículo Lattes em PDF;
- comprovante de endereço.

**Servidor da UFMG** marca essa condição e anexa também contracheque e
autorização da chefia — em troca, fica isento da taxa.

Os arquivos são PDF, JPG ou PNG, de até 10 MB cada. Só é possível **enviar
a inscrição com toda a documentação anexada**, e só dentro do prazo do
edital. Enquanto ela for um rascunho, você pode trocar disciplinas e
documentos; depois de enviada, não.

### 3. Acompanhar

Menu **Acompanhamento**. Mostra a situação da sua inscrição:

| Situação    | O que significa                      |
| ----------- | ------------------------------------ |
| Rascunho    | montada, ainda não enviada           |
| Inscrito    | enviada, aguardando decisão          |
| Deferido    | aceito — falta pagar a taxa          |
| Indeferido  | recusado, com o motivo escrito       |
| Cancelado   | encerrado; a vaga voltou para a fila |
| Matriculado | matrícula efetivada                  |

**Deferido**: use o link da GRU disponível na tela, pague dentro do prazo
e anexe o comprovante. Quem é isento pula essa etapa.

**Indeferido**: cabe recurso, dentro da janela do edital. Escreva as
razões e, se o problema foi documentação, anexe a página que faltou — esse
é o único momento depois da inscrição em que dá para trocar um documento.

## Processo seletivo

É a seleção de mestrado e doutorado: edital, inscrição, bancas, atas,
convocação e resultado. Cada etapa trava a seguinte, e essa trava costuma
ser a resposta para "por que este botão está desabilitado?".

### Quem faz o quê

| Papel                   | O que faz                                                                                                                                                                   |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Secretaria**          | monta e publica o edital, homologa ou indefere inscrições, compõe as bancas, dispara convocações, acompanha as atas e converte o aprovado em aluno. É a única que baixa os anexos do candidato |
| **Docente**             | como membro de banca, lança notas e assina a ata; como presidente, monta e congela a ata                                                                                    |
| **Comissão de Seleção** | lê tudo e é a única que **realoca vaga** entre alvos — é decisão colegiada, não expediente da secretaria                                                                   |
| **Coordenação**         | acompanha, só leitura                                                                                                                                                       |
| **Candidato**           | inscreve-se sem conta e acompanha por protocolo                                                                                                                             |

### Secretaria: o edital

Menu **Processo seletivo → Editais**. O edital pode ser **Regular** ou
**Suplementar** (muda a documentação exigida do candidato). Antes de
publicar, ele precisa ter:

- as **etapas** em ordem (por exemplo: prova escrita, projeto, entrevista),
  cada uma com a nota de corte;
- a **grade de vagas**, por nível (mestrado, doutorado) e por categoria —
  ampla concorrência, cota racial, pessoa com deficiência, quilombola,
  pessoa trans, indígena;
- o **modelo da convocação**, o texto que vai por e-mail;
- o PDF do edital anexado.

**Publicar** é um botão, e ele confere tudo isso. Depois de publicado,
etapas e vagas não mudam mais: corrigir é encerrar e abrir outro.

### Candidato: inscrição e protocolo

Não há conta. A inscrição fica num endereço público que a secretaria
divulga com o edital. O candidato escolhe o edital aberto, o nível, a
categoria de vaga, preenche os dados e anexa os documentos:

- identidade, diploma ou certidão de conclusão, currículo Lattes e
  comprovante de pagamento — sempre;
- resumo expandido (edital Regular) ou memorial (Suplementar);
- comprovação da cota, quando não for ampla concorrência.

Ao enviar, recebe um **protocolo**. É com ele, e só com ele, que consulta
a situação depois, na tela de consulta pública. Guarde o protocolo: ele
faz as vezes de senha, e o sistema não o reenvia.

| Situação    | O que significa                                   |
| ----------- | ------------------------------------------------- |
| Inscrita    | enviada, aguardando homologação                   |
| Homologada  | documentação aceita; vai para as bancas           |
| Indeferida  | documentação recusada, com o motivo               |
| Eliminada   | nota abaixo do corte em alguma etapa              |
| Aprovada    | passou por todas as etapas                        |
| Matriculada | a secretaria já converteu a aprovação em matrícula |

### Secretaria: homologação, bancas e convocação

**Inscrições** (menu Processo seletivo) é a fila de homologação: para cada
inscrição você vê os anexos e **homologa** ou **indefere** com motivo. Só
inscrição homologada chega às bancas.

**Bancas**: uma banca para cada combinação de nível, categoria de vaga e
etapa, com presidente e membros. Examinador **de fora da casa** é
cadastrado como professor externo, com a instituição de origem; ele não
precisa ter conta, porque assina a ata por um link enviado ao e-mail dele.

**Convocações**: para cada edital e etapa, a lista de quem pode ser
convocado. O envio é em lote, e cada destinatário ganha uma situação
própria: enviado ou falhou. **Falha não cancela o lote** — quem falhou
aparece marcado e pode ser reenviado depois de corrigir o e-mail.

### Docente: notas e ata

Menu **Minhas bancas**. Cada banca abre uma tela para lançar as notas da
etapa, em lote. O caminho da ata é do presidente:

1. **Gerar a ata** monta o texto a partir das notas lançadas. Enquanto
   for rascunho, **atualizar** reconstrói o texto se alguma nota mudou.
2. **Congelar** fecha o texto: a partir daí ninguém lança nota naquela
   etapa, e o sistema envia o link de assinatura ao examinador externo.
   Enquanto ninguém assinou, **reabrir** desfaz o congelamento.
3. **Assinar**: quem tem conta assina na própria tela da banca; o externo
   assina pelo link do e-mail.

Quando a **última assinatura** entra, o sistema fecha a etapa sozinho:
promove quem passou para a etapa seguinte, elimina quem ficou abaixo do
corte e, na etapa final, aprova. A ata vira PDF. Ata assinada não se
apaga: se houver erro, faz-se uma ata retificadora, que substitui a
anterior e deixa as duas no histórico.

A secretaria acompanha tudo isso em **Atas**, de onde reenvia o link ao
externo e baixa o PDF.

### Resultado, realocação e matrícula

Menu **Processo seletivo → Resultado**. Com a ata da etapa final assinada,
a secretaria **calcula a classificação**, que distribui os aprovados pelas
vagas. Se sobrar vaga num alvo e faltar noutro, a **Comissão de Seleção**
pode **realocar** — o que invalida a classificação e obriga recalcular.

Por fim, **Matricular** converte o aprovado em aluno: o sistema cria a
pessoa (ou reaproveita, se já existia) e o vínculo de aluno regular. Daí em
diante a pessoa aparece em **Pessoas → Alunos**.

## Bolsas

É a distribuição anual das bolsas por barema: o discente pontua o próprio
currículo, a comissão confere, e o resultado sai em faixas de prioridade.

### Quem faz o quê

| Papel                 | O que faz                                                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Secretaria**        | monta a edição do ano, o barema e a comissão; publica; informa o nível FUMP de cada inscrito e, se preciso, força a faixa           |
| **Discente**          | inscreve-se, lança os itens do barema com comprovantes e, se discordar, interpõe recurso                                          |
| **Comissão de Bolsas** | confere item a item, baixa os comprovantes e julga os recursos. É outra comissão, diferente da de Seleção                        |
| **Coordenação**       | acompanha, só leitura                                                                                                             |

### As fases da edição

A edição do ano anda **só para frente**:

1. **Rascunho** — a secretaria monta o barema e a comissão.
2. **Inscrições abertas** — os discentes se inscrevem e pontuam.
3. **Em análise** — a comissão confere.
4. **Resultado preliminar** — publicado; abre o prazo de recurso.
5. **Recursos em análise** — a comissão julga.
6. **Resultado final** — publicado e definitivo.

Cada passagem é um botão na tela do edital, e não há volta: se algo saiu
errado, a correção é com a equipe que opera a plataforma.

### Secretaria: edital, barema e comissão

Menu **Bolsas → Edital**. O barema tem seis seções — formação acadêmica,
produção bibliográfica, participação em eventos, atividade profissional,
participação em bancas e outros títulos — e cada item diz o que pontua, em
que unidade (semestre, mês, hora, unidade) e com que teto. Você pode
**clonar o barema do ano anterior** e ajustar, em vez de digitar tudo de
novo.

A comissão é escolhida por edição. Publicar congela o ano: a partir daí
barema e comissão não mudam.

Durante a análise, é a secretaria quem lança o **nível FUMP** de cada
inscrito e, em caso excepcional, **força a faixa** de prioridade — os dois
únicos campos que ela escreve na inscrição de outra pessoa.

### Discente: inscrever-se e pontuar

Menu **Minha bolsa**, com as inscrições abertas. A inscrição copia o seu
nível (mestrado ou doutorado) e o congela. Para cada item do barema que se
aplica a você, informe a quantidade e anexe o comprovante; a nota do item
é calculada pelo sistema, respeitando o teto. O questionário da inscrição
pergunta também sobre ação afirmativa, professor substituto e vínculo de
trabalho público ou privado, que entram no cálculo da faixa.

Enquanto a edição estiver em **Inscrições abertas**, você pode alterar o
que quiser. Depois, não.

### Comissão: análise

Menu **Bolsas → Análise**. A fila de inscritos e, para cada um, o barema
lançado: você confere item a item, com o comprovante ao lado, e registra a
sua avaliação e uma observação, que o discente lê no resultado.

### Resultado e recurso

Menu **Bolsas → Resultado**. A classificação sai por nível, em **faixas de
prioridade** (2.1-I, 2.1-II, 2.4-I até 2.4-IX, e residual), na ordem em que
as bolsas são distribuídas. O resultado publicado é uma **fotografia** do
momento da publicação: mexer numa inscrição depois não muda o que está na
tela nem no PDF, que a secretaria imprime para afixar.

Com o resultado preliminar publicado, o discente pode interpor **um**
recurso em **Recurso da bolsa**, escrevendo as razões. A comissão julga —
deferido, parcialmente deferido ou indeferido — com a fundamentação, e o
resultado final é publicado em seguida.

## Quando algo dá errado

**Entrei e só vejo "Aguardando a secretaria".** Você se cadastrou como
docente ou discente e a secretaria ainda não confirmou. Não há nada a
fazer do seu lado; se estiver demorando, fale com ela.

**A tela diz "Cadastro não confirmado".** A secretaria recusou o seu
cadastro, e o motivo está na própria tela. O sistema não aceita um novo
cadastro com o mesmo e-mail: a saída é a secretaria reativar você.

**Não vejo um item de menu que deveria ver.** O menu reflete o papel da
sua conta. Fale com a secretaria.

**Uma tela diz que não tenho permissão.** Mesma coisa: seu papel não
alcança aquela ação. Nada foi perdido.

**Esqueci minha senha.** Fale com a secretaria. Ela define a senha do
_primeiro_ acesso; se a sua conta já tem senha, quem faz a redefinição é a
equipe que opera a plataforma.

**Perdi o protocolo da inscrição no processo seletivo.** O sistema não o
reenvia — ele faz as vezes de senha. Fale com a secretaria do programa,
que localiza a inscrição pelo seu e-mail.

**Não recebi o e-mail de convocação (ou o link de assinatura da ata).**
A secretaria vê, na tela de convocações ou de atas, se o envio falhou, e
reenvia. Confira também a pasta de spam.

**O sistema recusou uma data.** Datas de edital seguem uma ordem
obrigatória, e prazos são conferidos contra o calendário publicado. A
mensagem diz qual regra foi violada.

**"Já existe uma pessoa com este e-mail".** O cadastro já está no sistema.
Procure pelo e-mail antes de criar outro — o formulário reaproveita a
pessoa existente.

**Fui deslogado sozinho.** A sessão expirou. Entre de novo; nada do que
você salvou se perde.

---

# Manual do Desenvolvedor

Escrito para quem está começando. Nenhum passo é considerado óbvio, e cada
decisão vem com o porquê — porque saber _por que_ algo é assim é o que
evita desfazê-lo sem querer.

## Sumário

1. [A regra que economiza mais tempo](#1-a-regra-que-economiza-mais-tempo)
2. [O que você precisa ter instalado](#2-o-que-você-precisa-ter-instalado)
3. [Subindo pela primeira vez](#3-subindo-pela-primeira-vez)
4. [A estrutura da aplicação, do banco à tela](#4-a-estrutura-da-aplicação-do-banco-à-tela)
5. [As decisões de arquitetura](#5-as-decisões-de-arquitetura)
6. [Cada comando do Makefile](#6-cada-comando-do-makefile)
7. [O Vite em desenvolvimento e em produção](#7-o-vite-em-desenvolvimento-e-em-produção)
8. [Quem entra onde](#8-quem-entra-onde)
9. [Armadilhas conhecidas](#9-armadilhas-conhecidas)
10. [Os módulos de negócio por dentro](#10-os-módulos-de-negócio-por-dentro)
11. [E-mail em desenvolvimento: o Mailpit](#11-e-mail-em-desenvolvimento-o-mailpit)

---

## 1. A regra que economiza mais tempo

**Acesse sempre `http://localhost:8080`.**

Abrir o Vite direto em `:5173` faz o login e o CSRF quebrarem de um jeito
que o navegador reporta de forma enigmática. Não é bug: front e API
precisam compartilhar a mesma origem, e quem garante isso é o Nginx na 8080. Ver [ADR-004](docs/adr/004-origem-unica-sem-cors.md).

Se você só decorar uma frase deste manual, que seja esta.

---

## 2. O que você precisa ter instalado

|                                    | Para quê                                                                            |
| ---------------------------------- | ----------------------------------------------------------------------------------- |
| [`uv`](https://docs.astral.sh/uv/) | dependências do backend — **instala o Python sozinho**, você não precisa ter Python |
| Node 20+ e `npm`                   | dependências e build do frontend                                                    |
| Docker + Compose v2                | banco, backend e Nginx                                                              |
| `make`                             | atalho para tudo                                                                    |

O `uv` merece uma nota: ele resolve dependências e gerencia a versão do
Python do projeto. Por isso todo comando Python daqui roda como
`uv run python ...`, e não `python ...` — o `python` do sistema não
enxerga as dependências do projeto.

---

## 3. Subindo pela primeira vez

```bash
git clone https://dso.direito.ufmg.br/ati/ppgd-manager.git
cd ppgd-manager
cp .env.example .env      # ajuste se precisar; o .env nunca vai pro git
make install              # dependências do backend
make install-web          # dependências do frontend
make up                   # sobe db + backend + frontend + nginx + mailpit
make migrate              # cria as tabelas
make seed                 # carga de demonstração: dois programas, todos os papéis
make superuser            # crie a SUA conta de sysadmin
```

Um terminal só. O Vite sobe dentro do `make up`, como serviço do Compose;
`make web` existe apenas para acompanhar o log dele (ver a
[seção 7](#7-o-vite-em-desenvolvimento-e-em-produção)).

Pronto:

- **Sistema** → http://localhost:8080
- **Admin** → http://localhost:8080/admin/ (só superusuário — veja a seção 8)
- **Documentação da API** → http://localhost:8080/api/v1/docs

O `make seed` deixa o sistema com dois programas (PPGD e PPGA), contas
para cada papel e o caminho de cada módulo quase todo andado — editais
publicados, bancas, uma ata assinada, edições de bolsa, inscrições em
isolada. As contas e a senha ficam em **`CONTAS-DEMO.txt`**, na raiz do
repositório (ignorado pelo git). É idempotente: rode de novo à vontade; só
funciona com `DEBUG=True`.

| Serviço    | O que é                                 | Porta no host                          |
| ---------- | --------------------------------------- | -------------------------------------- |
| `db`       | Postgres 17.5                           | `DB_PORT`, 5433                        |
| `backend`  | Django, `runserver`                     | nenhuma (só pelo nginx)                |
| `frontend` | Vite dev server (`node:25-slim`)        | nenhuma (rede interna)                 |
| `mailpit`  | captura todo e-mail (ver a seção 11)    | nenhuma (`docker compose port mailpit 8025`) |
| `nginx`    | origem única                            | `NGINX_PORT`, 8080                     |

---

## 4. A estrutura da aplicação, do banco à tela

Esta seção segue **um dado só** — uma pessoa cadastrada — desde a tabela
no Postgres até o pixel na tela. Todo recurso do sistema percorre esse
mesmo caminho; aprender uma vez basta.

### O mapa em uma imagem

```
  navegador
     │
     │  http://localhost:8080
     ▼
  ┌─────────────────────────────────────────────────┐
  │ Nginx  (origem única — ADR-004)                 │
  │                                                 │
  │  /api/     ──► backend  (Django)                │
  │  /admin/   ──► backend  (Django)                │
  │  /static/  ──► backend  (Django)                │
  │  /media/   ──► backend  (Django)                │
  │  /         ──► Vite em dev · arquivos em prod   │
  └─────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  ┌───────────────┐            ┌──────────────────────┐
  │ Django        │            │ SvelteKit (SPA)      │
  │  router.py    │            │  +page.svelte        │
  │  schemas.py   │            │  sessao.svelte.ts    │
  │  services.py  │            │  lib/api/client.ts   │
  │  models.py    │            │  lib/api/schema.d.ts │
  └───────────────┘            └──────────────────────┘
        │                              ▲
        ▼                              │
  ┌───────────────┐                    │
  │ PostgreSQL    │      OpenAPI ──────┘
  └───────────────┘   (make gen-api)
```

Repare que a seta do OpenAPI aponta **do backend para o frontend**. Isso é
importante: os tipos do front não são escritos à mão, são gerados a partir
da API. Voltaremos a isso.

### Camada 1 — o banco

PostgreSQL, num container, com volume nomeado. Você quase nunca escreve
SQL: quem cria e altera tabela são as _migrations_ do Django, que são
arquivos Python versionados em `backend/apps/<app>/migrations/`.

Duas regras que valem desde já:

- **Toda tabela de negócio tem `program_id`.** É a chave de tenant. O
  sistema nasce para o PPGD, mas o dado já vem preparado para vários
  programas, porque acrescentar essa coluna depois, com dados em produção,
  é caro. A FK é direta mesmo quando alcançável por navegação, porque sem
  ela o `AuditLog` perde a chave de tenant. Única exceção: o período letivo
  (`AcademicTerm`), que é da instituição inteira
  ([ADR-007](docs/adr/007-modalidade-e-situacao-do-aluno.md)).
- **Nunca edite uma migration já aplicada.** Gere uma nova.

### Camada 2 — o model, que é a entidade

`backend/apps/people/models.py`. Aqui mora **a definição do dado e a regra
de negócio**, juntos. Não existe uma "entidade de domínio" separada do
model — ver [ADR-002](docs/adr/002-model-como-entidade.md).

```python
class Person(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        ARCHIVED = "archived", "Arquivada"

    program = models.ForeignKey("programs.Program", on_delete=models.PROTECT, ...)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, ...)
    full_name = models.CharField("nome completo", max_length=200)
    ...

    def archive(self) -> None:
        """Invariante: arquivar só faz sentido a partir de ACTIVE."""
        if self.status == self.Status.ARCHIVED:
            raise InvalidStateTransition("Pessoa já está arquivada.")
        self.status = self.Status.ARCHIVED
```

Três coisas para observar, porque cada uma é um padrão que se repete:

**`archive()` é um método, não um `update` solto.** A regra "não arquivar
duas vezes" fica _dentro_ do model, então qualquer caminho que arquive uma
pessoa passa por ela. Testar essa regra é barato — instancia o objeto em
memória, sem banco e sem mock.

**Escolha fechada é `TextChoices`.** Nunca se repete a string `"archived"`
espalhada pelo código; importa-se `Person.Status.ARCHIVED`.

**`QuerySet` customizado guarda consulta recorrente.** `Person.objects.active()`
e `.for_program(p)` moram no `PersonQuerySet`, não copiadas em cada view.

O `people` é o **exemplo de referência**. App novo: copie a estrutura dele.

### Camada 3 — o service, só quando precisa

`backend/apps/people/services.py`. O mais curto dos services do projeto, e
o próprio arquivo explica por que existe:

> Este arquivo só existe porque `create_person_with_user` escreve em três
> models e precisa ser atômico (ADR-002). Operação que toca um model só é
> chamada direto do router — não crie service "por simetria".

Ou seja: service não é camada obrigatória. É a exceção para operação que
precisa de `@transaction.atomic` cruzando models. **Service que só
encaminha para um model é code smell — apague.**

Hoje cinco apps têm `services.py` — `people`, `accounts`, `academic`,
`selection` e `scholarships` — e em todos vale o mesmo critério: cada
função de lá escreve em mais de um model (ou em model + `AuditLog` + e-mail)
e precisa ser tudo ou nada. O de `selection` é grande porque o processo
seletivo é uma sequência de transições que cruzam inscrição, banca, ata e
vaga; não porque a regra tenha saído do model.

### Camada 4 — o router, a borda HTTP

`backend/apps/people/router.py`. Django Ninja, não DRF
([ADR-001](docs/adr/001-django-sincrono-com-ninja.md)). O router é **fino
de propósito** e sempre tem a mesma forma:

```python
@router.post("/{int:person_id}/archive", response=PersonOut)
def archive_person(request: HttpRequest, person_id: int):
    require_perm(request, "people.change_person")     # 1. permissão, sempre na 1ª linha
    person = get_object_or_404(Person, pk=person_id)  # 2. busca
    with transaction.atomic():
        person.archive()                              # 3. a REGRA mora no model
        person.save(update_fields=["status", "updated_at"])
        audit.record("people.archive", request=request, target=person)  # 4. auditoria
    return person                                     # 5. schema de saída explícito
```

Quatro regras de review saem daí:

1. **`require_perm` na primeira linha de toda rota.** Rota sem checagem só
   passa marcada com `# público` e justificativa.
2. **Zero regra de negócio no router.** Se você escreveu um `if` de
   domínio aqui, ele pertence ao model.
3. **Auditoria dentro do mesmo `atomic` da escrita.** Nunca se cria
   `AuditLog` direto — chama-se `audit.record()`.
4. **Nada de `try/except` no router.** `backend/api.py` tem handlers
   centrais que traduzem `DomainError` em 4xx com corpo padronizado
   `{detail, code}`.

### Camada 5 — os schemas

`backend/apps/people/schemas.py`. Classes Pydantic que definem o que
**entra** (`PersonIn`) e o que **sai** (`PersonOut`) da API. São elas que
geram o OpenAPI, e é do OpenAPI que o frontend gera seus tipos.

Consequência prática: mudar um `PersonOut` sem rodar `make gen-api` deixa
o front tipado com uma versão que não existe mais.

### Camada 6 — a montagem da API

`backend/api.py` junta os routers e define o padrão de autenticação:

```python
api = NinjaAPI(..., auth=django_auth)
api.add_router("/auth/", accounts_router)          # login, logout, csrf, me
api.add_router("/accounts/", accounts_users_router) # senha inicial
api.add_router("/programs/", programs_router)      # programa, linhas, projetos, disciplinas, períodos
api.add_router("/people/", people_router)
api.add_router("/academic/", academic_router)      # professores, alunos, isolada, acerto de matrícula
api.add_router("/access/", academic_access_router) # autocadastro e fila de solicitações
api.add_router("/selection/", selection_router)    # processo seletivo
api.add_router("/scholarships/", scholarships_router)
```

`auth=django_auth` significa **sessão do Django em toda rota por padrão**
([ADR-003](docs/adr/003-sessao-e-csrf-sem-jwt.md)). Rota pública precisa
declarar `auth=None` explicitamente e se justificar. As que existem:
`/auth/csrf` e `/auth/login`, `/programs/public` (programas que aceitam
autocadastro), `/access/signup`, e as `/selection/public/*` da inscrição
do candidato — estas com rate limit e `csrf_protect` explícitos, e com o
tenant saindo do edital encontrado, nunca de um `program_id` do chamador.

### Camada 7 — a ponte de tipos

```bash
make gen-api
```

Exporta o OpenAPI do Django para `frontend/src/lib/api/openapi.json` e
gera `schema.d.ts` a partir dele. **Rode sempre que mexer em schema ou em
rota.** É o que faz o TypeScript acusar, em tempo de escrita, que um campo
que você usa na tela não existe mais na API.

### Camada 8 — o cliente HTTP do front

`frontend/src/lib/api/client.ts`. Existe **um** cliente, e nenhuma tela usa
`fetch` cru:

```ts
export const api = createClient<paths>({
  baseUrl: "/api/v1", // RELATIVA, sempre (ADR-004)
  credentials: "include", // sem isto o cookie de sessão não vai junto
});
api.use(csrf); // injeta X-CSRFToken em POST/PUT/PATCH/DELETE
```

O middleware de CSRF resolve o header **de uma vez só**. Nenhuma tela lida
com CSRF, e é por isso que ninguém deve chamar `fetch` diretamente: quem
faz isso perde o CSRF e as credenciais, e o erro aparece longe da causa.

Há também `garantirCsrf()`, que planta o cookie antes da primeira escrita —
no login ainda não há sessão, então o token precisa ser pedido antes.

### Camada 9 — a tela

`frontend/src/routes/`. SvelteKit em modo SPA pura:

```
routes/
  +layout.ts            ssr = false, prerender = false  (ADR-005)
  +layout.svelte        casca comum
  +page.svelte          raiz
  (auth)/login/         grupo de rotas sem sessão
  (app)/                grupo de rotas autenticadas
    pessoas/+page.svelte
```

Os parênteses em `(auth)` e `(app)` são **grupos de rota** do SvelteKit:
organizam arquivos e permitem um layout por grupo, sem aparecer na URL.

`frontend/src/lib/sessao.svelte.ts` guarda o estado do usuário logado.

Como `ssr = false`, **toda busca de dado acontece no navegador**, depois do
carregamento. `+page.server.ts` e `load` com acesso a banco não existem
neste projeto — se você viu isso num tutorial de SvelteKit, não se aplica
aqui.

### O caminho completo, resumido

Um clique em "Arquivar" na tela de pessoas percorre:

```
+page.svelte  →  api.POST('/people/{id}/archive')  →  client.ts injeta CSRF
   →  Nginx :8080  →  /api/ vai para o backend
   →  router.archive_person()  →  require_perm  →  Person.archive()
   →  save() + audit.record()  →  PostgreSQL
   →  PersonOut  →  JSON  →  a tela atualiza
```

### Onde mora cada coisa

```
backend/
  api.py                    monta a API e traduz erros
  config/
    settings/base.py        configuração comum
    settings/dev.py         desenvolvimento
    settings/prod.py        produção
    urls.py                 /api/v1/ e /admin/
    wsgi.py                 ponto de entrada (WSGI, não ASGI — ADR-001)
  apps/
    core/                   permissions.py, audit.py, exceptions.py, tenancy.py, seed_demo
    accounts/               User, login, logout, CSRF, senha inicial
    programs/               Program (a chave de tenant), linhas, projetos, disciplinas, períodos
    people/                 Person — o exemplo de referência
    academic/               Teacher, Student, isolada, acerto de matrícula, AccessRequest
    selection/              processo seletivo (+ pdf.py da ata, emails.py)
    scholarships/           edital de bolsas (+ pdf.py do resultado)
    audit/                  AuditLog
frontend/src/
  lib/api/client.ts         o cliente único
  lib/api/schema.d.ts       tipos GERADOS — não edite à mão
  lib/sessao.svelte.ts      estado da sessão
  routes/(auth)/            login, cadastro, aguardando-confirmacao
  routes/(publico)/         inscrição e protocolo do processo seletivo, assinatura por token
  routes/(app)/             as telas autenticadas
nginx/                      configuração da origem única
docs/adr/                   as decisões de arquitetura
scripts/helton/             a esteira de desenvolvimento autônomo (README próprio)
.gitlab-ci.yml              o pipeline: `make ready` a cada push
```

Cada app do Django tem `models.py`, `admin.py`, `router.py`, `schemas.py`,
`migrations/` e `tests/`. "App" aqui é o termo do Django — um módulo do
backend, sem relação com as telas do frontend.

### Quanto custa um campo novo

Cerca de **6 arquivos**, ponta a ponta: model, migration, schema, router
(se mudar a assinatura), `make gen-api`, tela. Se custar muito mais que
isso, é sinal de que a arquitetura foi violada em algum ponto — é o alarme
combinado no ADR-002.

**Entidade nova é diferente e é cara**: fatia vertical inteira, incluindo
permissão e auditoria. Ver [ADR-006](docs/adr/006-admin-so-para-sysadmin.md).

---

## 5. As decisões de arquitetura

Estão em [`docs/adr/`](docs/adr/), um arquivo por decisão, no formato
ADR — contexto, decisão, consequências. **Leia os dez antes de propor
mudança estrutural.** Eles registram não só o que foi escolhido, mas o que
foi descartado e por quê, o que evita reabrir discussão já encerrada.

Resumo, com o que cada um significa no seu dia a dia:

### [ADR-001](docs/adr/001-django-sincrono-com-ninja.md) — Django síncrono com Django Ninja

**Decisão:** Django 5.x **síncrono**, sem nenhuma view `async`, com Django
Ninja para a API em `/api/v1/`.

**Por quê:** o sistema atende dezenas de usuários simultâneos, não
milhares — o custo dominante do projeto é erro humano, não CPU. Código
async cria uma classe de bug que não existe no síncrono (`await`
esquecido, ORM fora do event loop, biblioteca bloqueante) e que quebra
_sob carga_, o pior formato para quem está aprendendo. Ninja em vez de DRF
porque usa type hints e Pydantic, que o time já precisa conhecer, em vez
de um vocabulário próprio (serializers, viewsets, routers).

**No seu dia a dia:** nunca escreva `async def` numa view. O deploy é WSGI
(`gunicorn`) — o projeto **deliberadamente não tem `asgi.py`**.

### [ADR-002](docs/adr/002-model-como-entidade.md) — Model é a entidade de domínio

**Decisão:** a regra de negócio mora no model. `services.py` é opcional e
só para operação atômica que cruza models.

**Por quê:** Repository, Mapper e Unit of Work existem para desacoplar de
um ORM pobre e permitir trocar de banco. O ORM do Django já é repositório
e mapper, e o PostgreSQL não vai ser trocado. O custo dessas camadas é
imediato: campo novo passando por cinco arquivos e ninguém sabendo onde a
regra mora.

**No seu dia a dia:** proibidos Repository, Mapper, Unit of Work, entidade
paralela ao model e Protocols criados por antecipação. Regra de negócio em
router não passa em review.

### [ADR-003](docs/adr/003-sessao-e-csrf-sem-jwt.md) — Sessão do Django, sem JWT

**Decisão:** sessão em cookie `HttpOnly`, CSRF sempre ativo, permissões e
grupos **nativos** do Django. Papel de domínio ("Secretaria",
"Coordenação") é `Group` criado por data migration, não um RBAC próprio.

**Por quê:** JWT resolve origem cruzada e múltiplos consumidores — não é o
caso aqui. Onde há origem única, JWT é _downgrade_: o token fica no
browser (`localStorage` é vulnerável a XSS), não dá para revogar sem
inventar denylist, e a renovação exige um segundo fluxo.

**No seu dia a dia:** toda escrita precisa do header `X-CSRFToken`, e isso
já está resolvido no `client.ts`. Logout revoga de verdade, no servidor.
Admin e API compartilham a mesma sessão.

### [ADR-004](docs/adr/004-origem-unica-sem-cors.md) — Origem única via Nginx, CORS proibido

**Decisão:** front e API sempre atrás do mesmo Nginx, na mesma origem. O
`baseUrl` do cliente é **relativo** (`/api/v1`).

**Por quê:** CORS mal configurado é fonte frequente de brecha e de tempo
perdido. Com cookie de sessão, origem cruzada exigiria `SameSite=None` +
`Secure` + `credentials`, e errar um dos três quebra o login de forma
enigmática.

**No seu dia a dia:** **CORS é proibido** — se você sentiu necessidade de
configurar CORS, o erro está no deploy, não no código. URL absoluta de API
no front não passa em review. E: sempre `:8080`, nunca `:5173`.

### [ADR-005](docs/adr/005-front-estatico-sem-ssr.md) — Front estático, sem SSR e sem Node em produção

**Decisão:** SvelteKit com `adapter-static`, SPA pura, `ssr = false`.
Nenhum processo Node em produção, em nenhuma hipótese.

**Por quê:** `adapter-node` + SSR exigiria um processo Node rodando em
produção — mais um runtime para a infra instalar, supervisionar, atualizar
e incluir no plano de recuperação. O que SSR entrega (SEO, primeiro paint)
não tem valor num sistema atrás de login, interno, em rede boa.

**No seu dia a dia:** toda busca de dado é no browser. Nada de
`+page.server.ts`. Ver a [seção 7](#7-o-vite-em-desenvolvimento-e-em-produção).

### [ADR-006](docs/adr/006-admin-so-para-sysadmin.md) — Admin só para sysadmin

**Decisão:** o Django Admin é ferramenta de operação da plataforma,
restrita a superusuários. Todo usuário de negócio é atendido pelo
frontend.

**Por quê:** este ADR **substitui** uma orientação anterior, e a razão é
instrutiva. O Admin edita campos direto: arquivar uma pessoa lá é trocar
`status` num `<select>` — `Person.archive()` nunca é chamado, e o
invariante que ele protege deixa de existir naquele caminho. Seriam duas
portas para o mesmo dado, uma delas ignorando as regras do model. Somado a
isso, a escrita pelo Admin não gerava `AuditLog`, e a diferença visual
fazia o usuário perceber dois sistemas.

**No seu dia a dia:** a trava é de código — `admin.site.has_permission`
exige `is_superuser`; `is_staff` sozinho não abre a porta. Papel de
domínio nunca recebe `is_staff` nem `is_superuser`. Falta tela para
alguma coisa? O trabalho é escrever a tela, não dar acesso ao Admin —
inclusive quando o prazo aperta. Há um **período de desconforto
deliberado** aqui, e reabrir o Admin "temporariamente" é exatamente o que
o ADR proíbe.

### [ADR-007](docs/adr/007-modalidade-e-situacao-do-aluno.md) — Modalidade e situação do aluno

**Decisão:** no aluno, **modalidade** (Regular, Isolada, Eletiva) e
**situação** (Ativo, Trancado, Excluído) são dois campos. Trancar só vale
para regular, e o banco garante isso por `CheckConstraint`. `Student.person`
é `ForeignKey`, não `OneToOne`: uma pessoa tem vários episódios de vínculo,
cada um com a própria matrícula. Período letivo (`AcademicTerm`) é entidade
**institucional**, sem FK de programa — a única exceção à regra do tenant.

**Por quê:** um campo só de "status" misturava o que a pessoa é no programa
com como está o vínculo agora, e "excluído" tinha de significar desistência
e fim normal de semestre ao mesmo tempo.

**No seu dia a dia:** todo model de negócio novo carrega `program` direto,
mesmo quando alcançável por navegação. Campos de grau são obrigatórios por
constraint quando a modalidade é regular — o formulário não é a garantia.

### [ADR-008](docs/adr/008-pdf-da-ata-com-reportlab.md) — PDF da ata com ReportLab

**Decisão:** o PDF da ata do processo seletivo sai do **ReportLab**, montado
em `apps/selection/pdf.py`. Sem HTML-para-PDF, sem binário externo. O texto
da ata é o `content` congelado no banco; o PDF é renderização, nunca a
fonte.

**Por quê:** WeasyPrint e afins trazem dependência de sistema (Cairo, Pango)
que a imagem não tem e a infra teria de manter. ReportLab é Python puro com
fonte embutida.

**No seu dia a dia:** procurar texto dentro do PDF em teste exige desfazer
três camadas (compressão, escape octal dos acentos, quebra de `Paragraph`
em `Tj` separados). Há um helper para isso nos testes de bolsas.

### [ADR-009](docs/adr/009-email-de-convocacao-sem-fila.md) — E-mail síncrono, sem fila

**Decisão:** `django.core.mail` direto, dentro do request, sem Celery, sem
broker e sem retry automático. Cada envio vira uma linha com status
(`pending`/`sent`/`failed`) e a mensagem do erro. O envio fica **fora** do
`transaction.atomic`.

**Por quê:** um lote de dezenas de mensagens, algumas vezes por ano, não
justifica uma peça de infraestrutura nova. Falha é dado, não exceção
perdida: quem decide reenviar é uma pessoa, que sabe se o endereço estava
errado.

**No seu dia a dia:** link que vai em e-mail se monta com
`settings.SITE_URL`, nunca com `request.build_absolute_uri()`. Em
desenvolvimento tudo cai no Mailpit ([seção 11](#11-e-mail-em-desenvolvimento-o-mailpit)).

### [ADR-010](docs/adr/010-pdf-do-resultado-de-bolsas.md) — PDF do resultado de bolsas

**Decisão:** mesmo motor do ADR-008, em `apps/scholarships/pdf.py`,
espelhando o desenho da ata. O documento renderiza o **snapshot** publicado,
não o cálculo ao vivo.

**No seu dia a dia:** valor em real no papel usa `force_grouping=True`; sem
isso sai `3200,00` em vez de `3.200,00`, sem erro nenhum.

### Como escrever um ADR novo

Copie [`docs/adr/000-template.md`](docs/adr/000-template.md). Contexto são
**fatos, não opiniões**: qual problema apareceu, que restrição existe, o
que já foi tentado. A decisão vai no presente ("usamos X"). Alternativa
séria descartada entra com uma linha dizendo por quê.

---

## 6. Cada comando do Makefile

O `Makefile` é a **fonte da verdade**: comando novo entra lá, não só no
README. `make` sozinho lista todos (é o `.DEFAULT_GOAL`).

Dois atalhos internos que aparecem em todo alvo:

- `$(UV)` = `cd backend && uv run` — roda no ambiente Python do projeto.
- `$(NPM)` = `cd frontend && npm` — roda no frontend.

### Instalação

| Comando            | O que faz                                                                                                                                                                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make ajuda`       | Lista os comandos com a descrição. É o padrão do `make` sem argumento.                                                                                                              |
| `make install`     | `uv sync` no backend. Resolve as dependências Python **e instala o próprio Python** na versão do projeto. Rode depois de todo `git pull` que mexa em `pyproject.toml` ou `uv.lock`. |
| `make install-web` | `npm install` no frontend. Mesma lógica para `package.json`.                                                                                                                        |

### Subir e derrubar

| Comando     | O que faz                                                                                                                                          |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make db`   | Sobe **só o Postgres** (`docker compose up -d db`). Use com `make run` quando quiser o Django nativo, com reload mais rápido e depurador acoplado. |
| `make up`   | Sobe `db` + `backend` + `frontend` + `nginx`, com `--build`. É o modo normal de trabalho: a stack inteira, num comando só.                         |
| `make down` | `docker compose down`. Derruba os containers e **preserva o volume** — o banco continua lá.                                                        |

O `make up` sobe **o frontend também** — o Vite é um serviço do Compose.
Ver a [seção 7](#7-o-vite-em-desenvolvimento-e-em-produção).

### Rodar em modo desenvolvimento

| Comando    | O que faz                                                                                                                                                                        |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make run` | `runserver` do Django **nativo**, fora do container, na 8000. Precisa de `make db` antes. Alternativa ao `backend` do Compose quando você quer depurar com breakpoint no editor. |
| `make web` | Acompanha o log do Vite (`docker compose logs -f frontend`). O servidor sobe junto com o `make up`, no serviço `frontend` — não é mais preciso deixá-lo rodando à parte. Acesse sempre pela 8080. |

### Banco de dados

| Comando           | O que faz                                                                                                                                                                                |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make migrations` | `makemigrations` — gera os arquivos de migração a partir das mudanças nos models. **Leia o arquivo gerado antes de commitar**: o Django às vezes infere algo diferente do que você quis. |
| `make migrate`    | `migrate` — aplica as migrações pendentes no banco.                                                                                                                                      |
| `make superuser`  | `createsuperuser` — cria uma conta de sysadmin, a única que entra no Admin (ADR-006).                                                                                                    |
| `make seed`       | `seed_demo` — carga de demonstração nos dois programas, idempotente, só com `DEBUG=True`. Escreve as contas em `CONTAS-DEMO.txt`.                                                        |

Em produção a ordem é **migração primeiro, sempre**, e a migração precisa
ser retrocompatível com o código anterior: campo novo entra `null=True` ou
com default.

### A ponte de tipos

| Comando        | O que faz                                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `make gen-api` | Exporta o OpenAPI do Django para `frontend/src/lib/api/openapi.json` e gera o `schema.d.ts` a partir dele. |

Rode **sempre que mexer em schema ou em rota**. Sem isso o front continua
tipado contra uma API que mudou, e o erro só aparece em runtime — que é
exatamente o que a geração de tipos existe para evitar.

### Qualidade

| Comando          | O que faz                                                                                                                                           |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make test`      | `pytest` no backend. **O Postgres precisa estar de pé** (`make db` ou `make up`).                                                                   |
| `make lint`      | `ruff format` + `ruff check --fix` no backend, `npm run format` + `npm run lint` no frontend. Formata **e corrige** o que dá para corrigir sozinho. |
| `make typecheck` | `mypy` no backend e `svelte-check` no frontend.                                                                                                     |
| **`make ready`** | `lint` + `typecheck` + `test`, nessa ordem. **Verde é pré-condição de qualquer commit.**                                                            |

`make ready` é o único que você precisa lembrar antes de commitar — ele
chama os outros três. Se ele estiver vermelho, o commit não sai.

### O pipeline do GitLab

O `.gitlab-ci.yml` roda **o mesmo `make ready`** a cada push, num job só,
com um Postgres de serviço. Duas diferenças em relação à sua máquina:

- Ele instala com `uv sync --locked` e `npm ci`: lockfile desatualizado
  **falha**, em vez de ser reescrito em silêncio.
- Depois do `make ready` ele roda `git diff --exit-code`. O `make lint`
  formata em vez de conferir, e sai com zero mesmo tendo reescrito arquivo;
  no CI, arquivo reescrito significa que chegou sem formatar, e o diff
  acusa exatamente qual.

Para ver o resultado sem abrir o navegador, `glab ci status` (o `glab`
precisa estar autenticado no GitLab da faculdade). O pipeline não faz
deploy: produção continua sendo a seção 10 do `CLAUDE.md`.

---

## 7. O Vite em desenvolvimento e em produção

Esta é a parte que mais confunde quem chega, então vale a explicação
completa.

### Vite não é "um tipo de Node"

- **Node** é o _runtime_: executa JavaScript fora do navegador. É o
  "python" da analogia.
- **Vite** é um programa escrito em JavaScript que precisa do Node para
  rodar. É o "django" da analogia.

A cadeia completa do nosso front é:

**Svelte** (a linguagem de componente) → **SvelteKit** (o framework de
rotas) → **adapter-static** (a peça que manda o SvelteKit gerar arquivos
parados em vez de um servidor Node) → **Vite** (quem executa a
compilação) → **Node** (quem executa o Vite).

### O Vite faz duas coisas bem diferentes

**1. Servidor de desenvolvimento** — `npm run dev`, no serviço `frontend`.

Serve o código-fonte ao navegador quase sem transformação, usando módulos ES
nativos. Quando você salva um `.svelte`, ele empurra só aquele módulo para a
página já aberta — é o _hot reload_. Este é o processo Node que precisa ficar
vivo enquanto você trabalha; ele sobe junto com o `make up`.

**2. Empacotador** — `npm run build`.

Roda uma vez, lê todo o `frontend/`, compila os `.svelte` para JavaScript,
junta, minifica e produz uma pasta de `.html`, `.js` e `.css`. Terminou, o
processo morre.

### Em desenvolvimento

O Nginx do Compose faz proxy para o Vite, que é um serviço da mesma stack:

```nginx
upstream vite { server frontend:5173; }

location / {
    proxy_pass http://vite;
    # ... cabeçalhos de upgrade para o WebSocket do hot reload
}
```

Aquela `5173` é a porta **interna** da rede do Compose. Ela não é publicada e
não precisa ser: quem atende o navegador é o Nginx, na 8080.

Um só terminal, portanto — `make up` sobe os cinco serviços e o front já
está no ar. O `make web` continua existindo, mas agora só acompanha o log do
Vite.

**Por que o Vite é serviço do Compose.** Ele já foi nativo, alcançado por
`host.docker.internal:5173`, e a razão era hot reload mais rápido. O que
derrubou esse arranjo foi a esteira de obra: com N worktrees rodando ao mesmo
tempo, os N Nginx apontavam todos para o mesmo Vite do host — que serve o
código de UMA worktree. Todo canteiro exibia o front de outro, sem erro
nenhum na tela. Uma porta interna por stack resolve isso sem parametrizar
nada, porque cada canteiro tem a sua rede.

Duas consequências que valem saber:

- A imagem é `node:25-slim`, não `node:alpine`. O `node_modules` montado é o
  mesmo do host (é ele que o `make lint` e o `make typecheck` usam), e o
  `npm ci` de lá baixa os binários `linux-x64-gnu` do rollup e do
  `@tailwindcss/oxide`. Numa imagem musl eles não carregam, e o erro aparece
  como "cannot find module" de um pacote que está lá.
- O `hmr.clientPort` do `vite.config.ts` vem de `NGINX_PORT`. O WebSocket de
  hot reload é aberto pelo navegador, então precisa da porta publicada — a
  5173 não existe fora do Compose. Estava cravado em `8080`, o que fazia
  qualquer stack em outra porta perder o hot reload em silêncio: a página
  carrega, só não atualiza.

### Em produção

**Nenhum processo Node**, em nenhuma hipótese (ADR-005). O front vira
arquivo parado:

```bash
npm run build     # gera os estáticos com o adapter-static
# copiar a saída para o diretório servido pelo Nginx
```

E o `location /` do Nginx troca de proxy para disco — o bloco já está
escrito em comentário no `nginx/nginx.conf`:

```nginx
location / {
    root      /var/www/ppgd;      # saída de `npm run build`
    try_files $uri $uri/ /index.html;
}
```

O `try_files ... /index.html` é o que faz uma SPA funcionar com URL
direta: qualquer caminho desconhecido devolve o `index.html`, e o
roteamento acontece no navegador.

### O quadro comparativo

|                        | Desenvolvimento                   | Produção                                             |
| ---------------------- | --------------------------------- | ---------------------------------------------------- |
| SPA                    | Vite em `:5173`, Nginx faz proxy  | Arquivos estáticos, Nginx serve do disco             |
| Processo Node contínuo | sim (serviço `frontend` do Compose) | **nenhum**                                         |
| Django                 | `runserver` (container ou nativo) | `gunicorn`, WSGI                                     |
| Deploy do front        | —                                 | copiar arquivos; rollback é copiar os anteriores     |
| Deploy do back         | —                                 | `migrate` **primeiro**, depois recarregar o gunicorn |

Não há contradição entre "o front é feito com Vite" e "sem Node em
produção": em produção o Vite é usado no **modo 2**, na sua máquina ou na
esteira de CI. O que vai para o servidor é a pasta de arquivos.

Produção roda, no total, `gunicorn` + `postgres` + `nginx`. É o desenho
que a infra já opera.

> O `docker-compose.yml` deste repositório é **o perfil de desenvolvimento**
> (`db` + `backend` + `frontend` + `nginx` + `mailpit`). Não existe compose
> de produção aqui: a infra de produção está descrita na seção 10 do
> `CLAUDE.md`, a alinhar com o time de infra.

---

## 8. Quem entra onde

O Django Admin é ferramenta de **operação da plataforma**: criar programas
novos, ler auditoria e corrigir dado quando o sistema errou. Só
superusuário entra, e a trava é de código, não combinado.

Todo usuário do programa — secretaria, coordenação, docentes, discentes —
é atendido **pelo frontend**. Se falta tela para alguma coisa, o trabalho
é escrever a tela, não dar acesso ao Admin. Ver
[ADR-006](docs/adr/006-admin-so-para-sysadmin.md).

Correção de dado pelo Admin é **quebra-vidro**, não rotina, e é sempre
auditada.

---

## 9. Armadilhas conhecidas

Todas estas já custaram tempo a alguém. Comece por aqui quando algo não
funcionar.

**A tela não carrega, ou o login falha sem motivo aparente.**
Você abriu `:5173`. Use `:8080`.

**A tela não carrega e a 8080 devolve erro de gateway.**
O serviço `frontend` caiu. Veja o log com `make web`; erro de dependência
nativa (`cannot find module` de algo que está no `node_modules`) costuma
significar `npm ci` rodado noutra plataforma — refaça no host.

**A página abre mas não atualiza sozinha ao salvar um `.svelte`.**
O hot reload perdeu o WebSocket. O `hmr.clientPort` do `vite.config.ts` sai
de `NGINX_PORT`: se a stack está publicada numa porta e o `.env` diz outra,
o navegador pede o reload no endereço errado — e nada na tela acusa isso.

**`/admin` devolve a SPA ou uma página estranha.**
Falta a barra final: `/admin/`.

**Mudei o `nginx.conf` e nada aconteceu.**
O arquivo é montado, mas o Nginx só relê a configuração ao recarregar:

```bash
docker compose up -d --force-recreate nginx
```

**O Postgres não sobe, erro de porta já alocada.**
A 5432 desta máquina costuma estar ocupada por outro projeto. O nosso usa
a **5433** no host (`DB_HOST_PORT` no `.env`); dentro do Compose continua
sendo `db:5432`.

**Trocar a versão _major_ do Postgres quebra o banco.**
O Postgres não lê um data dir criado por outra major. O caminho é
`pg_dump` → remover o volume → subir a nova imagem → restaurar. Nunca só
trocar a tag.

**`ModuleNotFoundError: No module named 'django'` dentro do container.**
O `python` do container é o do sistema; o ambiente do projeto está em
outro lugar. Use `uv run python ...`.

**`make test` falha sem conseguir conectar no banco.**
O Postgres precisa estar de pé: `make db`.

**O TypeScript reclama de um campo que existe na API.**
Você mexeu no schema e não rodou `make gen-api`. O `schema.d.ts` é gerado
— nunca o edite à mão.

**A regra de negócio "não pegou" numa edição feita pelo Admin.**
Comportamento esperado e documentado: o Admin edita campo direto e não
passa pelos métodos do model. É exatamente por isso que ele é restrito a
sysadmin (ADR-006).

**Adicionei um pacote com `uv add` e o container quebra com
`ModuleNotFoundError`.** A imagem continua a antiga. `docker compose up -d
--build backend` e, junto, `docker compose restart nginx` — o `upstream`
resolve `backend:8000` uma vez e o container novo ganha IP novo.

**O e-mail "não saiu".** Em desenvolvimento ele nunca sai: está no Mailpit
([seção 11](#11-e-mail-em-desenvolvimento-o-mailpit)). Em teste, sem
`django_capture_on_commit_callbacks(execute=True)` o `on_commit` não roda e
a caixa fica vazia em silêncio.

**Rota nova no front quebra o `make typecheck` com `EACCES` em
`.svelte-kit/`.** O Vite do container regenerou os artefatos como root.
Apague-os de dentro do container (o comando exato está na seção "Além dos
gates" do `CLAUDE.md`) e rode de novo.

**Upload em `PATCH` chega vazio.** O Django só parseia `multipart` em
`POST`. Rota que recebe arquivo é `POST`, sempre.

As demais armadilhas que já custaram uma iteração — `prefetch_related`
inútil, `isnull` em relação ausente, texto dentro de PDF, `openapi-fetch`
estreitando para `never` — estão registradas na seção "Além dos gates" do
[`CLAUDE.md`](CLAUDE.md), que é onde o loop autônomo as relê.

---

## 10. Os módulos de negócio por dentro

O que cada módulo faz está no Manual do Usuário. Aqui vai o que **não** se
vê pela tela: onde a regra mora, qual service é o portão de cada transição
e o que trava o quê. Vale ler o módulo inteiro antes de mexer num pedaço.

### Identidade, papéis e tenant

- **Usuário é global; pessoa é do programa.** `User` (app `accounts`) não
  tem `program`. Quem tem é `Person`, e uma conta pode estar ligada a mais
  de uma pessoa (uma por programa). `current_program(request)`
  (`apps/core/tenancy.py`) sai da(s) `Person` **ativa(s)** do usuário — e é
  chamado logo depois do `require_perm` em toda rota de negócio.
- **Papel é `Group`**, criado por data migration em cada app: Secretaria e
  Coordenação nascem em `programs`, Discente e Docente em `academic`,
  Candidato e "Cadastro pendente" nas migrations do autocadastro, Comissão
  de Seleção em `selection`, Comissão de Bolsas em `scholarships`. Nenhum
  recebe `delete_*`, `is_staff` ou `is_superuser`.
- **Autocadastro** (`AccessRequest`, app `academic`, rotas `/access/`):
  `signup_access_request` valida a senha **antes** de consultar o banco e
  responde o mesmo corpo para e-mail novo e já existente (anti-enumeração).
  Candidato sai com o Group e sem solicitação; docente e discente saem com
  a solicitação `pending` e o Group "Cadastro pendente", cuja lista de
  permissões é **vazia** — o porteiro é `approve_access_request`, que cria
  `Teacher` ou `Student` na mesma transação. `reject_access_request` grava
  o motivo e **arquiva a `Person`**: é o arquivamento que tranca, porque
  `current_program()` só enxerga pessoa ativa. O recusado não se recadastra
  (`unique_email_por_programa`).

### Disciplina isolada (app `academic`)

`IsolatedEnrollmentCycle` é o edital do semestre, com seis marcos de data
em ordem; `DisciplineOffering` a oferta com docente e vagas;
`IsolatedEnrollmentRequest` a inscrição, com até dois itens. As decisões da
secretaria (`enroll_isolated_request`, `close_isolated_cycle`) e o acerto
de matrícula (`create_enrollment_adjustment`) estão em
`apps/academic/services.py`; a classificação do docente é permissão própria
(`rank_disciplineoffering`). São as funções marcadas `review_required` no
`CLAUDE.md`: escrevem no banco e só, mas decidem a vida acadêmica de alguém.

### Processo seletivo (app `selection`)

1. **Edital** — `SelectionProcess` (Regular/Suplementar), `SelectionStage`
   em ordem, grade de `Vacancy` (nível × categoria de cota) e template de
   convocação. **Publicar é `publish_process`**, nunca `status = "published"`
   na mão: é o service que cobra etapa, vaga e template. Depois, etapa e
   vaga só se escrevem em `draft`.
2. **Bancas** — uma `Board` por (nível × alvo × etapa). Examinador externo é
   `Teacher` com `category = EXTERNAL` e `home_institution` obrigatória;
   normalmente não tem conta, e por isso assina por token.
3. **Inscrição pública** — rotas `/selection/public/*`, `auth=None`, rate
   limit e `csrf_protect` explícitos. O tenant sai do edital encontrado.
   `required_document_kinds()` decide os anexos pelo tipo do edital e pela
   cota. O candidato recebe um protocolo, que é o segredo da consulta.
4. **Homologação** — só inscrição homologada entra em banca.
5. **Notas** — `GET /boards/mine` lista as bancas do docente; lançamento em
   lote. Com a ata `frozen` ou `signed`, o lançamento recusa com
   `record_frozen`.
6. **Ata** — `generate_record` monta o conteúdo a partir das notas,
   `refresh_record` reconstrói em rascunho, `freeze_record` congela (hash,
   tokens, e-mail ao externo), `reopen_record` desfaz enquanto ninguém
   assinou. Ata assinada não se apaga: retifica-se com versão nova
   (`ExaminationRecord.supersedes`).
7. **Assinaturas** — `sign_record` (logado) e `sign_record_with_token`
   (externo, em `/selecao/assinatura/<token>`). **Na última assinatura**
   `_close_stage` roda: promove, elimina abaixo do corte, aprova na etapa
   final e gera o PDF.
8. **Convocação** — lote e linhas `pending` gravados **dentro** da
   transação; envio **fora** dela, um destinatário por vez; falha de SMTP
   vira `ConvocationEmail` com status `failed`, nunca 500.
9. **Resultado** — `compute_ranking` exige a ata da etapa final assinada.
   `reallocate_vacancy` (Comissão) invalida a classificação.
   `convert_to_student` cria ou reaproveita a `Person` e cria o `Student`.

### Bolsas (app `scholarships`)

- **Enums no nível do módulo**, com nome único (`ScholarshipEditionStatus`,
  `PriorityBand`…): é a regra deste app, por causa do gerador de tipos.
- `ScholarshipEdition` anda só para frente; cada transição é um método do
  model chamado por um `POST .../editions/{id}/<transição>`. Não há volta
  ao rascunho: correção é quebra-vidro no Admin.
- `ScholarshipApplication` copia e congela o nível do aluno. `BaremeEntry`
  é o lançamento do discente; `ItemReview` a avaliação da comissão
  (`review_baremeentry`, permissão separada de `change_` de propósito).
  Upload de comprovante é `POST .../entries/{id}/proof`; os demais campos
  vão no `PATCH`.
- A secretaria escreve só dois campos na inscrição alheia, cada um com
  permissão própria: `set_fump_level` e `override_band`.
- `ScholarshipEdition.result(level)` calcula as dez faixas ao vivo;
  `publish_preliminary`/`publish_final` (`services.py`) gravam um
  **snapshot**, e `published_result` é o que tela e PDF leem. Regra de
  classificação é `review_required`: teste verde não prova critério certo.
- `ScholarshipAppeal` é um por inscrição; `judge()` recebe o desfecho
  (deferido, parcial, indeferido) e a fundamentação.

### O que o `make seed` deixa pronto

Nos **dois** programas: editais de seleção publicados, quatro bancas (uma
com externo), inscrições em todos os status, uma ata assinada com PDF, um
lote de convocação enviado, uma matrícula feita, duas edições de bolsa (a
do ano anterior e a do ano, com barema clonado) e candidatos em vários
estágios, ciclo de isolada com inscrições, autocadastro ligado. O PPGA é o
tenant limpo; o PPGD do seu checkout pode carregar dado de sessões
anteriores, porque a carga **adota** o que já existe.

---

## 11. E-mail em desenvolvimento: o Mailpit

Todo e-mail do sistema — token de assinatura, convocação — sai por
`django.core.mail`, síncrono e sem fila (ADR-009). No Compose o destino é o
serviço `mailpit`: SMTP em 1025, tudo em memória (`MP_MAX_MESSAGES=500`,
sem volume — o histórico some no `down`) e **nada sai para a internet**. É
isso que torna seguro exercitar convocação e link de assinatura aqui.

A UI não é publicada. Para abri-la, `docker compose port mailpit 8025` e
use a porta que ele imprimir. Para ler as mensagens sem UI — **a imagem do
backend não tem `curl`**:

```bash
docker compose exec -T backend python -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://mailpit:8025/api/v1/messages'))
print(d['total'])
for m in d['messages'][:5]:
    print(m['From']['Address'], '->', [t['Address'] for t in m['To']], '|', m['Subject'])
"
```

O corpo de uma mensagem (é dele que se colhe o link de assinatura) sai em
`/api/v1/message/<ID>`.

Fora do Compose, quem manda são as variáveis de ambiente: `EMAIL_BACKEND`
(default **console**, para que ambiente sem configuração não tente falar
com servidor nenhum), `EMAIL_HOST/PORT/USE_TLS/HOST_USER/HOST_PASSWORD`,
`DEFAULT_FROM_EMAIL` e **`SITE_URL`**, com que se montam os links. Em
teste o `pytest-django` troca o backend por `locmem` sozinho: teste de
e-mail lê `django.core.mail.outbox`, sem mock — e precisa de
`django_capture_on_commit_callbacks(execute=True)`, senão o `on_commit` não
roda e a caixa fica vazia em silêncio.
