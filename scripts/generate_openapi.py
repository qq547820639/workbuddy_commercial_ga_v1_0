from pathlib import Path
import yaml
from workbuddy.api.main import create_app

app = create_app(auto_seed=False)
path = Path(__file__).resolve().parents[1] / "api" / "openapi.yaml"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(yaml.safe_dump(app.openapi(), allow_unicode=True, sort_keys=False), encoding="utf-8")
print(path)
