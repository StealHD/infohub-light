"""One shared schema for the AI compiler and deterministic interpreter."""
from ..apify_actor_structures import StructuredOutput


def structured_mapping_contract():
    return {
        'field': 'structures',
        'schema': StructuredOutput.model_json_schema(),
        'rules': [
            'Emit structures ({} when no optional structures exist) to use schema-driven output mapping.',
            'Choose paths by their meaning and Schema descriptions, never by a fixed vendor/field alias list.',
            'Scalar output paths may have any spelling; real rows must pass URL, timestamp and target identity validation.',
            'Every collection pointer is relative to its containing publication or media item. Wildcards traverse at most two arrays; do not flatten different posts together.',
            'Use collection shape array for slides, single for one media object, array_or_single only when the Schema proves both.',
            'An empty relative pointer selects the current primitive URL or object. Scalar pointers do not allow wildcards.',
            'Variants are alternative sizes of ONE media item, never multiple slides. Map width/height when available.',
            'A video must use preview_url or image variants for its cover; never use its video file as an image.',
            'Map kind_values only from supplied enum values; preserve media order.',
            'Map contributors only for confirmed coauthors, not invited collaborators, tagged people or caption mentions. Never substitute the requested target into returned author fields.',
            'Missing optional media does not invalidate otherwise proven content. Do not invent missing URLs, people, or arrays.',
        ],
    }
