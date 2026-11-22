def validate_integer_price(value: object, field: str = 'price') -> int:
    if type(value) is not int:
        raise ValueError(f'{field} must be an integer')
    return value


def validate_default_price(value: object) -> int:
    return validate_integer_price(value, 'default_price')


def validate_source_price(value: object) -> int | None:
    if value is None:
        return None
    return validate_integer_price(value, 'source_price')
