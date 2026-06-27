# T2: Refactor Task Spec

## タスク

`typer/utils.py` で定義されている関数 `get_params_from_function` を、新しいモジュール `typer/_param_extractor.py` に移動する。

### 詳細仕様

1. **新規ファイル作成**: `typer/_param_extractor.py`
   - 関数 `get_params_from_function` の定義をそのまま含む
   - 必要な import (Callable, Any, ParamMeta, 内部 helper, etc.) もこのファイルに含める
   - 関数のシグネチャ・挙動・戻り型は完全に等価

2. **`typer/utils.py` から削除**:
   - 関数定義を削除
   - 不要になった import を整理 (任意)

3. **import 更新** (全ての参照を新パスに):
   - `typer/main.py:55` の `from .utils import get_params_from_function`
   - `typer/completion.py:12` の `from .utils import get_params_from_function`
   - これらを `from ._param_extractor import get_params_from_function` に変更
   - 他に参照があれば全て同様に更新

4. **整合性**:
   - すべての pytest テストが pass する
   - mypy strict が pass する
   - ruff check が pass する

## 開始状態

green base (typer b210c0e) からスタート。breakage injection なし。
LLM は spec 文書を見て自分でファイル操作・編集を行う。

## 完了判定 (`verify-T2.sh`)

| 項目 | コマンド | 期待値 |
|------|--------|--------|
| pytest pass | `harness.sh` の pytest | exit 0, failed=0 |
| mypy pass | `harness.sh` の mypy | exit 0, errors=0 |
| ruff pass | `harness.sh` の ruff_check | exit 0, errors=0 |
| 関数移動 | `grep -c "^def get_params_from_function" typer/_param_extractor.py` | >= 1 |
| 旧位置から削除 | `grep -c "^def get_params_from_function" typer/utils.py` | = 0 |
| 旧 import 撤去 | `grep -rE "from \.utils import.*get_params_from_function\|from typer.utils import.*get_params_from_function" typer/ tests/` | 0 件 |
| 新 import 採用 | `grep -rE "from \._param_extractor import.*get_params_from_function\|from typer._param_extractor import.*get_params_from_function" typer/` | >= 1 件 |

## 既知の難所 (LLM が踏みやすい罠)

1. `get_params_from_function` の依存(ParamMeta, Callable など)を新ファイルにも import 必要
2. main.py には 4箇所の参照、completion.py には 2箇所
3. `typer/utils.py` を空にし過ぎると、そこから export している他の関数がある場合に壊れる
4. mypy strict なので型注釈は完璧に維持する必要がある

## reset

```bash
breakage-pack/reset.sh   # typer/ を git checkout で base に戻す + 未追跡ファイル削除
```

新規ファイル `_param_extractor.py` は git untracked なので、`reset.sh` の `git clean -fd typer/` で削除される。

## 期待される LLM 行動

- spec を読み、対象関数とその依存を確認
- 新ファイルを作成して関数とimportをコピー
- 参照ファイル(main.py, completion.py)の import を書き換え
- 旧定義を utils.py から削除
- harness を実行 → エラーなら修正
- iteration 3-5 回で完了想定
