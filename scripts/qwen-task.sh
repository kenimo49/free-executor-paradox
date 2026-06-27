#!/bin/bash
# qwen-task.sh — ローカルQwen(claw-code経由)にタスクを委託する pure shell ラッパー
#
# 2モード:
#   ask   (デフォルト) … テキストを返すだけ。read-only。要約/翻訳/下試しコード/調べ物
#   agent (--agent)    … project内でファイルを作成/編集。workspace-write。生成物は人が確認
#
# 接続: GPU PCのOllama(Tailscale)。常駐サービスなので安定。実験021 GUIDE.md 参照。
#
# 使い方:
#   qwen-task.sh "東京の人口は?"                         # ask, 9b
#   qwen-task.sh --model qwen3.5:35b-a3b "…"            # 賢いが遅い35B
#   qwen-task.sh --agent --dir ~/proj "hello.pyを作って"  # エージェント(ファイル編集)
#   qwen-task.sh --list                                 # 利用可能モデル一覧
set -uo pipefail

CLAW="${CLAW_BIN:-/home/iris/repos/claw-code/rust/target/debug/claw}"
HOST="${OLLAMA_HOST:-http://100.72.192.8:11434}"
MODEL="qwen3.5:9b"
MODE="ask"
DIR=""
PROMPT=""

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)  MODE="agent"; shift;;
    --ask)    MODE="ask"; shift;;
    --model)  MODEL="$2"; shift 2;;
    --dir|-C) DIR="$2"; shift 2;;
    --host)   HOST="$2"; shift 2;;
    --list)   MODE="list"; shift;;
    -h|--help) usage; exit 0;;
    --) shift; PROMPT="${PROMPT:+$PROMPT }$*"; break;;
    *) PROMPT="${PROMPT:+$PROMPT }$1"; shift;;
  esac
done

# --- 前提チェック ---
[[ -x "$CLAW" ]] || { echo "❌ claw が見つかりません: $CLAW"; echo "   実験021 GUIDE.md の §2.1 でビルド要"; exit 1; }
export OLLAMA_HOST="$HOST"
unset OPENAI_API_KEY OPENAI_BASE_URL

code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 "$HOST/v1/models" 2>/dev/null)
[[ "$code" == "200" ]] || { echo "❌ Ollama に到達できません: $HOST (code=$code)"; echo "   GPU PC起動 / Tailscale接続を確認"; exit 1; }

# --- モデル一覧 ---
if [[ "$MODE" == "list" ]]; then
  echo "🟢 $HOST 利用可能モデル:"
  curl -s --max-time 6 "$HOST/api/tags" | python3 -c "import json,sys
for m in json.load(sys.stdin).get('models',[]): print('  -', m['name'], f\"({round(m['size']/1e9,1)}GB)\")"
  exit 0
fi

[[ -n "$PROMPT" ]] || { echo "❌ タスク文がありません"; usage; exit 1; }

# --- 実行 ---
if [[ "$MODE" == "ask" ]]; then
  DIR="${DIR:-/tmp/qwen-ask}"; mkdir -p "$DIR"
  echo "🤖 ask | model=$MODEL | host=$HOST"
  "$CLAW" --model "$MODEL" -C "$DIR" --permission-mode read-only --compact prompt "$PROMPT"
else
  [[ -n "$DIR" ]] || { echo "❌ --agent には --dir <project> が必須(broad_cwd回避)"; exit 1; }
  mkdir -p "$DIR"
  echo "🤖 agent | model=$MODEL | dir=$DIR | host=$HOST"
  echo "   制約: workspace-write / tools=read,write,glob,edit (任意コード実行なし)"
  "$CLAW" --model "$MODEL" -C "$DIR" \
    --permission-mode workspace-write --allowedTools read,write,glob,edit "$PROMPT"
  echo "--- $DIR の中身 ---"
  ls -la "$DIR" | grep -v '^total' | tail -n +2
fi
