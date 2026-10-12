"""Preserve RSSHub's publication-date AV/BV permalink identity without network IO."""

from .common import canonical_video_url


# Bilibili's reversible base-58 video identifier, documented with test vectors:
# https://github.com/pskdje/bilibili-API-collect/blob/main/docs/misc/bvid_desc.md
_ALPHABET = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
_POSITIONS = (8, 7, 0, 5, 1, 3, 2, 4, 6)
_XOR = 23442827791579
_MAX_AID = 1 << 51
# RSSHub bilibili/video.ts chooses AV links up to this publication timestamp.
_BV_LINK_START = 1589990400


def _encode(aid):
    if not 0 < aid < _MAX_AID:
        raise ValueError("Bilibili video identity is invalid")
    value = (_MAX_AID | aid) ^ _XOR
    chars = [""] * 9
    for position in _POSITIONS:
        value, digit = divmod(value, 58)
        chars[position] = _ALPHABET[digit]
    return "BV1" + "".join(chars)


def _decode(bvid):
    if not bvid.startswith("BV1"):
        raise ValueError("Bilibili video identity is invalid")
    value = 0
    for position in reversed(_POSITIONS):
        value = value * 58 + _ALPHABET.index(bvid[3 + position])
    aid = (value & (_MAX_AID - 1)) ^ _XOR
    if _encode(aid) != bvid:
        raise ValueError("Bilibili video identity is invalid")
    return aid


def rss_video_url(raw, published_at):
    url = canonical_video_url(raw)
    video_id = url.rsplit("/", 1)[1]
    use_bv = published_at.timestamp() > _BV_LINK_START
    if video_id.startswith("BV") and not use_bv:
        video_id = f"av{_decode(video_id)}"
    elif video_id.startswith("av") and use_bv:
        video_id = _encode(int(video_id[2:]))
    return f"https://www.bilibili.com/video/{video_id}"
