from lake.exchange.codec import decode_bundle
from lake.exchange.envelope import BundleEnvelope
from lake.exchange.evidence import verify_evidence


def receive_bundle(data: bytes | str) -> BundleEnvelope:
    candidate = decode_bundle(data)
    verify_evidence(candidate)
    return candidate
