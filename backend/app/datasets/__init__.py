from .base import DatasetAdapter
from .ludb import LUDBAdapter
from .mitdb import MITDBAdapter
from .qtdb import QTDBAdapter

ADAPTERS: dict[str, DatasetAdapter] = {a.id: a for a in (LUDBAdapter(), QTDBAdapter(), MITDBAdapter())}

# Small, redistributable (ODC-By 1.0) samples bundled under data/physionet/
BUNDLED_RECORDS: dict[str, list[str]] = {
    "ludb": ["1", "2", "3", "4", "5", "6"],
    "qtdb": ["sel100", "sel103"],
    "mitdb": ["100", "105"],
}


def get_adapter(dataset_id: str) -> DatasetAdapter:
    try:
        return ADAPTERS[dataset_id]
    except KeyError as e:
        raise KeyError(f"Unknown dataset '{dataset_id}'. Known: {', '.join(ADAPTERS)}") from e
