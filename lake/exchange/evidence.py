from hashlib import sha256

from lake.exchange.codec import encode_frozen_payload
from lake.exchange.envelope import BundleEnvelope, FrozenEvidence


def build_evidence(bundle: BundleEnvelope) -> FrozenEvidence:
    original_ids = tuple(row.original_id for row in bundle.rows)
    if len(set(original_ids)) != len(original_ids):
        raise ValueError('duplicate bundle original_id')
    return FrozenEvidence(original_ids, sha256(encode_frozen_payload(bundle)).hexdigest())


def verify_evidence(bundle: BundleEnvelope) -> None:
    supplied = bundle.evidence
    if supplied is None:
        raise ValueError('frozen evidence is required')
    expected = build_evidence(bundle)
    if supplied.original_ids != expected.original_ids:
        raise ValueError('bundle original row coverage mismatch')
    if supplied.sha256 != expected.sha256:
        raise ValueError('bundle frozen payload digest mismatch')
