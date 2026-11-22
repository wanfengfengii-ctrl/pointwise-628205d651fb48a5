from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from lake.source.rows import SourceRow, require_identifier, validate_rows
from lake.source.store import SourceStore
from lake.source.streams import read_stream_head, require_predecessor
from lake.source.tariffs import validate_default_price


@dataclass(frozen=True)
class FrozenRevision:
    stream: str
    revision_id: str
    predecessor: str | None
    ordinal: int
    default_price: int
    rows: tuple[SourceRow, ...]


def freeze(
    store: SourceStore,
    stream: str,
    predecessor: str | None,
    default_price: int,
    rows: Iterable[SourceRow | Mapping[str, object]],
) -> str:
    stream = require_identifier(stream, 'stream')
    if predecessor is not None:
        predecessor = require_identifier(predecessor, 'predecessor')
    default_price = validate_default_price(default_price)
    validated = validate_rows(rows)
    with store.write_transaction():
        ordinal = require_predecessor(read_stream_head(store, stream), predecessor)
        revision = FrozenRevision(stream, uuid4().hex, predecessor, ordinal, default_price, validated)
        store.save_revision(revision)
    return revision.revision_id


def read_frozen_revision(store: SourceStore, revision_id: str) -> FrozenRevision:
    revision_id = require_identifier(revision_id, 'revision_id')
    loaded = store.load_revision(revision_id)
    if loaded is None:
        raise KeyError(f'unknown revision: {revision_id}')
    header, stored_rows = loaded
    if len(stored_rows) != header['row_count'] or any(
        row['position'] != position for position, row in enumerate(stored_rows)
    ):
        raise ValueError(f'incomplete frozen rows: {revision_id}')
    rows = validate_rows(
        SourceRow(
            row['original_id'], row['station'], int(row['quantity']),
            None if row['source_price'] is None else int(row['source_price']),
        )
        for row in stored_rows
    )
    return FrozenRevision(
        header['stream'], revision_id, header['predecessor'], header['ordinal'],
        validate_default_price(int(header['default_price'])), rows,
    )
