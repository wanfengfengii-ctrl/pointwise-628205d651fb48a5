import json
import re
from dataclasses import asdict

from lake.exchange.envelope import BundleEnvelope, BundleLine, FrozenEvidence
from lake.source.rows import require_identifier
from lake.source.tariffs import validate_default_price, validate_source_price


_PAYLOAD_KEYS = {'version', 'issue_id', 'stream', 'revision_id', 'predecessor',
                 'ordinal', 'default_price', 'rows'}
_ROW_KEYS = {'original_id', 'station', 'quantity', 'price_kind', 'source_price'}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _payload(bundle: BundleEnvelope) -> dict:
    return {
        'version': 1,
        'issue_id': bundle.issue_id,
        'stream': bundle.stream,
        'revision_id': bundle.revision_id,
        'predecessor': bundle.predecessor,
        'ordinal': bundle.ordinal,
        'default_price': bundle.default_price,
        'rows': [asdict(row) for row in bundle.rows],
    }


def encode_frozen_payload(bundle: BundleEnvelope) -> bytes:
    return _canonical(_payload(bundle))


def encode_bundle(bundle: BundleEnvelope) -> bytes:
    if bundle.evidence is None:
        raise ValueError('frozen evidence is required')
    data = _payload(bundle)
    data['evidence'] = {'frozen_v1': asdict(bundle.evidence)}
    return _canonical(data)


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f'duplicate JSON field: {key}')
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f'invalid JSON constant: {value}')


def _decode_line(data: object) -> BundleLine:
    if not isinstance(data, dict) or data.keys() != _ROW_KEYS:
        raise ValueError('invalid bundle row fields')
    original_id = require_identifier(data['original_id'], 'original_id')
    station = require_identifier(data['station'], 'station')
    quantity = data['quantity']
    if type(quantity) is not int:
        raise ValueError(f'quantity for {original_id} must be an integer')
    kind = data['price_kind']
    price = validate_source_price(data['source_price'])
    if (kind, price is not None) not in (('explicit', True), ('default', False)):
        raise ValueError(f'inconsistent price declaration for {original_id}')
    return BundleLine(original_id, station, quantity, kind, price)


def _decode_evidence(data: object) -> FrozenEvidence:
    if not isinstance(data, dict) or not isinstance(data.get('frozen_v1'), dict):
        raise ValueError('missing frozen_v1 evidence')
    frozen = data['frozen_v1']
    if frozen.keys() != {'original_ids', 'sha256'}:
        raise ValueError('invalid frozen_v1 fields')
    original_ids, digest = frozen['original_ids'], frozen['sha256']
    if not isinstance(original_ids, list):
        raise ValueError('invalid original row coverage')
    if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise ValueError('invalid frozen payload digest')
    return FrozenEvidence(tuple(require_identifier(item, 'original_id') for item in original_ids), digest)


def decode_bundle(data: bytes | str) -> BundleEnvelope:
    if not isinstance(data, (bytes, str)):
        raise ValueError('bundle must be UTF-8 bytes or text')
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    raw = json.loads(data, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    if not isinstance(raw, dict) or raw.keys() != _PAYLOAD_KEYS | {'evidence'}:
        raise ValueError('invalid bundle fields')
    if type(raw['version']) is not int or raw['version'] != 1:
        raise ValueError('unsupported bundle version')
    revision_id = require_identifier(raw['revision_id'], 'revision_id')
    predecessor = raw['predecessor']
    if predecessor is not None:
        predecessor = require_identifier(predecessor, 'predecessor')
    ordinal = raw['ordinal']
    if type(ordinal) is not int or ordinal < 1 or (ordinal == 1) != (predecessor is None):
        raise ValueError('inconsistent revision position')
    if predecessor == revision_id:
        raise ValueError('revision cannot directly precede itself')
    if not isinstance(raw['rows'], list):
        raise ValueError('bundle rows must be an array')
    return BundleEnvelope(
        require_identifier(raw['issue_id'], 'issue_id'), require_identifier(raw['stream'], 'stream'),
        revision_id, predecessor, ordinal, validate_default_price(raw['default_price']),
        tuple(_decode_line(row) for row in raw['rows']), _decode_evidence(raw['evidence']),
    )
