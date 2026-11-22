from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from lake.exchange.codec import encode_bundle
from lake.exchange.envelope import BundleEnvelope, BundleLine
from lake.exchange.evidence import build_evidence
from lake.source.revisions import read_frozen_revision
from lake.source.store import SourceStore


def issue(store: SourceStore, revision_id: str) -> bytes:
    revision = read_frozen_revision(store, revision_id)
    rows = tuple(
        BundleLine(
            row.original_id, row.station, row.quantity,
            'default' if row.source_price is None else 'explicit', row.source_price,
        )
        for row in revision.rows
    )
    issue_id = uuid5(NAMESPACE_URL, f'binqu-metering/v1/{revision.revision_id}').hex
    bundle = BundleEnvelope(
        issue_id, revision.stream, revision.revision_id, revision.predecessor,
        revision.ordinal, revision.default_price, rows,
    )
    return encode_bundle(replace(bundle, evidence=build_evidence(bundle)))
