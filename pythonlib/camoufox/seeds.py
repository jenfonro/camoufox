"""Type contract for existing kernel fingerprint seed fields."""

SEED_KEYS = ('canvas:seed', 'audio:seed', 'fonts:spacing_seed')


def validate_seed_options(config):
    for key in SEED_KEYS:
        if key not in config:
            continue
        value = config[key]
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f'{key} must be an integer between 0 and 4294967295')
