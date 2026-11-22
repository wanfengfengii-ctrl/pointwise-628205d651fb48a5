from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lake.source.tariffs import validate_source_price


@dataclass(frozen=True)
class SourceRow:
    original_id: str
    station: str
    quantity: int
    source_price: int | None = None


def require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{field} must be nonempty text')
    value.encode('utf-8')
    return value


def _as_source_row(value: SourceRow | Mapping[str, object]) -> SourceRow:
    if isinstance(value, SourceRow):
        return value
    if not isinstance(value, Mapping):
        raise ValueError('each source row must be a SourceRow or field mapping')
    required = {'original_id', 'station', 'quantity'}
    if not required <= value.keys() or value.keys() - required - {'source_price'}:
        raise ValueError('invalid source row fields')
    return SourceRow(value['original_id'], value['station'], value['quantity'], value.get('source_price'))


def validate_rows(rows: Iterable[SourceRow | Mapping[str, object]]) -> tuple[SourceRow, ...]:
    try:
        items = iter(rows)
    except TypeError as exc:
        raise ValueError('rows must be iterable') from exc
    validated = []
    registered = set()
    for value in items:
        row = _as_source_row(value)
        original_id = require_identifier(row.original_id, 'original_id')
        station = require_identifier(row.station, 'station')
        if original_id in registered:
            raise ValueError(f'duplicate original_id: {original_id}')
        if type(row.quantity) is not int:
            raise ValueError(f'quantity for {original_id} must be an integer')
        price = validate_source_price(row.source_price)
        registered.add(original_id)
        validated.append(SourceRow(original_id, station, row.quantity, price))
    return tuple(validated)
