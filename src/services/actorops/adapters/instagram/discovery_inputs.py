"""Exact-schema Instagram profile inputs, independent of Actor names."""

from collections.abc import Mapping

HANDLE_KEYS = ('username', 'usernames', 'instagramUsernames', 'profiles', 'profile', 'handle')
URL_KEYS = ('profileUrls', 'startUrls', 'directUrls')


def input_options(revision):
    properties = revision.input_schema.get('properties', {})
    arrays = {key for key, schema in properties.items()
              if isinstance(schema, Mapping) and 'array' in _types(schema)}
    return {
        'input_keys': (*HANDLE_KEYS, *URL_KEYS),
        'identity_ref': 'target.handle',
        'list_handle_input_keys': tuple(key for key in HANDLE_KEYS if key in arrays),
        'list_url_input_keys': tuple(key for key in URL_KEYS if key in arrays),
        'handle_input_keys': tuple(key for key in HANDLE_KEYS if key not in arrays),
        'url_input_keys': tuple(key for key in URL_KEYS if key not in arrays),
        'max_items_input_keys': ('maxItems', 'maxPosts', 'postsPerProfile',
                                'resultsPerProfile', 'resultsLimit', 'limit'),
        'input_constants': _constants(properties),
    }


def _types(schema):
    raw = schema.get('type', ())
    return {raw} if isinstance(raw, str) else set(raw or ())


def _constants(properties):
    constants = {}
    for key, choice in (('resultsType', 'posts'), ('dataDetailLevel', 'basicData')):
        schema = properties.get(key)
        if isinstance(schema, Mapping) and choice in schema.get('enum', ()):
            constants[key] = choice
    return constants


def refine_mapping(revision, mapping):
    """Apply profile semantics to both deterministic and AI proposals before proof."""
    import json
    from ...ports import DiscoveryMapping

    fields = revision.input_schema.get('properties', {})
    if 'postUrls' in fields and not set(fields).intersection((*HANDLE_KEYS, *URL_KEYS)):
        return DiscoveryMapping(None, 'wrong_actor_type')
    if mapping is None or not mapping.manifest_json:
        return mapping
    try:
        manifest = json.loads(mapping.manifest_json)
        inputs = manifest.get('input')
        if not isinstance(inputs, dict):
            return mapping
        manifest['input'] = {**inputs, **_constants(fields)}
        return DiscoveryMapping(json.dumps(manifest), mapping.rejection_code)
    except (ValueError, TypeError, AttributeError):
        return mapping
