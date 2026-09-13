from collections.abc import Iterable
from pathlib import Path

from fastapi.templating import Jinja2Templates

from wpsboot.pipeline import ALIGNERS, CONCATENATE_STEP

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"
STEP_LABELS = {name: a.label for name, a in ALIGNERS.items()} | {CONCATENATE_STEP: "Super-MSA"}

templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


def step_labels(names: Iterable[str]) -> str:
    return ", ".join(STEP_LABELS.get(name, name) for name in names)


templates.env.filters["step_labels"] = step_labels
