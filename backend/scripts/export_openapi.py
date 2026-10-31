"""把 FastAPI 当前契约导出为仓库内的 OpenAPI YAML。"""

import sys
from pathlib import Path

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

OUTPUT = BACKEND_DIR / "openapi.yml"


def main() -> None:
    schema = app.openapi()
    OUTPUT.write_text(
        yaml.safe_dump(schema, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"已生成 {OUTPUT}")


if __name__ == "__main__":
    main()
