import sqlite3

from lake.exchange.receive import receive_bundle
from lake.install.history import append_installation, read_installation
from lake.install.rebase import InstalledBase, prepare_base
from lake.install.repository import WarehouseStore, load_base, replace_base


def load_active_base(connection: sqlite3.Connection) -> InstalledBase | None:
    return load_base(connection)


def install(store: WarehouseStore, data: bytes | str) -> str:
    bundle = receive_bundle(data)
    with store.write_transaction() as connection:
        active = load_active_base(connection)
        prepared = prepare_base(active, bundle)
        if read_installation(connection, prepared.revision_id) is not None:
            raise ValueError('revision is already recorded in installation history')
        replace_base(connection, prepared)
        append_installation(connection, prepared)
    return prepared.revision_id
