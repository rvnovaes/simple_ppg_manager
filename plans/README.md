# plans/ — a entrada da esteira

Um arquivo por plano de desenvolvimento aprovado, em Markdown:

```
plans/<nome>.md
```

**O nome do arquivo é a chave primária de tudo.** Ele precisa ser kebab-case
(minúsculas, dígitos e hífen simples), porque vira, sem tradução:

| a partir de `plans/onda-2.md` | vira |
|---|---|
| worktree | `../<projeto>-onda-2` |
| branch | `helton/onda-2` |
| projeto Compose | `<projeto>-onda-2` |

## Como um arquivo chega aqui

O começo são **três sessões distintas**, e a separação é a parte que mais se
perde ao contar a história rápido:

1. **Sessão de descoberta** — `/grill-me` sobre o problema. A saída é a spec,
   gravada em `specs/<tema>.md` a cada resposta. O grill extrai; ele não redige
   entregável.
2. **Sessão nova em plan mode, apontada para a spec.** Não é continuação da
   anterior: sessão limpa, e o primeiro pedido é literalmente *"leia
   `specs/<tema>.md` e faça o plano"*. O humano julga o resultado — arquivos
   certos? premissas explícitas? o que está faltando? — e o plano aprovado é
   salvo aqui. **Commit e push**: a guarda do `montar-canteiro.sh` procura o
   plano em `origin/develop`, não no seu diretório.
3. `/compatibilizar` cruza os planos entre si e grava `plans/manifest.json`.
4. `./scripts/obra/montar-canteiro.sh <nome>` provisiona o canteiro —
   ou `--todos`, que monta em série todos os planos que o manifesto liberou
   como `parallel` (e diz o motivo de cada um que pulou).
5. `/cronograma`, **de dentro da worktree**, vira o plano em
   `scripts/helton/prd.json`.
6. `./scripts/helton/helton.sh --tool claude 1` — ensaio vigiado — e só então o
   cap real.
7. `./scripts/obra/desmontar-canteiro.sh <nome>` imprime o índice de revisão e
   desmonta, preservando a branch para o merge.
8. Merge à mão em `develop`, e então
   `./scripts/obra/arquivar-plano.sh <nome>`, que move o plano para
   `history/`.

### Por que o passo 8 não é opcional

Plano entregue que fica em `plans/` volta a ser montado. Depois do merge a
branch `helton/<nome>` é apagada e a worktree já foi no desmonte — de modo que
**nenhuma** das três guardas do `montar-canteiro.sh --todos` dispara (canteiro
montado? não; branch existe? não; status no manifesto? ainda `parallel`). O
plano ganha canteiro novo e o loop refaz do zero o que já está no develop.

O `arquivar-plano.sh` recusa arquivar enquanto a branch existir e não estiver
contida em `origin/develop`: arquivar antes do merge marcaria como
entregue um trabalho que ainda pode mudar, ou ser abandonado. Para plano
descartado de propósito, `--force`.

## history/

O que já foi entregue, fora do caminho da esteira. É pasta versionada, e a
enumeração não a enxerga: o `--todos` lista `plans/` sem recursão e filtra por
`plans/<nome>.md`, e o `/compatibilizar` lê `plans/*.md` — nada aqui dentro é
confundido com trabalho pendente.

As subpastas com data (`20260803-primeira-implementacao-nfe/`) são material mais
antigo, agrupado por empreitada; o `arquivar-plano.sh` grava sempre na raiz de
`history/`, com o mesmo nome de arquivo que o plano tinha.

### Por que a sessão do plano tem de ser nova

Plano nascido dentro da sessão do grill herda a conversa inteira — inclusive o
que foi dito e **não** foi parar no arquivo. Ele sai melhor que a spec, e
ninguém percebe: a spec segue incompleta para as etapas seguintes, que só têm o
arquivo, e o buraco aparece lá adiante, quando o `/cronograma` traduz mal
alguma coisa. Lendo de uma sessão fria, a spec é submetida ao mesmo teste que
tudo o mais nesta esteira — **o disco é o contrato, o contexto não é**. É a
regra da worktree, que só enxerga o commitado; a do `montar-canteiro.sh`, que
confere o plano na base; e a do próprio Helton, que zera o contexto a cada
iteração e relê `prd.json` e `progress.txt`. Se a spec não se sustenta sozinha,
é melhor descobrir no plan mode, onde custa uma pergunta.

Contando direito, uma fatia atravessa quatro sessões frias: grill → plano →
`/cronograma` → cada iteração do loop. Nenhuma delas depende da memória da
anterior.

## manifest.json

Gerado pelo `/compatibilizar`, não escrito à mão. Diz, por plano, quais arquivos
ele reivindica, se cria migration, e se pode rodar em paralelo
(`parallel`), se precisa esperar outro (`serialized_after:<plano>`) ou se
precisa ser reescrito (`needs_reslicing`). Guarda também o sha256 de cada plano
— é assim que o `/cronograma` percebe que o texto mudou depois da decisão.

## O que **não** entra aqui

- Specs — inclusive a saída do `/grill-me` → `specs/`.
- O que não vira plano (conferências, checklists, transcrições avulsas) →
  `notes/`, onde também ficam as capturas de grill anteriores a 09/08/2026.
- PRDs de execução → `scripts/helton/prd.json` (o corrente) e
  `scripts/helton/archive/` (os encerrados).
