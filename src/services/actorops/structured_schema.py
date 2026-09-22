"""Schema proof for declared collection projections, independent of field spelling."""
from collections.abc import Mapping
from ..apify_actor_structures import StructuredOutput


class SchemaProofError(ValueError):
    pass


def alternatives(node):
    choices = node.get('anyOf') or node.get('oneOf')
    if isinstance(choices, list):
        return [value for item in choices if isinstance(item, Mapping)
                for value in alternatives(item)]
    return [node]


def schemas_at(schema, pointer):
    nodes = alternatives(schema)
    for token in pointer.split('/')[1:] if pointer else ():
        token = token.replace('~1', '/').replace('~0', '~')
        result = []
        for node in nodes:
            child = node.get('properties', {}).get(token)
            if child is None and (token == '*' or token.isdigit()):
                child = node.get('items')
            if isinstance(child, Mapping):
                result.extend(alternatives(child))
        nodes = result
    return nodes


def prove_value(schema, mapping, types):
    if mapping is None:
        return
    for pointer in mapping.pointers:
        nodes = schemas_at(schema, pointer)
        if not nodes:
            raise SchemaProofError('unknown projection path')
        proven = False
        for node in nodes:
            raw = node.get('type')
            kinds = {raw} if isinstance(raw, str) else set(raw or ())
            if pointer == '' and len(mapping.pointers) > 1 and kinds <= {'object', 'array', 'null'}:
                continue
            if not kinds or not kinds.issubset(set(types) | {'null'}):
                raise SchemaProofError('invalid projection type')
            proven = proven or bool(kinds & set(types))
        if not proven:
            raise SchemaProofError('projection has no scalar evidence')


def collection_schema(schema, mapping):
    items = []
    for pointer in mapping.pointers:
        nodes = schemas_at(schema, pointer)
        if not nodes:
            raise SchemaProofError('unknown collection path')
        for node in nodes:
            if node.get('type') == 'null':
                continue
            if node.get('type') == 'array' and mapping.shape != 'single':
                child = node.get('items')
                if not isinstance(child, Mapping):
                    raise SchemaProofError('unproven collection elements')
                items.extend(alternatives(child))
            elif mapping.shape != 'array':
                items.append(node)
            else:
                raise SchemaProofError('expected collection schema')
    return {'anyOf': items} if items else {'type': 'null'}


def prove_structures(value, schema):
    if value is None:
        return None
    try:
        plan = StructuredOutput.model_validate(value)
        prove_value(schema, plan.media_count, ('integer', 'number'))
        media = plan.media
        if media:
            node = collection_schema(schema, media.collection)
            if not any((media.url, media.preview_url, media.variants)):
                raise SchemaProofError('media preview missing')
            for mapping in (media.url, media.preview_url):
                prove_value(node, mapping, ('string',))
            prove_value(node, media.native_id, ('string', 'integer'))
            prove_value(node, media.kind, ('string', 'integer', 'boolean'))
            if media.kind:
                supplied = {str(v).lower() for path in media.kind.pointers
                            for raw in schemas_at(node, path) for v in raw.get('enum', [])}
                if not media.kind_values or not set(media.kind_values).issubset(supplied):
                    raise SchemaProofError('media kinds require schema enum evidence')
            if media.variants:
                variant = collection_schema(node, media.variants.collection)
                prove_value(variant, media.variants.url, ('string',))
                for mapping in (media.variants.width, media.variants.height):
                    prove_value(variant, mapping, ('integer', 'number'))
        people = plan.contributors
        if people:
            for pointer in people.collection.pointers:
                descriptions = [str(n.get('description', '')) for n in schemas_at(schema, pointer)]
                evidence = (pointer + ' ' + ' '.join(descriptions)).lower()
                if any(word in evidence for word in ('invited', 'invitation', 'tagged', 'mention')):
                    raise SchemaProofError('unconfirmed relationship')
            node = collection_schema(schema, people.collection)
            for mapping in (people.handle, people.name, people.avatar_url):
                prove_value(node, mapping, ('string',))
    except (SchemaProofError, TypeError, ValueError):
        return 'actorops_discovery_ai_structured_mapping_unproven'
    return None
