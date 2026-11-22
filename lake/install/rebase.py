from dataclasses import dataclass

from lake.exchange.envelope import BundleEnvelope


@dataclass(frozen=True)
class InstalledRow:
    original_id: str
    station: str
    quantity: int
    source_price: int | None


@dataclass(frozen=True)
class InstalledBase:
    stream: str
    revision_id: str
    predecessor: str | None
    ordinal: int
    issue_id: str
    default_price: int
    evidence_digest: str
    rows: tuple[InstalledRow, ...]


def prepare_base(current: InstalledBase | None, bundle: BundleEnvelope) -> InstalledBase:
    if current is None:
        if bundle.ordinal != 1 or bundle.predecessor is not None:
            raise ValueError('first installation requires the first stream revision')
    else:
        if bundle.stream != current.stream:
            raise ValueError('bundle belongs to another stream')
        if bundle.predecessor != current.revision_id or bundle.ordinal != current.ordinal + 1:
            raise ValueError('bundle must be the direct successor of the active revision')
    if bundle.evidence is None:
        raise ValueError('an installable bundle requires frozen evidence')
    rows = tuple(
        InstalledRow(row.original_id, row.station, row.quantity, row.source_price)
        for row in bundle.rows
    )
    return InstalledBase(
        bundle.stream, bundle.revision_id, bundle.predecessor, bundle.ordinal, bundle.issue_id,
        bundle.default_price, bundle.evidence.sha256, rows,
    )
