from dataclasses import dataclass


@dataclass(frozen=True)
class BundleLine:
    original_id: str
    station: str
    quantity: int
    price_kind: str
    source_price: int | None


@dataclass(frozen=True)
class FrozenEvidence:
    original_ids: tuple[str, ...]
    sha256: str


@dataclass(frozen=True)
class BundleEnvelope:
    issue_id: str
    stream: str
    revision_id: str
    predecessor: str | None
    ordinal: int
    default_price: int
    rows: tuple[BundleLine, ...]
    evidence: FrozenEvidence | None = None
