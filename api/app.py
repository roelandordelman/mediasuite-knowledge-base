from pathlib import Path

import yaml
from fastapi import FastAPI

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

app = FastAPI(title="Media Suite Knowledge Base API")

_entity_config: dict | None = None


@app.on_event("startup")
async def _load_entity_config() -> None:
    global _entity_config
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    _entity_config = {
        "tool_entities": cfg.get("tool_entities", {}),
        "collection_entities": cfg.get("graph", {}).get("collection_entities", {}),
    }


@app.get("/config/entities")
def get_entities() -> dict:
    return _entity_config
