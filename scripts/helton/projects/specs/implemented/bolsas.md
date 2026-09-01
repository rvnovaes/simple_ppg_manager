

Pular para o conteúdo
Como usar o Gmail com leitores de tela
1 de 1.019
Bolsas.md
Caixa de entrada
Roberto Novaes <rvnovaes@gmail.com>
	
Anexos08:09 (há 4 minutos)
	
	
para mim

		
Roberto Vasconcelos Novaes
Professor Adjunto
Professo Permanente do PPGD 
Coordenador do Colegiado de 
Ciências do Estado

+55 31 9 8447 9085
	


www.robertonovaes.com.br
rnovaes@ufmg.br
rvnovaes@gmail.com
	
 1 anexo
  •  Verificados pelo Gmail

# Concessão de Bolsas — Grill / Discovery Notes
Date: 2026-08-31 · Goal: extrair a spec completa do processo de concessão
de bolsas do PPGD aos alunos — insumo para `plans/bolsas.md` (sessão nova
em plan mode). O grill extrai; não redige o plano.

## Glossário
- **Comissão de Bolsas** (nome completo: Comissão de Bolsas e Estágios de
  Docência do PPGD) — docentes; analisa as candidaturas. Quando falta gente, a
  Coordenação designa docente *ad hoc*, ad referendum do Colegiado.
- **Colegiado do PPGD** — julga os recursos e publica o resultado final;
  também decide caso omisso e prorrogação de validade do edital.
- **Barema** — tabela de pontuação de mérito científico, um por nível
  (Anexo I = mestrado, Anexo II = doutorado). Seis seções, cada item com
  pontos por unidade e teto próprio.
- **FUMP** — Fundação Universitária Mendes Pimentel; faz a análise
  socioeconômica e devolve um **nível** de vulnerabilidade. Manda o resultado
  direto para a Comissão de Bolsas (fora do sistema).
- **CadÚnico** — Cadastro Único do Governo Federal; via alternativa de
  comprovação de vulnerabilidade.
- **Cumulação/acúmulo** — receber a bolsa junto com atividade remunerada ou
  outros rendimentos. Só entra nas bolsas que sobram depois de atendida a
  lista sem acúmulo.
- **Implementação** — o momento em que a bolsa é efetivada junto à agência
  (CAPES/CNPq/FAPEMIG). É aí que se afere o acúmulo.
- **Cota/quota** — bolsa disponível, que chega por fluxo ao longo do ano.

## Contexto já estabelecido (lido do repositório — NÃO perguntar de novo)
- **Stack e arquitetura**: `CLAUDE.md`. Django 5 LTS + Ninja + Postgres,
  SvelteKit `adapter-static`, origem única no Nginx. Model = entidade,
  regra de negócio em método de model, `services.py` só quando a operação
  cruza vários models. Admin só para sysadmin — toda tela de usuário de
  negócio é Svelte.
- **Multi-tenant por `Program`**: todo model de negócio carrega FK
  `program` direta (ADR-007). Exceção: `AcademicTerm` (institucional).
- **Já implementado** em `backend/apps/`: `people` (`Person`), `programs`
  (`Program`, `ResearchLine`, `CollectiveProject`, `Discipline`,
  `AcademicTerm`), `academic` (`Teacher`, `Student`, acerto de matrícula,
  ciclo completo de disciplinas isoladas), `accounts`, `audit`, `core`.
- **`Student`** já tem: `modality` (regular/isolada/eletiva) × `status`
  (ativo/trancado/excluído), `level` (mestrado/doutorado), `project`
  (projeto coletivo), `advisor` (`Teacher`), `admission_date`,
  `deadline`, `defense_date`, `term`, `registration_number`.
  `PRAZO_EM_ANOS = {mestrado: 2, doutorado: 4}`.
- **Specs já levantadas, ainda não implementadas**: `specs/processo-seletivo.md`
  e `specs/bancas-projeto-coletivo.md`.
- **Precedentes de corte**: isoladas não geram GRU nem conciliação
  financeira, não têm SMTP nem agendador (nada expira sozinho). Processo
  seletivo rompeu o corte de SMTP e de PDF — ambos pedem ADR.

## Corpus normativo lido (fonte: Dropbox do usuário, `.../PPGD/Simple PPGD`)
1. **Edital nº 353/2026 — Seleção de Bolsas Mestrado e Doutorado** (23/02/2026):
   inscrição em 2 dias (17-18/03), plataforma própria; ordem de prioridade da
   CEPE 08/2023; barema; bonificação FUMP (nível 1 = +15 pts, nível 2 = +9 pts);
   desempate em 5 níveis terminando em sorteio; Comissão de Bolsas analisa;
   resultado preliminar → recurso em 2 dias → resultado final pelo Colegiado
   em 5 dias; convocação por ordem de classificação conforme a disponibilidade;
   declínio por perfil de agência mantém a posição, recusa por outro motivo
   joga para o fim da lista; documentação de implementação (item 9); estágio de
   docência obrigatório para bolsista; **validade de 10 meses**.
2. **Resolução CEPE 08/2023 (UFMG)** — diretrizes institucionais: Art. 3º
   (prioridade sem acúmulo: I ações afirmativas/vulnerabilidade, II demais),
   Art. 6º-7º (acúmulo só no que sobra, com 9+1 critérios de prioridade),
   **Art. 8º (revisão da distribuição a cada 12 meses, com aviso de 30 dias
   antes de redistribuir bolsa ocupada)**, Art. 9º (bolsista deve comunicar
   mudança de imediato; omissão gera suspensão/cancelamento e cobrança de
   parcelas).
3. **Resolução PPGD nº 3, de 26/02/2024** — edital anual; barema revisto
   anualmente pela Comissão; recurso ao Colegiado; declínio/reclassificação
   (art. 6º e 7º); **Art. 8º: relatórios trimestrais obrigatórios, entregues no
   mês seguinte ao trimestre; não entrega pode revogar a bolsa**.
4. **Anexos I e II — Baremas de mestrado e doutorado**: seções I Formação
   Acadêmica, II Produção Bibliográfica, III Eventos, IV Experiência
   Profissional, V Bancas Examinadoras, VI Outros Títulos. Cada item tem
   unidade (semestre, mês, hora, item) × pontos × teto.
5. **Ata do Colegiado de 06/11/2025** — pedidos de cumulação julgados caso a
   caso pelo Colegiado, com parecer da Comissão; parâmetros fixados para bolsa
   complementar: (a) não concorrer com a pesquisa, (b) valor ≤ 50% da bolsa,
   (c) carga horária < 20h/semana. Regra que aparece na prática: não há
   cumulação enquanto houver classificado sem bolsa que a queira sem acúmulo.

## Decisões fechadas (TL;DR)
- **Escopo do KPG: só a seleção.** Cadastro dos inscritos → questionário de
  prioridade → coleta de documentos → análise da comissão item a item →
  classificação. A vida da bolsa (convocação, lista de espera, implementação,
  relatórios trimestrais, cumulação, revisão anual do Art. 8º da CEPE 08/2023)
  continua em planilha, fora do sistema.
- **Ciclo anual fechado**: um edital por ano; publicada, a lista vale para
  aquele ano e não é reaproveitada. Bolsista atual não se reinscreve; não
  contemplado concorre ao edital do ano seguinte.
- **Aluno preenche a própria inscrição**, logado. Secretaria só abre a edição e
  a janela. Sem trava automática de elegibilidade.
- **Barema é dado**, cadastrado pela Secretaria, clonável de uma edição para a
  seguinte e congelado na abertura da janela. Nota do lançamento = quantidade ×
  pontos/unidade, com teto por item.
- **Questionário é fixo em código** (8 perguntas amarradas aos incisos da CEPE
  08/2023).
- **Comprovante obrigatório para salvar o lançamento**; um arquivo por
  lançamento; visível só para Comissão e Secretaria; retenção indefinida.
- **Duas pontuações paralelas por lançamento** (candidato × comissão), com
  observação escrita obrigatória quando divergem.
- **Comissão é corpo único**: qualquer membro avalia qualquer lançamento, sem
  relator nem dupla avaliação; altera apenas nota e observação.
- **O KPG classifica** — hoje a ordem é montada na planilha. A ordenação depende
  da faixa; a nota publicada já inclui a bonificação FUMP.
- **Seis estados de edição**, transição sempre manual da Secretaria, sem
  agendador. O aluno só vê nota e observações a partir do resultado preliminar.
- **Recurso: texto único por candidato, sem documento novo.** A Comissão
  registra o julgamento; o Colegiado não é ator do sistema. Deferimento reabre
  lançamentos e recalcula a nota.

## Spec consolidada

### Atores e papéis
| Papel | O que faz no KPG |
|---|---|
| **Aluno candidato** | Preenche questionário, lança itens do barema com comprovante, acompanha o próprio resultado, interpõe recurso. |
| **Secretaria** | Cria a edição, cadastra o barema, abre e fecha cada fase, lança o nível FUMP, publica preliminar e final, registra ordem de sorteio quando houver. |
| **Comissão de Bolsas** | Avalia lançamento a lançamento (nota + observação), lê comprovantes, registra o julgamento dos recursos. |
| *(fora do sistema)* Colegiado | Julga formalmente o recurso em reunião; a decisão entra no KPG pela Comissão. |
| *(fora do sistema)* FUMP | Faz a análise socioeconômica e manda o resultado à Comissão; o nível é digitado pela Secretaria. |

### Entidades (esboço, sujeito ao plano)
- **Edição do edital** — ano, nível(is), datas informativas do cronograma,
  estado, FK `program`. Uma por ano.
- **Item de barema** — (edição, nível, seção, código "1.3", texto, unidade
  [semestre/mês/hora/unidade], pontos por unidade, teto). Clonável entre edições,
  congelado quando a janela abre.
- **Inscrição** — (edição, `Student`), respostas do questionário, valor de
  rendimento e carga horária semanal quando há atividade remunerada, nível FUMP
  lançado pela Secretaria, faixa derivada, nota final, estado da análise.
- **Lançamento** — (inscrição, item de barema, descrição livre, quantidade,
  nota do candidato, nota da comissão, observação da comissão, comprovante).
  Comprovante obrigatório; um arquivo por lançamento.
- **Recurso** — (inscrição, texto do candidato, resultado ∈ {deferido, deferido
  parcialmente, indeferido}, fundamentação). Um por inscrição.
- Escopo de tenant por `program` em tudo, conforme ADR-007.

### Máquina de estados da edição
| Estado | Quem entra | O que muda |
|---|---|---|
| Rascunho | Secretaria | monta edição e barema; invisível ao aluno |
| Inscrições abertas | Secretaria | **barema congela**; aluno lança e anexa |
| Em análise | Secretaria | aluno não mexe mais; comissão avalia |
| Resultado preliminar | Secretaria | aluno vê nota, cortes e observações; abre recurso |
| Recursos em julgamento | Secretaria | prazo de recurso fechado; comissão julga |
| Resultado final | Secretaria | congela tudo; lista definitiva do ano |

As datas do cronograma do edital são cadastradas como informação. **Nada abre ou
fecha por relógio** — mesmo corte das isoladas.

### Algoritmo de classificação
1. **Nota da comissão** = soma dos lançamentos, cada item respeitando seu teto.
2. **Nota final** = nota da comissão + bonificação FUMP (nível 1: +15; nível 2: +9).
3. **Faixa** derivada do questionário. `possui atividade remunerada` é a chave:
   - **Não** → bloco 2.1: se ação afirmativa **ou** vulnerabilidade → **2.1-I**,
     senão **2.1-II**.
   - **Sim** → bloco 2.4: **primeiro inciso aplicável** na ordem I→IX; se nenhum
     se aplica → **faixa residual**.
4. **Ordenação dentro da faixa**:
   - 2.1-I, 2.1-II, 2.4-I…IV, 2.4-IX e residual → **nota final**, decrescente.
   - **2.4-V** → menor rendimento mensal; desempate por nota.
   - **2.4-VI+VII+VIII** (faixa única) → menor rendimento; depois menor carga
     horária; depois nota.
5. **Desempate geral** (item 3.3 do edital), aplicado quando o critério da faixa
   não resolve: I menor nível FUMP → II CadÚnico → III maior subtotal em
   "Formação Acadêmica" → IV maior subtotal em "Publicações" → V **sorteio**.
6. Uma lista por **nível** (mestrado e doutorado correm independentes).

### Saída
Um documento por nível, com **as 9 faixas normativas + a residual, publicadas
mesmo quando vazias**, cada seção com seu título, o rótulo "Ordem de prioridade:
N" e a regra de ordenação escrita no cabeçalho. Colunas: Nome, Nota do Barema,
Classificação — mais **Remuneração** nas faixas 2.4-V e 2.4-VI/VII/VIII.

### Cortes deliberados
- Sem convocação, lista de espera, declínio ou reclassificação.
- Sem controle de cota, agência de fomento ou implementação.
- Sem relatório trimestral, cumulação ou revisão anual.
- Sem agendador; sem trava de elegibilidade; sem papel "Colegiado".
- Documento novo em recurso é **proibido** (item 1.3 do edital) — ao contrário
  das isoladas.

### Pontos que exigem gate humano / ADR
- Todo o **algoritmo de classificação** e os desempates (CLAUDE.md, gate 3).
- Se o KPG for **gerar o PDF do resultado**, é precedente novo — só o processo
  seletivo abriu essa porta (ver flag em aberto).
- Migrations e contrato de API, como sempre.

## Q&A log

### Q1 — Onde começa e onde termina o processo dentro do sistema
- Asked: o sistema gerencia a fila e a concessão (cotas, candidatura,
  classificação, substituição, encerramento) ou também a vida mensal da bolsa?
- Captured: "inicialmente temos apenas o **processo seletivo** no KPG. O
  gerenciamento da **vida da bolsa** é feito em planilhas." Usuário entregou o
  corpus normativo acima para leitura (edital, 2 resoluções, 2 baremas, ata).
- Flags: fronteira exata entre "processo seletivo" e "vida da bolsa" ainda a
  definir (Q2) — convocação e lista de espera ficam de que lado?

### Q2 — Onde exatamente termina o processo seletivo no KPG
- Asked: o KPG vai até a manutenção da lista classificada durante os 10 meses
  de validade (convocação, declínio, reclassificação), ou para no resultado final?
- Captured: **para antes disso.** "O KPG só faz a **seleção**", que consiste em:
  1. **cadastro dos alunos inscritos**;
  2. **aplicação de um questionário** que filtra os critérios de prioridade das
     resoluções (CEPE 08/2023 e Resolução PPGD nº 3);
  3. **coleta dos documentos**;
  4. **a comissão acessa os documentos no KPG e os alunos são classificados**.
  Fora do KPG, em planilha: convocação, lista de espera, declínio,
  reclassificação, implementação, relatórios trimestrais, cumulação, revisão
  anual do Art. 8º da CEPE 08/2023.
- Flags: nenhum.

### Q3 — Quem se inscreve e como entra no sistema
- Asked: candidato é `Student` regular ativo (mestrado/doutorado) sem
  auto-registro? Bolsista atual pode se inscrever? Há trava de elegibilidade?
- Captured: "**o aluno bolsista não se inscreve de novo**". O ciclo é anual e
  fechado: "uma vez gerada uma lista para o edital do ano x, o resultado é
  publicado e **é definitivo para o ano**". "No ano seguinte o aluno não
  contemplado pode concorrer ao **novo edital**." Ou seja: uma edição de edital
  por ano, lista congelada depois de publicada, sem reabertura no meio do ano —
  e a lista não é reaproveitada no ano seguinte, o não contemplado se reinscreve.
- Flags: **recursos ainda serão modelados** ("ainda vamos modelar os recursos")
  -> tratar em bloco próprio mais adiante nesta entrevista.

### Q4 — Quem preenche a inscrição e quem o sistema deixa entrar
- Asked: o próprio aluno logado preenche questionário + lançamentos do barema +
  comprovantes (Secretaria só abre o edital)? E não há trava automática contra
  bolsista se inscrever?
- Captured: "**sim, o aluno preenche sozinho e sem trava automática**".
  Secretaria abre a edição do edital e a janela; não digita inscrição de
  ninguém. O sistema não sabe quem é bolsista (isso vive na planilha) — "bolsista
  não se inscreve" é regra de fato, conferida pela comissão.
- Flags: nenhum.

### Q5 — Barema é dado cadastrado ou tabela fixa em código
- Asked: barema como dado versionado por edição+nível, clonável do ano anterior
  e congelado na abertura da janela? Quem cadastra?
- Captured: "**sim, barema clonável e congelado; queremos que a secretaria
  cadastre as regras do barema**". Confirmada também a aritmética observada no
  print: nota do lançamento = **quantidade × pontos por unidade**, com **teto
  aplicado na soma do item** (1 semestre × 0,50 = 0,50; 12 meses × 0,25 = 3,00,
  exatamente o teto; 3 horas × 0,01 = 0,03).
- Consequência aceita: editar o barema depois da janela aberta invalidaria notas
  já lançadas — por isso congela.
- Modelo implícito: item de barema = (edição, nível, seção, código "1.3", texto,
  unidade [semestre/mês/hora/unidade], pontos por unidade, teto).
- Flags: quem revisa o barema pela Resolução nº 3 é a Comissão, mas quem
  **cadastra no sistema** é a Secretaria — a revisão acontece fora do KPG.

### Q6 — O sistema classifica ou só pontua?
- Asked: o KPG deriva a categoria e entrega as listas ordenadas, ou só pontua e
  filtra como o legado, deixando a ordem para a comissão?
- Captured: "**o sistema classifica; hoje a comissão monta a ordem na
  planilha**". Confirma o diagnóstico: o legado pontua e filtra, e a ordenação
  final é trabalho manual em planilha — é justamente isso que o KPG elimina.
- Consequência: o algoritmo das resoluções (faixas 2.1-I, 2.1-II, depois 2.4-I a
  2.4-IX; nota do barema + bonificação FUMP; desempate em 5 níveis) vira código.
  **É human gate** pelo CLAUDE.md ("regra de classificação e contagem de vaga").
- Flags: sorteio (5º critério de desempate) — provavelmente ato manual
  registrado, confirmar mais adiante.

### Q7 — O que ordena dentro de cada faixa: nota ou critério da faixa?
- Asked: dentro da faixa, ordena a nota do barema (com "menor rendimento" só
  como desempate) ou o critério do inciso prevalece sobre a nota?
- Captured: resolvido pela leitura dos resultados publicados
  (`Resultado-Final-Mestrado.pdf`, `Resultado-Preliminar-Doutorado.pdf`, edição
  2026): **depende da faixa**, e o próprio documento publica a regra de
  ordenação no cabeçalho de cada seção.
- **Depende da faixa** (regra confirmada nos dados):
  - 2.1-I, 2.1-II, 2.4-I e a faixa residual: ordena por **nota do barema**,
    decrescente.
  - 2.4-V: "Classificação com base no **menor rendimento mensal**, prevalecendo
    a nota do Barema como critério de desempate".
  - 2.4-VI+VII+VIII (faixa única): "menor rendimento mensal, prevalecendo a
    **menor carga horária** em caso de empate e prevalecendo a **nota do
    Barema** caso o empate persista".
  - Prova nos dados: no mestrado, faixa VI/VII/VIII, Amanda Pereira Reis (59,20)
    é 1ª e Ana Rita Fontes Nascimento (73,29) é 5ª — a nota não ordena ali.
- Flags: nenhum. A dúvida do edital (item 3.1 × incisos do 2.4) está resolvida.

### Q8 — Faixas ausentes (2.4-II e 2.4-III) e a faixa residual
- Asked: gerar sempre as faixas II e III, mesmo vazias? A faixa residual
  ("fora dos critérios") é categoria de verdade no modelo?
- Captured: "**sim, gera as nove faixas sempre e a residual como oitava**".
  Logo: o conjunto canônico de faixas é fixo e completo, e "nenhum inciso se
  aplica" é estado válido — o sistema não força ninguém dentro de um inciso.
- Faixas normativas (9 seções, com VI/VII/VIII agrupados como uma só):
  2.1-I · 2.1-II · 2.4-I · 2.4-II · 2.4-III · 2.4-IV · 2.4-V ·
  2.4-VI+VII+VIII · 2.4-IX — **+ residual** ao final.
- Flags: o rótulo "Ordem de prioridade: N" muda ao incluir II e III — a residual
  deixa de ser "oitava" (como em 2026) e passa a **décima**. Confirmar o texto
  publicado.

### Q9 — Bonificação FUMP: por onde entra e onde aparece
- Asked: quem lança o nível FUMP, e a "Nota do Barema" publicada inclui o bônus?
- Captured: "**a nota publicada já contém a FUMP. A secretaria soma ao final.**"
  Ou seja: a coluna "Nota do Barema" do resultado é **nota da comissão + bônus
  FUMP** (+15 para nível 1, +9 para nível 2, item 3.2 do edital). Hoje a soma é
  manual, feita pela Secretaria ao fechar a lista — no KPG passa a ser calculada.
- Quem lança o nível: **Secretaria** (a FUMP manda o resultado direto à Comissão,
  fora do sistema; o aluno não digita nem anexa). O nível fica guardado porque é
  também o **1º critério de desempate** (item 3.3, I: menor nível FUMP).
- Flags: nenhum.

### Q10 — O trabalho da comissão: quem avalia e o que pode alterar
- Asked: comissão como corpo único sem distribuição? Altera só nota e
  observação, nunca o que o aluno digitou? Observação obrigatória na divergência?
- Captured: "**corpo único, qualquer membro avalia qualquer lançamento**".
  Sem relator, sem divisão por linha de pesquisa, sem dupla avaliação — último a
  salvar vence. O filtro "somente candidatos com itens a analisar" é a fila de
  trabalho.
- Desenho aceito junto: a comissão mexe **só na nota da comissão e na
  observação**; item, descrição e quantidade são do aluno e ficam intocados (se
  a quantidade está errada, zera-se a nota e se escreve o porquê). Observação
  **obrigatória quando a nota da comissão difere da do candidato** — é a
  fundamentação que o recurso ataca. "Todos itens avaliados" é **derivado**
  (nenhum lançamento pendente), não um botão.
- Flags: nenhum.

### Q11 — Comprovantes: quantos, obrigatórios em quê, quem vê
- Asked: um arquivo por lançamento, obrigatório para salvar? Documento também
  em respostas do questionário? Visibilidade e retenção como nas isoladas?
- Captured: "**obrigatório para salvar o lançamento**" — sem comprovante o
  lançamento não existe; a comissão nunca recebe item vazio para zerar.
- Desenho proposto junto (não contestado): um arquivo por lançamento, PDF, com
  limite de tamanho; visível **só para Comissão e Secretaria**; guardado
  **indefinidamente**, sem expurgo — mesmo precedente das isoladas. Documentos do
  item 9 do edital (implementação) ficam fora do KPG.
- Flags: **quais respostas do questionário exigem documento** ainda em aberto —
  o export mostra `vulnerabilidade: Sim - Não enviado`, então pelo menos essa
  exige. Confirmar na Q12.

### Q12 — Questionário: dado cadastrável ou fixo em código?
- Asked: perguntas fixas em código (ligadas aos incisos) em vez de dado
  editável? E a tabela de o que cada resposta "Sim" exige?
- Captured: "**sim**" para as duas coisas.
- **Perguntas fixas em código**, uma a uma amarradas aos incisos da CEPE
  08/2023 — pergunta editável deixaria o algoritmo de classificação órfão, e
  mudança de norma é mudança de código (com ADR), não de cadastro.
- Mapa pergunta → faixa: ações afirmativas e vulnerabilidade → 2.1-I; professor
  substituto → 2.4-III; educação básica/saúde coletiva → 2.4-IV; serviço público
  → 2.4-V; serviço privado → 2.4-VI; outra bolsa não pública → 2.4-IX;
  **"possui atividade remunerada" é a chave** que joga o candidato do bloco 2.1
  para o bloco 2.4.
- O que cada "Sim" carrega: **atividade remunerada** → valor do rendimento +
  carga horária semanal (é o que ordena as faixas V e VI/VII/VIII); **todas as
  demais** → documento comprobatório anexado.
- Flags: resolvido o flag da Q11.

### Q13 — Fases da edição e o que o aluno vê em cada uma
- Asked: máquina de estados com transição manual da Secretaria, sem agendador, e
  o aluno só vendo nota/observações depois do preliminar?
- Captured: "**sim, é isso mesmo**".
- Estados: **rascunho** (Secretaria monta edição + barema; invisível) →
  **inscrições abertas** (barema congela; aluno lança e anexa) → **em análise**
  (janela fechada; aluno não mexe; comissão avalia) → **resultado preliminar
  publicado** (aluno passa a ver sua nota, os cortes e as observações; abre
  recurso) → **recursos em julgamento** (prazo de recurso fechado) →
  **resultado final publicado** (congela tudo; lista definitiva do ano).
- **Sem agendador**: as datas do edital são cadastradas como informação, mas
  toda transição é clique da Secretaria (mesmo precedente das isoladas).
- **A publicação do preliminar é o que revela as observações da comissão** — o
  aluno recorre vendo o corte item a item, não no escuro.
- Flags: nenhum.

### Q14 — O recurso
- Asked: recurso é texto único por candidato ou por lançamento? Quem registra o
  julgamento — Comissão ou um papel "Colegiado"?
- Captured: "**texto único por candidato, e quem lança é a comissão**".
- Desenho fechado: **um recurso por candidato por edição**, texto livre, aberto
  só na fase de recurso, só para inscrição avaliada; **sem documento novo**
  (item 1.3 do edital veta postagem fora do prazo — o oposto do recurso das
  isoladas, e a diferença vem da norma); julgamento com resultado **deferido /
  deferido parcialmente / indeferido** + fundamentação escrita (o "Análise do
  recurso" do legado).
- **Não existe papel "Colegiado" no sistema.** Formalmente quem julga é o
  Colegiado (Res. nº 3, art. 4º), mas ele não tem tela nem login: a Comissão dá
  o parecer, o Colegiado ratifica em reunião fora do KPG, e a Comissão registra
  o resultado.
- **Efeito do deferimento**: reabre os lançamentos citados para a Comissão
  corrigir nota e observação; a nota é **recalculada** e a lista final sai desse
  recálculo — é o que dá sentido a "deferido parcialmente".
- Flags: nenhum. (Resolve o flag aberto na Q3.)

## Estrutura do resultado publicado (fonte: PDFs de resultado 2026)

Um documento por **nível** (mestrado, doutorado), em **oito faixas** fixas, cada
uma com título, "Ordem de prioridade: primeira/segunda/..." e sua própria
tabela. Faixa vazia **é publicada mesmo assim**, só com o cabeçalho (foi o caso
de 2.4-IV e 2.4-IX nas duas listas de 2026).

| Ordem | Faixa | Colunas | Ordenação |
|---|---|---|---|
| primeira | Item 2.1, I | Nome, Nota do Barema, Classificação | nota desc. |
| segunda | Item 2.1, II | idem | nota desc. |
| terceira | Item 2.4, I | idem | nota desc. |
| quarta | Item 2.4, IV | idem | (vazia em 2026) |
| quinta | Item 2.4, V | Nome, **Remuneração**, Nota, Classificação | menor remuneração; desempate por nota |
| sexta | Item 2.4, VI, VII e VIII (agrupados) | Nome, Remuneração, Nota, Classificação | menor remuneração; desempate por menor CH; depois nota |
| sétima | Item 2.4, IX | Nome, Nota, Classificação | (vazia em 2026) |
| oitava | "Cumulação com atividade remunerada, **fora dos critérios de prioridade** do item 2.4" | Nome, Nota, Classificação | nota desc. |

Observações materiais:
- **Os incisos 2.4-II e 2.4-III não aparecem** em nenhuma das duas listas — nem
  vazios, ao contrário de IV e IX.
- A **oitava faixa não existe na norma**: é residual, para quem acumula e não se
  encaixa em nenhum inciso. Em 2026 ela é grande (8 no mestrado, 2 no doutorado).
- A coluna **Remuneração aparece como `###`** nos dois PDFs — sinal de planilha
  com coluna estreita, não necessariamente mascaramento deliberado.
- Nota 0,00 é classificada normalmente (candidato sem lançamento aproveitado).
- Volume 2026: mestrado 6+18+4+0+2+6+0+8 = **44**; doutorado 5+17+2+0+4+3+0+2 = **33**.
- Mestrado saiu como "Resultado Final", doutorado como "Resultado Preliminar" —
  os dois níveis correm em documentos independentes.

## Sistema legado (prints e export entregues pelo usuário)

Fonte: `filtros_bolsas.jpg`, `analise_aluno.jpg`, `modelo_resultado_classificacao`
— telas do sistema atual em `pos.direito.ufmg.br/acessorestrito`, edição 2026.
É o que o KPG vai substituir; serve de referência de comportamento observado.

**Tela "Análise de requerimentos de bolsa - 2026" (lista + filtros)**
- Filtros: Nível (único obrigatório — "Remover todos (exceto nível)"), Linha de
  Pesquisa, Orientador, Ano de entrada, e um filtro para **cada pergunta do
  questionário** (atividade remunerada, ações afirmativas, vulnerabilidade,
  professor substituto, educação básica/saúde coletiva, serviço público,
  serviço privado, outra bolsa não pública).
- Ordenação (no export: "Pelo nome do candidato"), filtro por Recursos.
- Dois toggles: "Exibir dados detalhados de cada candidato" e **"Exibir somente
  candidatos com itens a analisar"** (fila de trabalho da comissão).

**Export da lista (31 candidatos, edição 2026)** — por candidato: nº de ordem,
nome, ano de entrada, linha de pesquisa, orientador, as 8 respostas do
questionário (com **valores** quando "Sim": `Rendimentos: R$ 1400 - CH semanal:
20h`), a **nota**, o estado da análise ("Todos itens analisados") e o estado do
recurso. Vulnerabilidade aparece como `Sim - Não enviado` → a resposta e o
**documento comprobatório** são estados distintos.
Recursos observados: 25 "Não enviado", 1 "Deferido", 2 "Deferido parcialmente",
3 "Indeferido", cada um com links "Recurso do candidato" e "Análise do recurso".

**Tela de análise de um candidato** — o coração do sistema:
- Cabeçalho: candidato, nível, **"Pontuação: Candidato: 24,50 - Comissão:
  23,50"** (duas notas paralelas), estado "Todos itens avaliados", "Itens
  cadastrados: 15".
- Corpo agrupado pelas **seções do barema** (Seção I Formação Acadêmica, Seção
  III Eventos...), e dentro de cada seção pelo **item do barema**, com o texto
  normativo do item repetido como cabeçalho: `1.3 - Participação em grupo de
  estudos - 0,50 pts/semestre - Limite: 3,00`.
- Cada lançamento do candidato é uma linha: ID, descrição livre, **quantidade**
  (`1 Semestres`, `12 Meses`, `3 Horas`), **Nota candidato**, **Nota comissão**,
  link "Abrir" do comprovante, ação "Alterar avaliação".
- Abaixo de cada lançamento, quando a comissão diverge: **"Observação da
  comissão:"** em destaque, com a justificativa por escrito (ex.: "Não é
  possível computar a pontuação porque não está previsto no certificado a
  informação de que as atividades se deram no período igual ou superior a três
  meses."). Há também observação **por item do barema**, não só por lançamento.
- Cada item fecha com **"Nota total"** do item, com o teto aplicado (ex.:
  lançamentos de 3,00 + 3,00 no item 1.8 → total 6,00, limite 18,00).

### Q15 — Empates: até onde o sistema decide sozinho *(sem resposta)*
- Asked: sistema aplica os critérios I a IV do item 3.3 e para no sorteio, que
  vira ato humano registrado pela Secretaria? A cadeia III/IV usa os subtotais
  **da comissão**?
- Captured: usuário encerrou a especificação aqui — pergunta **não respondida**.
  A recomendação registrada (não confirmada): sistema aplica I-IV; empate
  remanescente fica marcado e a Secretaria lança a ordem sorteada, com data e
  justificativa auditadas; `random()` dentro do software não é auditável e a
  norma trata o sorteio como ato presencial da comissão.

## Open flags (pending input)
- **Sorteio (item 3.3, V)**: ato humano registrado ou função do sistema? -> usuário.
- **Subtotais do desempate III/IV**: da comissão (assumido) ou do candidato? -> usuário.
- **Geração do PDF de resultado**: o KPG monta os documentos por nível ou a
  Secretaria continua montando a planilha e o PDF à mão? Se o KPG gerar, é
  precedente que pede ADR (só o processo seletivo abriu essa porta). -> usuário.
- **Notificação por e-mail** (publicação de preliminar/final, resultado de
  recurso): manter o corte de SMTP das isoladas ou seguir o processo seletivo,
  que o rompeu? -> usuário.
- **Rótulo "Ordem de prioridade: N"** no documento publicado: com 2.4-II e
  2.4-III incluídas, a faixa residual passa de "oitava" para "décima". -> usuário.
- **Como a Comissão de Bolsas é modelada**: grupo de permissão fixo ou
  composição por edição (a ata de 06/11/2025 mostra a comissão sendo recomposta
  por consulta aos docentes). -> usuário.
- **Cancelamento/desistência de inscrição** e reabertura de janela: não
  levantados. -> usuário.
- **Vida da bolsa em planilha**: quando (e se) migrar para o KPG — hoje
  deliberadamente fora. -> usuário / Secretaria.

bolsas.md
Exibindo bolsas.md.