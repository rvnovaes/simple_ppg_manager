#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop
# Usage: ./ralph.sh [max_iterations]
#
# Ralph é o LOOP, não o agente. A cada iteração ele invoca o `claude` em modo
# --print, passando ralph/CLAUDE.md como prompt. Não aponte para ralph.sh: um
# loop chamando a si mesmo abre outro loop de N iterações, sem fundo.

set -e

MAX_ITERATIONS=10

while [[ $# -gt 0 ]]; do
  case $1 in
    *)
      # Assume it's max_iterations if it's a number
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
      fi
      shift
      ;;
  esac
done

if ! command -v claude >/dev/null 2>&1; then
  echo "Erro: 'claude' não está no PATH."
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "Erro: 'jq' não está no PATH."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROMPT_FILE="$SCRIPT_DIR/CLAUDE.md"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"

if [ ! -f "$PRD_FILE" ]; then
  echo "Erro: $PRD_FILE não existe."
  exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
  echo "Erro: $PROMPT_FILE não existe."
  exit 1
fi

# O agente precisa arrancar na raiz do projeto: é lá que estão o CLAUDE.md que
# ele carrega sozinho, o Makefile e o git. Sem isto, rodar de dentro de ralph/
# deixa o agente cego para o projeto.
cd "$PROJECT_ROOT"

# Archive previous run if branch changed
if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")
  
  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    # Archive the previous run
    DATE=$(date +%Y-%m-%d)
    # Strip "ralph/" prefix from branch name for folder
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"
    
    echo "Archiving previous run: $LAST_BRANCH"
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"
    
    # Reset progress file for new run
    echo "# Ralph Progress Log" > "$PROGRESS_FILE"
    echo "Started: $(date)" >> "$PROGRESS_FILE"
    echo "---" >> "$PROGRESS_FILE"
  fi
fi

# Track current branch
if [ -f "$PRD_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  if [ -n "$CURRENT_BRANCH" ]; then
    echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
  fi
fi

# Initialize progress file if it doesn't exist
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

echo "Starting Ralph - cwd: $PROJECT_ROOT - Max iterations: $MAX_ITERATIONS"

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS"
  echo "==============================================================="

  # Claude Code: --dangerously-skip-permissions para rodar sem prompt de permissão,
  # --print para a resposta final vir em stdout.
  #
  # stderr NÃO entra em OUTPUT: com 2>&1 qualquer eco da string de conclusão em log
  # ou diff encerraria o loop por engano. stderr segue para o terminal.
  OUTPUT=$(claude --dangerously-skip-permissions --print < "$PROMPT_FILE" | tee /dev/stderr) || true

  # Só a resposta final conta como sinal de conclusão.
  if echo "$OUTPUT" | tail -n 20 | grep -q "<promise>COMPLETE</promise>"; then
    echo ""
    echo "Ralph completed all tasks!"
    echo "Completed at iteration $i of $MAX_ITERATIONS"
    exit 0
  fi
  
  echo "Iteration $i complete. Continuing..."
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status."
exit 1
