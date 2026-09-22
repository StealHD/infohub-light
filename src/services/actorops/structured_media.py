"""Interpret declared media groups without knowledge of Actor field names."""
from dataclasses import dataclass
from .structured_paths import collection_at, value_at, StructureError
from .structured_identity import safe_image_url
from .capability_evidence import MediaCapabilityEvidence


@dataclass(frozen=True)
class MediaResult:
    urls: tuple[str, ...]
    photos: int
    videos: int
    evidence: MediaCapabilityEvidence

    def metadata(self):
        result = {'media_urls': list(self.urls[:6]),
                  'media_image_count': len(self.urls),
                  'media_photo_count': self.photos, 'media_video_count': self.videos}
        if self.urls:
            result['image_url'] = self.urls[0]
        if self.photos + self.videos > 1:
            result['upstream_content_format'] = 'gallery'
        elif self.videos:
            result['upstream_content_format'] = 'video'
        elif self.photos:
            result['upstream_content_format'] = 'image'
        return result


def _dimension(value):
    return value if type(value) in (int, float) and 0 < value <= 100000 else 0


def _preview(node, mapping, kind):
    gap = False
    if mapping.variants:
        ranked = []
        try:
            for value in collection_at(node, mapping.variants.collection):
                url = safe_image_url(value_at(value, mapping.variants.url))
                if url:
                    area = (_dimension(value_at(value, mapping.variants.width))
                            * _dimension(value_at(value, mapping.variants.height)))
                    ranked.append((area, url))
                else:
                    gap = True
        except StructureError:
            gap = True
        if ranked:
            return max(enumerate(ranked), key=lambda pair: (pair[1][0], -pair[0]))[1][1], gap
    cover = safe_image_url(value_at(node, mapping.preview_url))
    return cover or (safe_image_url(value_at(node, mapping.url)) if kind == 'image' else None), gap


def interpret_media(row, structures):
    mapping = structures.media
    if mapping is None:
        return None
    urls, seen, photos, videos, gap = [], {}, 0, 0, False
    try:
        nodes = collection_at(row, mapping.collection)
    except StructureError:
        nodes, gap = [], True
    for node in nodes:
        try:
            raw_kind = value_at(node, mapping.kind)
            kind = mapping.default_kind
            if mapping.kind is not None:
                kind = mapping.kind_values.get(str(raw_kind).lower())
                if kind is None:
                    gap = True
                    continue
            url, preview_gap = _preview(node, mapping, kind)
            gap = gap or preview_gap
            identity = value_at(node, mapping.native_id)
            identity = str(identity) if isinstance(identity, (str, int)) else url
            if identity and identity in seen:
                gap = gap or seen[identity] != url
                continue
            if identity:
                seen[identity] = url
            photos += int(kind == 'image')
            videos += int(kind == 'video')
            if url and url not in urls:
                urls.append(url)
            elif not url and kind == 'image':
                gap = True
        except (StructureError, TypeError, ValueError):
            gap = True
    count = photos + videos
    expected = value_at(row, structures.media_count)
    incomplete = not gap and type(expected) is int and expected > count and expected > 1
    status = ('upstream_incomplete' if incomplete else 'mapping_gap' if gap else
              'observed_multi' if count > 1 else 'unknown')
    reason = {'upstream_incomplete': 'gallery_items_missing',
              'mapping_gap': 'unmapped_media_items',
              'observed_multi': 'multiple_media_observed', 'unknown': 'no_gallery_sample'}[status]
    evidence = MediaCapabilityEvidence(status=status, reason=reason,
                                      sample_count=1, media_count=count)
    return MediaResult(tuple(urls), photos, videos, evidence)
