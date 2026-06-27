# T1: Breakage Recovery Spec

## 目的

green な typer (b210c0e) に 25 errors を 15 files に inject し、各 arm に「green まで戻す」タスクを与えて経済性を測る。

## 配分

| カテゴリ | 件数 | harness 検知 | 期待される LLM action |
|---------|------|------------|------------------|
| 型エラー | 10 | mypy | 戻り型/引数型/None 整合の修正 |
| lint エラー | 10 | ruff check | unused import 削除 / undefined name 修正 / unused var 削除 |
| test 失敗 | 5 | pytest | 真理値反転/off-by-one を元に戻す |

## ファイル選定 (15 files, 重複あり)

| file | 行数 | 配分 |
|------|------|------|
| typer/main.py | 2011 | 4 (型2+lint1+test1) |
| typer/params.py | 1833 | 3 (型2+lint1) |
| typer/core.py | 1217 | 3 (型1+lint1+test1) |
| typer/rich_utils.py | 772 | 2 (型1+lint1) |
| typer/models.py | 743 | 2 (型1+lint1) |
| typer/testing.py | 342 | 2 (型1+lint1) |
| typer/cli.py | 317 | 2 (型1+test1) |
| typer/_completion_shared.py | 254 | 1 (lint) |
| typer/_completion_classes.py | 229 | 1 (lint) |
| typer/utils.py | 197 | 1 (lint) |
| typer/completion.py | 145 | 1 (test) |
| typer/_types.py | 120 | 1 (型) |
| typer/_typing.py | 73 | 1 (型) |
| typer/colors.py | 21 | 1 (lint) |
| typer/__main__.py | 4 | 1 (lint - unused import) |

合計: 型10 + lint10 + test5 = **25 errors**

## Injection 種別の詳細

### 型エラー (mypy で検知される 10件)

| 種別 | 件数 | 例 |
|------|------|-----|
| 戻り型変更 (Wrong return type) | 4 | `def f() -> int: return "x"` |
| 引数型変更 (Argument type) | 2 | 引数の型を `int` → `str` に書き換え、呼び出し元と不整合 |
| None 整合違反 | 2 | `Optional[X]` を `X` に変える(None代入箇所が型エラー) |
| 未定義属性 | 2 | `obj.nonexistent_attr` を追加 |

### lint エラー (ruff check で検知される 10件)

| 種別 | 件数 | ruff code |
|------|------|----------|
| 未使用 import | 4 | F401 |
| 未定義名 | 2 | F821 |
| 未使用変数 | 2 | F841 |
| star import (ban) | 2 | F403 |

### test 失敗 (pytest で検知される 5件)

| 種別 | 件数 | 戦略 |
|------|------|------|
| 真理値反転 | 2 | `return True` → `return False` 等 |
| off-by-one | 1 | `range(n)` → `range(n+1)` 等 |
| 文字列置換 | 1 | error message 改変 |
| 順序入替 | 1 | tuple の要素順を入れ替え |

## 決定論性の保証

- `inject-breakage.py` が単一の真実源
- AST/正規表現で injection point を**ファイル順×行番号順の先頭から決定論的に選ぶ**
- 同じ typer commit (b210c0e) + 同じ script = **常に同一の breakage 状態**
- 適用前の検査として「対象ファイルの SHA256 が base 状態と一致するか」を確認

## reset 方法

```bash
cd base-repo/typer && git checkout -- .
```

`git apply T1-breakage.patch` で生成した状態を `git checkout` で完全に戻す。

## injection 後の実測状態 (verified 2026-06-27)

| harness | 値 |
|---------|-----|
| exit_code | 1 (red) |
| mypy errors | 16 |
| ruff_check errors | 28 (内訳: F401=16, F841=5, F821=4, F403=3) |
| ruff_format errors | 12 (informational) |
| pytest failed | 0 |
| pytest passed | 1324 (base 1356 から 32 減少) |
| pytest collection_errors | 40 (5 test files × pytest-xdist 8 workers) |
| elapsed | 22 sec |

reset 後: 全 0 errors / 1356 passed (green base に完全復帰、22 sec)。

注: "25 injections" は注入数、harness が報告する "84 error signals" は注入の downstream 派生 (e.g., 1つの bad type annotation が mypy で 2-3件報告される)。両者は別概念。

## 完了判定

LLM 修正後 `harness.sh` が exit 0 を返したら trial 完了。
そのとき以下を records:
- 修正までの iteration 数
- 各 iteration の token usage
- 修正中に新規 error を発生させた回数
- final commit の diff サイズ
