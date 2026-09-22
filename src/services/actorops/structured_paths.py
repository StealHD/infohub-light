"""Evaluate only declared paths; never recursively hunt for URLs or identities."""
from collections.abc import Mapping


class StructureError(ValueError):
    pass


def matches(value, pointer, *, limit=100):
    nodes = [value]
    for part in pointer.split('/')[1:] if pointer else ():
        part = part.replace('~1', '/').replace('~0', '~')
        found = []
        for node in nodes:
            if part == '*' and isinstance(node, list):
                found.extend(node)
            elif isinstance(node, Mapping) and part in node:
                found.append(node[part])
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                found.append(node[int(part)])
            if len(found) > limit:
                raise StructureError('collection expansion exceeded bound')
        nodes = found
    return nodes


def value_at(value, mapping):
    if mapping is None:
        return None
    for pointer in mapping.pointers:
        nodes = matches(value, pointer)
        if (nodes and nodes[0] is not None and nodes[0] != ''
                and not isinstance(nodes[0], (Mapping, list, tuple))):
            return nodes[0]
    return None


def collection_at(value, mapping, *, limit=100):
    for pointer in mapping.pointers:
        nodes = matches(value, pointer, limit=limit)
        if not nodes:
            continue
        result = []
        for node in nodes:
            if node is None:
                continue
            if isinstance(node, list) and mapping.shape != 'single':
                result.extend(node)
            elif mapping.shape != 'array':
                result.append(node)
            else:
                raise StructureError('expected an array')
            if len(result) > limit:
                raise StructureError('collection exceeded bound')
        if result:
            return result
    return []
