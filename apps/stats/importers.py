"""Sources of official reference prices (min-max). Only the interface and a CSV reader exist for now;
the live stat.uz connection is a TODO because the real endpoint/format is not decided yet."""
import csv
import datetime
from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class ReferenceRow:
    product_name: str          # matched against Product.name / ProductAlias via normalisation
    date: datetime.date
    min_price: int             # so'm per product's default unit
    max_price: int
    region: str = ""


class PriceSource(Protocol):
    name: str

    def fetch(self) -> Iterable[ReferenceRow]: ...


class CsvSource:
    """Local CSV with header: product,date,min_price,max_price[,region]  (date = YYYY-MM-DD).
    Lets the import pipeline be exercised end-to-end before the real source exists."""
    name = "csv"

    def __init__(self, path):
        self.path = path

    def fetch(self):
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            for line_no, row in enumerate(csv.DictReader(fh), start=2):
                try:
                    yield ReferenceRow(
                        product_name=row["product"].strip(),
                        date=datetime.date.fromisoformat(row["date"].strip()),
                        min_price=int(row["min_price"]),
                        max_price=int(row["max_price"]),
                        region=(row.get("region") or "").strip(),
                    )
                except (KeyError, ValueError, AttributeError) as exc:
                    raise ValueError(f"{self.path}:{line_no}: bad row ({exc})") from exc


class StatUzSource:
    """TODO: connect to stat.uz farmers'-market prices once the data source is confirmed.
    Expected to yield ReferenceRow items in so'm per product default unit (convert kg/l/pack there)."""
    name = "stat.uz"

    def fetch(self):
        raise NotImplementedError("stat.uz source is not connected yet; use --file with a CSV for now.")
