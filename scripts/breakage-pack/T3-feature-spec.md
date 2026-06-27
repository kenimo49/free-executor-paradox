# T3: Feature-Add Task Spec

## タスク

`typer` モジュールに新しい関数 `get_version_banner` を追加し、付属の test (実験側が提供する `tests/test_t3_feature.py`) を pass させる。

### 詳細仕様

**追加すべき関数**:

```python
# typer/__init__.py からも import 可能であること
# typer.get_version_banner と呼び出せる
def get_version_banner(prefix: str = "Typer", uppercase: bool = False) -> str:
    """Return a one-line version banner string.

    Format: "{prefix} v{typer.__version__} (Python {python_major}.{python_minor})"

    Args:
        prefix: leading label (default: "Typer")
        uppercase: if True, uppercase the entire result
    """
```

**期待される動作**:
- `get_version_banner()` → `"Typer v0.26.8 (Python 3.X)"`  (X は実行 Python の minor バージョン)
- `get_version_banner(prefix="MyTool")` → `"MyTool v0.26.8 (Python 3.X)"`
- `get_version_banner(uppercase=True)` → `"TYPER V0.26.8 (PYTHON 3.X)"`

**型注釈**: mypy strict が pass する必要あり (str / bool 引数、str 戻り型)

**配置**:
- 実装は `typer/utils.py` または新規 module どちらでも可
- ただし `import typer; typer.get_version_banner` で呼び出せること(__init__.py の re-export 必須)

## 提供されるテスト

実験側で `tests/test_t3_feature.py` を inject する。LLM はこのテストファイルを **編集禁止**(改変したら verifier が検知)。テスト内容:

```python
import sys
import typer


def test_get_version_banner_default():
    result = typer.get_version_banner()
    assert result.startswith("Typer v")
    assert "Python" in result
    assert str(sys.version_info.major) in result
    assert str(sys.version_info.minor) in result


def test_get_version_banner_prefix():
    result = typer.get_version_banner(prefix="MyTool")
    assert result.startswith("MyTool v")


def test_get_version_banner_uppercase():
    result = typer.get_version_banner(uppercase=True)
    assert result == result.upper()
    assert "TYPER" in result
```

## 開始状態

green base (typer b210c0e) からスタート。
実験側が `tests/test_t3_feature.py` を inject 済(未公開機能を呼ぶので最初は test fail)。

```bash
breakage-pack/inject-T3.sh   # tests/test_t3_feature.py を配置
```

## 完了判定 (`verify-T3.sh`)

| 項目 | コマンド | 期待値 |
|------|--------|--------|
| pytest pass | harness の pytest | exit 0, failed=0 |
| mypy pass | harness の mypy | exit 0, errors=0 |
| ruff pass | harness の ruff_check | exit 0, errors=0 |
| 関数定義存在 | `grep -rE "^def get_version_banner" typer/` | >= 1 |
| 公開API | `python -c "import typer; assert callable(typer.get_version_banner)"` | exit 0 |
| 新テスト無改変 | injection 時の SHA256 と比較 | 一致 |
| t3 test pass | `pytest tests/test_t3_feature.py` | exit 0 |

## 既知の難所

1. `__init__.py` への re-export を忘れる → `typer.get_version_banner` が呼べない
2. mypy strict の型注釈不足
3. Python バージョン取得方法(sys.version_info)を忘れる
4. テストファイルを変えてしまう(reject)

## reset

```bash
breakage-pack/reset.sh   # T3 注入ファイル + LLM の変更を全て元に戻す
```

`reset.sh` の `git clean -fd typer/ tests/` で T3-test、 LLM が追加した新ファイル全て削除。
