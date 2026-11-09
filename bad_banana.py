#!/usr/bin/env python3
import argparse
import atexit
import base64
import collections
import difflib
import email.utils
import gzip
import hashlib
import hmac
import http.client
import json
import os
import platform
import re
import shutil
import signal
import socket
import struct
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

VERSION = "1.4"

BANNER = (
    " ╔╗ ╔═╗╔╦╗  ╔╗ ╔═╗╔╗╔╔═╗╔╗╔╔═╗\n"
    " ╠╩╗╠═╣ ║║  ╠╩╗╠═╣║║║╠═╣║║║╠═╣\n"
    " ╚═╝╩ ╩═╩╝  ╚═╝╩ ╩╝╚╝╩ ╩╝╚╝╩ ╩   terminal-style music streaming for the Raspberry Pi\n"
)

AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
}

COVER_STEMS = frozenset(
    {"cover", "folder", "front", "album", "albumart", "albumartsmall", "artwork"}
)
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})

CHUNK_SIZE = 64 * 1024
MAX_TAG_BYTES = 32 * 1024 * 1024
MAX_MOOV_BYTES = 64 * 1024 * 1024
MAX_FIELD_LENGTH = 512
MAX_POST_BYTES = 64 * 1024
ART_CACHE_SIZE = 48
GZIP_MIN_BYTES = 1024
SOCKET_TIMEOUT = 120
MPEG_SCAN_BYTES = 128 * 1024
OGG_TAIL_BYTES = 128 * 1024
SCAN_LOG_EVERY = 250
CSRF_HEADER = "X-BadBanana"
FALSE_WORDS = frozenset({"0", "false", "no", "off"})

UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"
MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2/%s/"
COVER_ART_URL = "https://coverartarchive.org/release-group/%s/front-500"
COVER_ART_HOSTS = frozenset({"coverartarchive.org", "archive.org"})
ONLINE_ART_PROVIDERS = ("musicbrainz",)
MUSICBRAINZ_INTERVAL = 1.1
MUSICBRAINZ_RESULTS = 10
MUSICBRAINZ_PAUSE = 60
ART_CANDIDATE_LIMIT = 3
ART_MATCH_CACHE_SIZE = 512
MUSICBRAINZ_CONTACT = "Scott Forbes; flakefrost@gmail.com"
ONLINE_REQUEST_TIMEOUT = 5
ONLINE_LOOKUP_BUDGET = 12
ONLINE_JSON_LIMIT = 2 * 1024 * 1024
ONLINE_IMAGE_LIMIT = 8 * 1024 * 1024
ONLINE_ART_GRACE = 600
ONLINE_ART_MAX_FILES = 8
ONLINE_MISS_TTL = 600
ONLINE_OFFLINE_BACKOFF = 300
MATCH_THRESHOLD = 0.6
TITLE_MATCH_THRESHOLD = 0.7
IMAGE_EXTENSIONS_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

TRACK_ROUTE = re.compile(r"/(stream|art)/([0-9a-f]{12})")
ART_PURGE_ROUTE = re.compile(r"/api/art/([0-9a-f]{12})")
BRACKETED = re.compile(r"[\(\[][^\)\]]*[\)\]]")
NON_WORD = re.compile(r"[\W_]+")
MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ID3_FRAME_ID = re.compile(rb"[A-Z0-9]{3,4}")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
LEADING_NUMBER = re.compile(r"\s*(\d+)")
FILENAME_TRACK = re.compile(r"^\s*(\d{1,3})[\s.\-_]+(.+)$")

ID3_TEXT_FRAMES = {
    "TIT2": "title",
    "TT2": "title",
    "TPE1": "artist",
    "TP1": "artist",
    "TPE2": "albumartist",
    "TP2": "albumartist",
    "TALB": "album",
    "TAL": "album",
    "TRCK": "track",
    "TRK": "track",
    "TPOS": "disc",
    "TPA": "disc",
}

ID3_TEXT_CODECS = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}

ID3_LEGACY_IMAGE_FORMATS = {
    b"PNG": "image/png",
    b"JPG": "image/jpeg",
    b"GIF": "image/gif",
}

VORBIS_FIELDS = {
    "TITLE": "title",
    "ARTIST": "artist",
    "ALBUMARTIST": "albumartist",
    "ALBUM ARTIST": "albumartist",
    "ALBUM": "album",
    "TRACKNUMBER": "track",
    "DISCNUMBER": "disc",
}

MP4_TEXT_FIELDS = {
    b"\xa9nam": "title",
    b"\xa9ART": "artist",
    b"aART": "albumartist",
    b"\xa9alb": "album",
}

MP4_IMAGE_TYPES = {13: "image/jpeg", 14: "image/png", 27: "image/bmp"}

RIFF_INFO_FIELDS = {
    b"INAM": "title",
    b"IART": "artist",
    b"IPRD": "album",
    b"ITRK": "track",
    b"IPRT": "track",
}

MPEG_BITRATES = {
    (True, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}

MPEG_SAMPLE_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}

MpegFrame = collections.namedtuple(
    "MpegFrame", "mpeg1 layer bitrate sample_rate samples length mono"
)
ArtCandidate = collections.namedtuple("ArtCandidate", "artist album title urls")

PROBE_ERRORS = (OSError, ValueError, struct.error, IndexError, OverflowError, EOFError)
CLIENT_GONE_ERRORS = (ConnectionError, socket.timeout, TimeoutError)
ONLINE_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    socket.timeout,
    TimeoutError,
    OSError,
    ValueError,
)


def plural(count, noun):
    return "%d %s%s" % (count, noun, "" if count == 1 else "s")


def timestamp():
    return time.strftime("[%I:%M:%S %p]")


class Console:
    verbose = False
    serving = False

    @classmethod
    def enabled(cls):
        return cls.verbose or not cls.serving


def log(message):
    if Console.enabled():
        print(timestamp(), message, flush=True)


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    value = str(value)
    try:
        raw = value.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        raw = value.encode("utf-8", "surrogatepass")
    value = CONTROL_CHARACTERS.sub(" ", raw.decode("utf-8", "replace"))
    return " ".join(value.split())[:MAX_FIELD_LENGTH]


def parse_number(value):
    if isinstance(value, int):
        return max(0, value)
    match = LEADING_NUMBER.match(str(value or ""))
    return int(match.group(1)) if match else 0


def detect_image(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return None


def sniff_image(data, declared="image/jpeg"):
    detected = detect_image(data)
    if detected:
        return detected
    declared = (declared or "").lower().strip()
    if declared == "image/jpg":
        return "image/jpeg"
    return declared if declared.startswith("image/") else "image/jpeg"


def put(meta, key, value):
    if isinstance(value, str):
        value = clean_text(value)
    if value and not meta.get(key):
        meta[key] = value


def synchsafe(data):
    return (
        (data[0] & 0x7F) << 21
        | (data[1] & 0x7F) << 14
        | (data[2] & 0x7F) << 7
        | (data[3] & 0x7F)
    )


def remove_unsynchronisation(data):
    return data.replace(b"\xff\x00", b"\xff")


def decode_loose(data):
    data = data.split(b"\x00", 1)[0]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


class ArtCollector:
    def __init__(self, want):
        self.want = want
        self.found = False
        self.data = None
        self.mime = None
        self.picture_type = None

    @property
    def satisfied(self):
        return self.found and (not self.want or self.picture_type == 3)

    def mark(self):
        self.found = True

    def offer(self, picture_type, mime, data):
        if not data:
            return
        self.found = True
        if not self.want:
            return
        if self.data is None or (picture_type == 3 and self.picture_type != 3):
            self.data = bytes(data)
            self.mime = sniff_image(self.data, mime)
            self.picture_type = picture_type

    def result(self):
        if self.data is None:
            return None
        return self.data, self.mime


def decode_id3_text(encoding, data):
    codec = ID3_TEXT_CODECS.get(encoding)
    if codec is None:
        return ""
    if encoding == 1 and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        codec = "utf-16-le"
    if encoding in (1, 2) and len(data) % 2:
        data = data[:-1]
    text = data.decode(codec, "replace")
    first = next((part for part in text.split("\x00") if part.strip()), "")
    return clean_text(first.lstrip("﻿"))


def skip_terminated(data, start, wide):
    if wide:
        index = start
        while index + 1 < len(data):
            if data[index] == 0 and data[index + 1] == 0:
                return index + 2
            index += 2
        return len(data)
    index = data.find(b"\x00", start)
    return len(data) if index < 0 else index + 1


def parse_id3_picture(payload, legacy):
    if len(payload) < 5:
        return None
    encoding = payload[0]
    if legacy:
        mime = ID3_LEGACY_IMAGE_FORMATS.get(payload[1:4].upper(), "image/jpeg")
        type_index = 4
    else:
        mime_end = payload.find(b"\x00", 1)
        if mime_end < 0:
            return None
        mime = payload[1:mime_end].decode("latin-1", "replace").strip().lower()
        if mime and "/" not in mime:
            mime = "image/" + mime
        type_index = mime_end + 1
    if type_index >= len(payload):
        return None
    data_start = skip_terminated(payload, type_index + 1, encoding in (1, 2))
    return payload[type_index], mime, payload[data_start:]


def id3_frame_boundary(body, offset):
    if offset > len(body):
        return False
    head = body[offset:offset + 4]
    return head.strip(b"\x00") == b"" or bool(ID3_FRAME_ID.fullmatch(head))


def id3v24_frame_size(body, position):
    raw = body[position + 4:position + 8]
    plain = struct.unpack(">I", raw)[0]
    if any(byte & 0x80 for byte in raw):
        return plain
    safe = synchsafe(raw)
    if safe == plain or id3_frame_boundary(body, position + 10 + safe):
        return safe
    if id3_frame_boundary(body, position + 10 + plain):
        return plain
    return safe


def inflate(data):
    decompressor = zlib.decompressobj()
    result = decompressor.decompress(data, MAX_TAG_BYTES)
    if decompressor.unconsumed_tail:
        raise zlib.error("frame expands beyond %d bytes" % MAX_TAG_BYTES)
    return result


def id3_frame_payload(data, major, flags, tag_unsynchronised):
    try:
        if major == 3:
            if flags & 0x0040:
                return b""
            offset = (4 if flags & 0x0080 else 0) + (1 if flags & 0x0020 else 0)
            data = data[offset:]
            if flags & 0x0080:
                data = inflate(data)
        elif major == 4:
            if flags & 0x0004:
                return b""
            offset = (1 if flags & 0x0040 else 0) + (4 if flags & 0x0001 else 0)
            data = data[offset:]
            if flags & 0x0002 or tag_unsynchronised:
                data = remove_unsynchronisation(data)
            if flags & 0x0008:
                data = inflate(data)
    except zlib.error:
        return b""
    return data


def parse_id3v2(buffer, meta, art):
    if len(buffer) < 10 or buffer[:3] != b"ID3":
        return
    major = buffer[3]
    flags = buffer[5]
    if major not in (2, 3, 4):
        return
    if major == 2 and flags & 0x40:
        return
    body = buffer[10:10 + synchsafe(buffer[6:10])]
    tag_unsynchronised = bool(flags & 0x80)
    if tag_unsynchronised and major < 4:
        body = remove_unsynchronisation(body)
    position = 0
    if major >= 3 and flags & 0x40 and len(body) >= 4:
        if major == 3:
            position = 4 + struct.unpack(">I", body[:4])[0]
        else:
            position = synchsafe(body[:4])
    id_length, header_length = (3, 6) if major == 2 else (4, 10)
    while position + header_length <= len(body):
        frame_id = body[position:position + id_length]
        if not ID3_FRAME_ID.fullmatch(frame_id):
            break
        if major == 2:
            frame_size = int.from_bytes(body[position + 3:position + 6], "big")
            frame_flags = 0
        else:
            if major == 4:
                frame_size = id3v24_frame_size(body, position)
            else:
                frame_size = struct.unpack(">I", body[position + 4:position + 8])[0]
            frame_flags = struct.unpack(">H", body[position + 8:position + 10])[0]
        data_start = position + header_length
        data_end = data_start + frame_size
        if frame_size <= 0 or data_end > len(body):
            break
        position = data_end
        name = frame_id.decode("ascii")
        field = ID3_TEXT_FRAMES.get(name)
        is_picture = name in ("APIC", "PIC")
        if not field and not is_picture:
            continue
        if field and meta.get(field):
            continue
        if is_picture and art.satisfied:
            continue
        payload = id3_frame_payload(
            body[data_start:data_end], major, frame_flags, tag_unsynchronised
        )
        if not payload:
            continue
        if field:
            put(meta, field, decode_id3_text(payload[0], payload[1:]))
        elif art.want:
            picture = parse_id3_picture(payload, name == "PIC")
            if picture:
                art.offer(*picture)
        else:
            art.mark()


def read_leading_id3(handle, meta, art):
    header = handle.read(10)
    if len(header) < 10 or header[:3] != b"ID3":
        return 0
    size = synchsafe(header[6:10])
    footer = 10 if header[3] == 4 and header[5] & 0x10 else 0
    if size <= MAX_TAG_BYTES:
        parse_id3v2(header + handle.read(size), meta, art)
    return 10 + size + footer


def parse_id3v1(tail, meta):
    if len(tail) != 128 or tail[:3] != b"TAG":
        return

    def field(data):
        return data.split(b"\x00", 1)[0].decode("latin-1", "replace")

    put(meta, "title", field(tail[3:33]))
    put(meta, "artist", field(tail[33:63]))
    put(meta, "album", field(tail[63:93]))
    if tail[125] == 0 and tail[126]:
        put(meta, "track", tail[126])


def parse_mpeg_header(word):
    if (word & 0xFFE00000) != 0xFFE00000:
        return None
    version = (word >> 19) & 0x3
    layer_bits = (word >> 17) & 0x3
    bitrate_index = (word >> 12) & 0xF
    rate_index = (word >> 10) & 0x3
    if version == 1 or layer_bits == 0 or bitrate_index in (0, 15) or rate_index == 3:
        return None
    mpeg1 = version == 3
    layer = 4 - layer_bits
    bitrate = MPEG_BITRATES[(mpeg1, layer)][bitrate_index] * 1000
    sample_rate = MPEG_SAMPLE_RATES[version][rate_index]
    padding = (word >> 9) & 0x1
    mono = ((word >> 6) & 0x3) == 3
    if layer == 1:
        samples = 384
        length = (12 * bitrate // sample_rate + padding) * 4
    else:
        samples = 1152 if mpeg1 or layer == 2 else 576
        length = samples // 8 * bitrate // sample_rate + padding
    return MpegFrame(mpeg1, layer, bitrate, sample_rate, samples, length, mono)


def find_mpeg_frame(buffer):
    limit = len(buffer) - 4
    index = 0
    while 0 <= index < limit:
        index = buffer.find(b"\xff", index)
        if index < 0 or index >= limit:
            return None, -1
        frame = parse_mpeg_header(struct.unpack_from(">I", buffer, index)[0])
        if frame and frame.length > 0:
            following = index + frame.length
            if following + 4 > len(buffer):
                return frame, index
            other = parse_mpeg_header(struct.unpack_from(">I", buffer, following)[0])
            if (
                other
                and other.sample_rate == frame.sample_rate
                and other.layer == frame.layer
            ):
                return frame, index
        index += 1
    return None, -1


def mpeg_duration(handle, start, file_size, has_id3v1):
    handle.seek(start)
    buffer = handle.read(MPEG_SCAN_BYTES)
    frame, index = find_mpeg_frame(buffer)
    if frame is None:
        return 0.0
    if frame.mpeg1:
        side_info = 17 if frame.mono else 32
    else:
        side_info = 9 if frame.mono else 17
    xing = index + 4 + side_info
    if buffer[xing:xing + 4] in (b"Xing", b"Info") and xing + 12 <= len(buffer):
        xing_flags, frames = struct.unpack_from(">II", buffer, xing + 4)
        if xing_flags & 0x1 and frames:
            return frames * frame.samples / frame.sample_rate
    vbri = index + 36
    if buffer[vbri:vbri + 4] == b"VBRI" and vbri + 18 <= len(buffer):
        frames = struct.unpack_from(">I", buffer, vbri + 14)[0]
        if frames:
            return frames * frame.samples / frame.sample_rate
    audio_bytes = file_size - (start + index) - (128 if has_id3v1 else 0)
    if frame.bitrate and audio_bytes > 0:
        return audio_bytes * 8 / frame.bitrate
    return 0.0


def probe_mpeg(handle, start, file_size, meta):
    has_id3v1 = False
    if file_size - start >= 128:
        handle.seek(file_size - 128)
        tail = handle.read(128)
        if tail[:3] == b"TAG":
            has_id3v1 = True
            parse_id3v1(tail, meta)
    meta["duration"] = mpeg_duration(handle, start, file_size, has_id3v1)


def parse_flac_picture(data):
    picture_type, mime_length = struct.unpack_from(">II", data, 0)
    position = 8
    mime = data[position:position + mime_length].decode("ascii", "replace")
    position += mime_length
    description_length = struct.unpack_from(">I", data, position)[0]
    position += 4 + description_length + 16
    image_length = struct.unpack_from(">I", data, position)[0]
    position += 4
    if mime == "-->":
        return None
    return picture_type, mime, data[position:position + image_length]


def parse_vorbis_comment(data, meta, art):
    try:
        vendor_length = struct.unpack_from("<I", data, 0)[0]
        position = 4 + vendor_length
        count = struct.unpack_from("<I", data, position)[0]
        position += 4
        for _ in range(count):
            if position + 4 > len(data):
                break
            length = struct.unpack_from("<I", data, position)[0]
            position += 4
            entry = data[position:position + length]
            position += length
            if len(entry) < length:
                break
            key, separator, value = entry.partition(b"=")
            if not separator:
                continue
            key = key.decode("ascii", "replace").upper()
            field = VORBIS_FIELDS.get(key)
            if field:
                put(meta, field, value.decode("utf-8", "replace"))
            elif key == "METADATA_BLOCK_PICTURE" and not art.satisfied:
                if art.want:
                    picture = parse_flac_picture(base64.b64decode(value))
                    if picture:
                        art.offer(*picture)
                else:
                    art.mark()
            elif key == "COVERART" and not art.satisfied:
                if art.want:
                    image = base64.b64decode(value)
                    art.offer(0, sniff_image(image), image)
                else:
                    art.mark()
    except (struct.error, ValueError):
        return


def parse_streaminfo(data, meta):
    if len(data) < 18:
        return
    packed = int.from_bytes(data[10:18], "big")
    sample_rate = packed >> 44
    total_samples = packed & 0xFFFFFFFFF
    if sample_rate and total_samples:
        meta["duration"] = total_samples / sample_rate


def probe_flac(handle, start, meta, art):
    handle.seek(start + 4)
    while True:
        header = handle.read(4)
        if len(header) < 4:
            return
        is_last = header[0] & 0x80
        block_type = header[0] & 0x7F
        length = int.from_bytes(header[1:4], "big")
        if block_type == 0:
            parse_streaminfo(handle.read(length), meta)
        elif block_type == 4 and length <= MAX_TAG_BYTES:
            parse_vorbis_comment(handle.read(length), meta, art)
        elif block_type == 6 and length <= MAX_TAG_BYTES and art.want and not art.satisfied:
            picture = parse_flac_picture(handle.read(length))
            if picture:
                art.offer(*picture)
        else:
            if block_type == 6:
                art.mark()
            handle.seek(length, os.SEEK_CUR)
        if is_last or block_type == 127:
            return


def read_ogg_packets(handle, count):
    packets = []
    pending = bytearray()
    serial = None
    while len(packets) < count:
        header = handle.read(27)
        if len(header) < 27 or header[:4] != b"OggS":
            break
        segments = handle.read(header[26])
        if len(segments) < header[26]:
            break
        body = handle.read(sum(segments))
        page_serial = header[14:18]
        if serial is None:
            serial = page_serial
        if page_serial != serial:
            continue
        offset = 0
        for lace in segments:
            pending += body[offset:offset + lace]
            offset += lace
            if lace < 255:
                packets.append(bytes(pending))
                pending = bytearray()
                if len(packets) == count:
                    break
        if len(pending) > MAX_TAG_BYTES:
            break
    return packets, serial


def last_ogg_granule(handle, file_size, serial):
    offset = max(0, file_size - OGG_TAIL_BYTES)
    handle.seek(offset)
    data = handle.read(file_size - offset)
    index = data.rfind(b"OggS")
    while index >= 0:
        if index + 18 <= len(data) and data[index + 14:index + 18] == serial:
            granule = struct.unpack_from("<q", data, index + 6)[0]
            if granule >= 0:
                return granule
        index = data.rfind(b"OggS", 0, index)
    return 0


def probe_ogg(handle, start, file_size, meta, art):
    handle.seek(start)
    packets, serial = read_ogg_packets(handle, 2)
    if not packets:
        return
    identification = packets[0]
    comments = packets[1] if len(packets) > 1 else b""
    sample_rate = 0
    pre_skip = 0
    if identification[:7] == b"\x01vorbis" and len(identification) >= 16:
        sample_rate = struct.unpack_from("<I", identification, 12)[0]
        if comments[:7] == b"\x03vorbis":
            parse_vorbis_comment(comments[7:], meta, art)
    elif identification[:8] == b"OpusHead" and len(identification) >= 12:
        sample_rate = 48000
        pre_skip = struct.unpack_from("<H", identification, 10)[0]
        if comments[:8] == b"OpusTags":
            parse_vorbis_comment(comments[8:], meta, art)
    elif identification[:5] == b"\x7fFLAC" and len(identification) >= 35:
        sample_rate = int.from_bytes(identification[27:35], "big") >> 44
        if comments and comments[0] & 0x7F == 4:
            parse_vorbis_comment(comments[4:], meta, art)
    if sample_rate and serial is not None:
        granule = last_ogg_granule(handle, file_size, serial)
        if granule > pre_skip:
            meta["duration"] = (granule - pre_skip) / sample_rate


def iter_atoms(data, start, end):
    position = start
    while position + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, position)
        header = 8
        if size == 1:
            if position + 16 > end:
                return
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            return
        yield kind, position + header, position + size
        position += size


def parse_mvhd(data, start, end, meta):
    if end - start < 20:
        return
    if data[start] == 1:
        if end - start < 32:
            return
        timescale, duration = struct.unpack_from(">IQ", data, start + 20)
    else:
        timescale, duration = struct.unpack_from(">II", data, start + 12)
    if timescale and duration:
        meta["duration"] = duration / timescale


def parse_mp4_meta(data, start, end, meta, art):
    child_start = start if data[start + 4:start + 8] == b"hdlr" else start + 4
    for kind, list_start, list_end in iter_atoms(data, child_start, end):
        if kind != b"ilst":
            continue
        for item, item_start, item_end in iter_atoms(data, list_start, list_end):
            for data_kind, data_start, data_end in iter_atoms(data, item_start, item_end):
                if data_kind != b"data" or data_end - data_start < 8:
                    continue
                data_type = int.from_bytes(data[data_start + 1:data_start + 4], "big")
                payload = data[data_start + 8:data_end]
                if item in MP4_TEXT_FIELDS:
                    put(meta, MP4_TEXT_FIELDS[item], payload.decode("utf-8", "replace"))
                elif item in (b"trkn", b"disk") and len(payload) >= 4:
                    field = "track" if item == b"trkn" else "disc"
                    put(meta, field, int.from_bytes(payload[2:4], "big"))
                elif item == b"covr":
                    if art.want:
                        art.offer(3, MP4_IMAGE_TYPES.get(data_type, "image/jpeg"), payload)
                    else:
                        art.mark()
                break


def probe_mp4(handle, start, file_size, meta, art):
    position = start
    while position + 8 <= file_size:
        handle.seek(position)
        header = handle.read(16)
        if len(header) < 8:
            return
        size, kind = struct.unpack_from(">I4s", header)
        header_size = 8
        if size == 1 and len(header) == 16:
            size = struct.unpack_from(">Q", header, 8)[0]
            header_size = 16
        elif size == 0:
            size = file_size - position
        if size < header_size:
            return
        if kind == b"moov":
            if size > MAX_MOOV_BYTES:
                return
            handle.seek(position)
            moov = handle.read(size)
            for child, child_start, child_end in iter_atoms(moov, header_size, len(moov)):
                if child == b"mvhd":
                    parse_mvhd(moov, child_start, child_end, meta)
                elif child == b"meta":
                    parse_mp4_meta(moov, child_start, child_end, meta, art)
                elif child == b"udta":
                    for sub, sub_start, sub_end in iter_atoms(moov, child_start, child_end):
                        if sub == b"meta":
                            parse_mp4_meta(moov, sub_start, sub_end, meta, art)
            return
        position += size


def parse_riff_info(data, meta):
    if data[:4] != b"INFO":
        return
    position = 4
    while position + 8 <= len(data):
        chunk_id, length = struct.unpack_from("<4sI", data, position)
        value = data[position + 8:position + 8 + length]
        position += 8 + length + (length & 1)
        field = RIFF_INFO_FIELDS.get(chunk_id)
        if field:
            put(meta, field, decode_loose(value))


def probe_wav(handle, start, file_size, meta, art):
    position = start + 12
    byte_rate = 0
    data_size = 0
    info = {}
    while position + 8 <= file_size:
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            break
        chunk_id, length = struct.unpack("<4sI", header)
        body = position + 8
        if chunk_id == b"fmt ":
            fmt = handle.read(min(length, 40))
            if len(fmt) >= 12:
                byte_rate = struct.unpack_from("<I", fmt, 8)[0]
        elif chunk_id == b"data":
            data_size = min(length, file_size - body)
        elif chunk_id == b"LIST" and length <= MAX_TAG_BYTES:
            parse_riff_info(handle.read(length), info)
        elif chunk_id in (b"id3 ", b"ID3 ") and length <= MAX_TAG_BYTES:
            parse_id3v2(handle.read(length), meta, art)
        position = body + length + (length & 1)
    for key, value in info.items():
        put(meta, key, value)
    if byte_rate and data_size:
        meta["duration"] = data_size / byte_rate


def probe(path, want_art=False):
    meta = {}
    art = ArtCollector(want_art)
    try:
        with open(path, "rb") as handle:
            file_size = os.fstat(handle.fileno()).st_size
            start = read_leading_id3(handle, meta, art)
            handle.seek(start)
            magic = handle.read(12)
            if magic[:4] == b"fLaC":
                probe_flac(handle, start, meta, art)
            elif magic[:4] == b"OggS":
                probe_ogg(handle, start, file_size, meta, art)
            elif magic[4:8] == b"ftyp":
                probe_mp4(handle, start, file_size, meta, art)
            elif magic[:4] == b"RIFF" and magic[8:12] == b"WAVE":
                probe_wav(handle, start, file_size, meta, art)
            else:
                probe_mpeg(handle, start, file_size, meta)
    except PROBE_ERRORS:
        pass
    return meta, art


def find_cover(directory, cache):
    if directory in cache:
        return cache[directory]
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    images = [
        name
        for name in names
        if not name.startswith(".")
        and os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
        and os.path.isfile(os.path.join(directory, name))
    ]
    best = next(
        (name for name in images if os.path.splitext(name)[0].lower() in COVER_STEMS),
        images[0] if images else None,
    )
    cache[directory] = os.path.join(directory, best) if best else None
    return cache[directory]


def guess_from_filename(stem):
    track, artist, title = 0, "", stem
    match = FILENAME_TRACK.match(stem)
    if match:
        track, title = int(match.group(1)), match.group(2)
    if " - " in title:
        artist, title = (part.strip() for part in title.split(" - ", 1))
    return track, artist, title.replace("_", " ").strip()


def normalise_name(value):
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = BRACKETED.sub(" ", text.casefold()).replace("&", " and ")
    return " ".join(NON_WORD.sub(" ", text).split())


def name_similarity(left, right):
    first = normalise_name(left)
    second = normalise_name(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    ratio = difflib.SequenceMatcher(None, first, second).ratio()
    if first in second or second in first:
        ratio = max(ratio, 0.85)
    return ratio


class Identity:
    contact = ""


class MusicBrainzGate:
    lock = threading.Lock()
    last = 0.0


def user_agent():
    return "BadBanana/%s ( %s )" % (VERSION, Identity.contact or "self-hosted music player")


def secure_art_url(url):
    if not isinstance(url, str) or not url:
        return None
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https"):
        return None
    if host not in COVER_ART_HOSTS and not host.endswith(".archive.org"):
        return None
    return url


class ArtRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not secure_art_url(new_url):
            return None
        return super().redirect_request(request, response, code, message, headers, new_url)


ART_OPENER = urllib.request.build_opener(ArtRedirectHandler)


def http_get(url, limit, deadline, opener=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("lookup time budget exhausted")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent(),
            "Accept": "application/json, image/*;q=0.9, */*;q=0.1",
        },
    )
    with (opener or urllib.request.build_opener()).open(
        request, timeout=min(ONLINE_REQUEST_TIMEOUT, remaining)
    ) as response:
        final_url = response.geturl()
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response larger than %d bytes" % limit)
    return data, final_url


def get_json(url, parameters, deadline):
    data, _ = http_get(
        "%s?%s" % (url, urllib.parse.urlencode(parameters)), ONLINE_JSON_LIMIT, deadline
    )
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("unexpected response")
    return payload


def musicbrainz_search(entity, query, deadline):
    with MusicBrainzGate.lock:
        wait = MusicBrainzGate.last + MUSICBRAINZ_INTERVAL - time.monotonic()
        if wait > 0:
            if time.monotonic() + wait >= deadline:
                raise TimeoutError("lookup time budget exhausted")
            time.sleep(wait)
        MusicBrainzGate.last = time.monotonic()
    return get_json(
        MUSICBRAINZ_API_URL % entity,
        {"query": query, "fmt": "json", "limit": MUSICBRAINZ_RESULTS},
        deadline,
    )


def lucene_phrase(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def artist_credit(credits):
    if not isinstance(credits, list):
        return ""
    parts = []
    for credit in credits:
        if isinstance(credit, dict):
            parts.append(str(credit.get("name") or ""))
            parts.append(str(credit.get("joinphrase") or ""))
    return "".join(parts).strip()


def cover_candidate(group_id, artist, album, title):
    if not isinstance(group_id, str) or not MBID.fullmatch(group_id):
        return None
    return ArtCandidate(artist, album, title, (COVER_ART_URL % group_id,))


def search_release_groups(track, deadline):
    query = "releasegroup:%s AND artist:%s" % (
        lucene_phrase(track["album"]),
        lucene_phrase(track["albumartist"]),
    )
    payload = musicbrainz_search("release-group", query, deadline)
    for item in payload.get("release-groups") or []:
        if not isinstance(item, dict):
            continue
        candidate = cover_candidate(
            item.get("id"),
            artist_credit(item.get("artist-credit")),
            str(item.get("title") or ""),
            "",
        )
        if candidate:
            yield candidate


def search_recordings(track, deadline):
    query = "recording:%s AND artist:%s" % (
        lucene_phrase(track["title"]),
        lucene_phrase(track["artist"]),
    )
    payload = musicbrainz_search("recording", query, deadline)
    seen = set()
    for item in payload.get("recordings") or []:
        if not isinstance(item, dict):
            continue
        artist = artist_credit(item.get("artist-credit"))
        title = str(item.get("title") or "")
        for release in item.get("releases") or []:
            if not isinstance(release, dict):
                continue
            group = release.get("release-group")
            group = group if isinstance(group, dict) else {}
            group_id = group.get("id")
            if group_id in seen:
                continue
            album = str(group.get("title") or release.get("title") or "")
            candidate = cover_candidate(group_id, artist, album, title)
            if candidate:
                seen.add(group_id)
                yield candidate


def rank_candidates(candidates, track, by_title):
    ranked = []
    album_known = track["album"] != UNKNOWN_ALBUM
    for order, candidate in enumerate(candidates):
        artist_score = max(
            name_similarity(track["artist"], candidate.artist),
            name_similarity(track["albumartist"], candidate.artist),
        )
        if artist_score < MATCH_THRESHOLD:
            continue
        if by_title:
            title_score = name_similarity(track["title"], candidate.title)
            if title_score < TITLE_MATCH_THRESHOLD:
                continue
            score = artist_score + title_score
            if album_known:
                score += 0.5 * name_similarity(track["album"], candidate.album)
        else:
            album_score = name_similarity(track["album"], candidate.album)
            if album_score < MATCH_THRESHOLD:
                continue
            score = artist_score + album_score
        ranked.append((-score, order, candidate))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in ranked]


def is_offline_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return False
    reason = getattr(error, "reason", None)
    return isinstance(error, urllib.error.URLError) and isinstance(reason, OSError)


class OnlineArt:
    def __init__(self, enabled):
        self.enabled = enabled
        self.directory = tempfile.mkdtemp(prefix="badbanana-art-") if enabled else None
        self.entries = {}
        self.misses = {}
        self.gates = {}
        self.matches = collections.OrderedDict()
        self.offline_until = 0.0
        self.lock = threading.Lock()

    @property
    def providers(self):
        return list(ONLINE_ART_PROVIDERS) if self.enabled else []

    def eligible(self, track):
        return self.enabled and track["artist"] != UNKNOWN_ARTIST

    def get(self, track):
        if not self.eligible(track):
            return None
        self.sweep()
        track_id = track["id"]
        with self.lock:
            gate = self.gates.setdefault(track_id, threading.Lock())
        try:
            with gate:
                return self.fetch(track)
        finally:
            with self.lock:
                if (
                    track_id not in self.entries
                    and self.gates.get(track_id) is gate
                    and not gate.locked()
                ):
                    del self.gates[track_id]

    def fetch(self, track):
        track_id = track["id"]
        cached = self.read(track_id)
        if cached:
            return cached
        key = "\x00".join(
            normalise_name(track[field]) for field in ("artist", "album", "title")
        )
        now = time.monotonic()
        with self.lock:
            if self.offline_until > now or self.misses.get(key, 0.0) > now:
                return None
        result = self.lookup(track)
        if result is None:
            with self.lock:
                self.misses[key] = time.monotonic() + ONLINE_MISS_TTL
            return None
        self.store(track, *result)
        return result

    def lookup(self, track):
        deadline = time.monotonic() + ONLINE_LOOKUP_BUDGET
        searches = [("song", search_recordings)]
        if track["album"] != UNKNOWN_ALBUM:
            searches.insert(0, ("album", search_release_groups))
        for kind, search in searches:
            fields = ("albumartist", "album") if kind == "album" else ("artist", "title")
            key = kind + "\x00" + "\x00".join(normalise_name(track[field]) for field in fields)
            try:
                urls = self.cached_matches(key)
                if urls is None:
                    ranked = rank_candidates(list(search(track, deadline)), track, kind == "song")
                    urls = [candidate.urls[0] for candidate in ranked[:ART_CANDIDATE_LIMIT]]
                    self.remember_matches(key, urls)
                image = self.download(urls, deadline) if urls else None
            except ONLINE_ERRORS as error:
                self.handle_failure(error)
                return None
            if image:
                return image[0], image[1], ONLINE_ART_PROVIDERS[0]
        return None

    def handle_failure(self, error):
        if is_offline_error(error):
            pause, message = ONLINE_OFFLINE_BACKOFF, "network unavailable (%s); using local art for 5 minutes"
        elif isinstance(error, urllib.error.HTTPError) and error.code in (429, 503):
            pause, message = MUSICBRAINZ_PAUSE, "musicbrainz is busy (%s); pausing lookups for a minute"
        else:
            log("art: musicbrainz lookup failed: %s" % error)
            return
        with self.lock:
            self.offline_until = time.monotonic() + pause
        log("art: " + message % error)

    def cached_matches(self, key):
        with self.lock:
            urls = self.matches.get(key)
            if urls is not None:
                self.matches.move_to_end(key)
            return urls

    def remember_matches(self, key, urls):
        with self.lock:
            self.matches[key] = urls
            while len(self.matches) > ART_MATCH_CACHE_SIZE:
                self.matches.popitem(last=False)

    def download(self, urls, deadline):
        for url in urls:
            try:
                data, final_url = http_get(url, ONLINE_IMAGE_LIMIT, deadline, ART_OPENER)
            except urllib.error.HTTPError:
                continue
            mime = detect_image(data)
            if secure_art_url(final_url) and mime in IMAGE_EXTENSIONS_BY_MIME:
                return data, mime
        return None

    def store(self, track, data, mime, provider):
        path = os.path.join(self.directory, track["id"] + IMAGE_EXTENSIONS_BY_MIME[mime])
        partial = path + ".part"
        with open(partial, "wb") as handle:
            handle.write(data)
        os.replace(partial, path)
        now = time.monotonic()
        with self.lock:
            self.entries[track["id"]] = {
                "path": path,
                "mime": mime,
                "source": provider,
                "title": track["title"],
                "created": now,
                "expires": now + max(0.0, track["duration"]) + ONLINE_ART_GRACE,
            }
            overflow = sorted(self.entries, key=lambda key: self.entries[key]["created"])
            overflow = overflow[: max(0, len(overflow) - ONLINE_ART_MAX_FILES)]
        log("art: fetched '%s' from %s (%d KB)" % (track["title"], provider, len(data) // 1024))
        for track_id in overflow:
            self.purge(track_id, "cache full")

    def read(self, track_id):
        with self.lock:
            entry = self.entries.get(track_id)
        if not entry:
            return None
        try:
            with open(entry["path"], "rb") as handle:
                return handle.read(), entry["mime"], entry["source"]
        except OSError:
            self.purge(track_id, "file missing")
            return None

    def purge(self, track_id, reason):
        with self.lock:
            entry = self.entries.pop(track_id, None)
            gate = self.gates.get(track_id)
            if gate is not None and not gate.locked():
                del self.gates[track_id]
        if not entry:
            return False
        try:
            os.remove(entry["path"])
        except OSError:
            pass
        log("art: purged '%s' (%s)" % (entry["title"], reason))
        return True

    def sweep(self):
        now = time.monotonic()
        with self.lock:
            expired = [key for key, entry in self.entries.items() if entry["expires"] <= now]
            self.misses = {key: until for key, until in self.misses.items() if until > now}
        for track_id in expired:
            self.purge(track_id, "expired")

    def close(self):
        if self.directory:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None


class Library:
    def __init__(self, root, online):
        self.root = os.path.realpath(os.path.expanduser(root))
        self.online = online
        self.tracks = []
        self.by_id = {}
        self.snapshot = (b"{}", gzip.compress(b"{}"))
        self.lock = threading.Lock()
        self.scan_lock = threading.Lock()
        self.art_cache = collections.OrderedDict()

    def scan(self):
        with self.scan_lock:
            started = time.monotonic()
            found = []
            covers = {}
            visited = set()
            for directory, subdirectories, filenames in os.walk(self.root, followlinks=True):
                real = os.path.realpath(directory)
                if real in visited:
                    subdirectories[:] = []
                    continue
                visited.add(real)
                subdirectories[:] = sorted(
                    name for name in subdirectories if not name.startswith(".")
                )
                for name in sorted(filenames):
                    extension = os.path.splitext(name)[1].lower()
                    if name.startswith(".") or extension not in AUDIO_TYPES:
                        continue
                    path = os.path.join(directory, name)
                    try:
                        found.append(self.read_track(path, extension, covers))
                    except Exception as error:
                        log("skipped %s: %s" % (clean_text(path), error))
                        continue
                    if len(found) % SCAN_LOG_EVERY == 0:
                        log("  ... %s" % plural(len(found), "track"))
            found.sort(
                key=lambda track: (
                    track["albumartist"].lower(),
                    track["album"].lower(),
                    track["disc"],
                    track["track"],
                    track["title"].lower(),
                    track["path"],
                )
            )
            elapsed = time.monotonic() - started
            snapshot = self.build_snapshot(found, elapsed)
            with self.lock:
                self.tracks = found
                self.by_id = {track["id"]: track for track in found}
                self.snapshot = snapshot
                self.art_cache.clear()
            log("indexed %s in %.1fs" % (plural(len(found), "track"), elapsed))
            return len(found)

    def read_track(self, path, extension, covers):
        relative = os.path.relpath(path, self.root)
        track_id = hashlib.sha1(relative.encode("utf-8", "surrogateescape")).hexdigest()[:12]
        stem = os.path.splitext(os.path.basename(path))[0]
        parent = os.path.basename(os.path.dirname(path)) if os.path.dirname(relative) else ""
        guessed_track, guessed_artist, guessed_title = guess_from_filename(stem)
        meta, art = probe(path)
        cover = None if art.found else find_cover(os.path.dirname(path), covers)
        artist = (
            clean_text(meta.get("artist"))
            or clean_text(meta.get("albumartist"))
            or clean_text(guessed_artist)
            or UNKNOWN_ARTIST
        )
        return {
            "id": track_id,
            "path": path,
            "ext": extension.lstrip("."),
            "mime": AUDIO_TYPES[extension],
            "title": clean_text(meta.get("title"))
            or clean_text(guessed_title)
            or clean_text(stem)
            or "Untitled",
            "artist": artist,
            "albumartist": clean_text(meta.get("albumartist")) or artist,
            "album": clean_text(meta.get("album")) or clean_text(parent) or UNKNOWN_ALBUM,
            "track": parse_number(meta.get("track")) or guessed_track,
            "disc": parse_number(meta.get("disc")),
            "duration": round(float(meta.get("duration") or 0.0), 2),
            "size": os.path.getsize(path),
            "art": "embedded" if art.found else ("file" if cover else None),
            "cover_file": cover,
        }

    def build_snapshot(self, tracks, elapsed):
        public_keys = (
            "id",
            "title",
            "artist",
            "albumartist",
            "album",
            "track",
            "disc",
            "duration",
            "size",
            "ext",
        )
        payload = {
            "name": "badbanana",
            "version": VERSION,
            "host": clean_text(platform.node()) or "badbanana",
            "machine": platform.machine(),
            "python": platform.python_version(),
            "root": clean_text(os.path.basename(self.root) or self.root),
            "scan_seconds": round(elapsed, 2),
            "online_art": self.online.providers,
            "count": len(tracks),
            "albums": len({(track["album"], track["albumartist"]) for track in tracks}),
            "artists": len({track["artist"] for track in tracks}),
            "tracks": [
                dict(
                    {key: track[key] for key in public_keys},
                    art=bool(track["art"]) or self.online.eligible(track),
                )
                for track in tracks
            ],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return raw, gzip.compress(raw, 6)

    def get(self, track_id):
        with self.lock:
            return self.by_id.get(track_id)

    def get_snapshot(self):
        with self.lock:
            return self.snapshot

    def artwork(self, track_id):
        track = self.get(track_id)
        if not track:
            return None
        fetched = self.online.get(track)
        if fetched:
            return fetched
        return self.local_art(track)

    def local_art(self, track):
        if not track["art"]:
            return None
        track_id = track["id"]
        with self.lock:
            cached = self.art_cache.get(track_id)
            if cached:
                self.art_cache.move_to_end(track_id)
                return cached
        result = None
        if track["art"] == "embedded":
            embedded = probe(track["path"], want_art=True)[1].result()
            result = embedded + ("embedded",) if embedded else None
        elif track["cover_file"]:
            try:
                with open(track["cover_file"], "rb") as handle:
                    data = handle.read(MAX_TAG_BYTES)
                result = (data, sniff_image(data), "folder") if data else None
            except OSError:
                result = None
        if result:
            with self.lock:
                self.art_cache[track_id] = result
                while len(self.art_cache) > ART_CACHE_SIZE:
                    self.art_cache.popitem(last=False)
        return result


def system_status(root):
    status = {"host": clean_text(platform.node()) or "badbanana", "time": time.time()}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as handle:
            status["temp_c"] = round(int(handle.read().strip()) / 1000.0, 1)
    except (OSError, ValueError):
        status["temp_c"] = None
    try:
        status["load"] = [round(value, 2) for value in os.getloadavg()]
    except (OSError, AttributeError):
        status["load"] = None
    try:
        with open("/proc/uptime") as handle:
            status["uptime_s"] = int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        status["uptime_s"] = None
    try:
        usage = shutil.disk_usage(root)
        status["disk_free_gb"] = round(usage.free / 1e9, 1)
        status["disk_total_gb"] = round(usage.total / 1e9, 1)
    except OSError:
        status["disk_free_gb"] = None
        status["disk_total_gb"] = None
    return status


def parse_range(header, size):
    match = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header or "")
    if not match:
        return "ignore"
    first, last = match.groups()
    if size == 0 or (first == "" and last == ""):
        return None
    if first == "":
        suffix = int(last)
        if suffix == 0:
            return None
        return max(0, size - suffix), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        return None
    return start, end


def accepts_gzip(header):
    for part in (header or "").split(","):
        name, _, parameters = part.partition(";")
        if name.strip().lower() != "gzip":
            continue
        quality = 1.0
        for parameter in parameters.split(";"):
            key, _, value = parameter.partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        return quality > 0
    return False


ICON_FILL = 'fill="currentColor"'
ICON_STROKE = (
    'fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="square" stroke-linejoin="miter"'
)
REPEAT_LOOP = (
    '<path d="M4 12V7h14"/><path d="M16 4l3 3-3 3"/>'
    '<path d="M20 12v5H6"/><path d="M8 14l-3 3 3 3"/>'
)
ICONS = {
    "play": '<path %s d="M7 4 20 12 7 20Z"/>' % ICON_FILL,
    "pause": '<path %s d="M6 4h4v16H6zM14 4h4v16h-4z"/>' % ICON_FILL,
    "previous": '<path %s d="M4 4h3v16H4zM20 4 8 12l12 8z"/>' % ICON_FILL,
    "next": '<path %s d="M20 4h-3v16h3zM4 4l12 8-12 8z"/>' % ICON_FILL,
    "shuffle": (
        '<g %s><path d="M3 7h4l10 10h2.6"/><path d="M3 17h4l10-10h2.6"/>'
        '<path d="M17.6 4l3 3-3 3"/><path d="M17.6 14l3 3-3 3"/></g>' % ICON_STROKE
    ),
    "shuffle-off": (
        '<g %s><path d="M3 7h16.6"/><path d="M3 17h16.6"/>'
        '<path d="M17.6 4l3 3-3 3"/><path d="M17.6 14l3 3-3 3"/></g>' % ICON_STROKE
    ),
    "repeat": '<g %s>%s</g>' % (ICON_STROKE, REPEAT_LOOP),
    "repeat-one": (
        '<g %s>%s<path stroke-width="1.6" stroke-linecap="butt" d="M10.9 11.2 12.6 10v5"/></g>'
        % (ICON_STROKE, REPEAT_LOOP)
    ),
    "repeat-off": '<g %s>%s<path d="M5 5l14 14"/></g>' % (ICON_STROKE, REPEAT_LOOP),
    "volume": (
        '<path %s d="M2.5 9h4l5-5v16l-5-5h-4z"/>'
        '<g %s stroke-linecap="butt"><path d="M15 9a4 4 0 0 1 0 6"/>'
        '<path d="M18 6a8 8 0 0 1 0 12"/></g>' % (ICON_FILL, ICON_STROKE)
    ),
    "volume-off": (
        '<path %s d="M2.5 9h4l5-5v16l-5-5h-4z"/>'
        '<g %s><path d="M14.8 9l5.5 6M20.3 9l-5.5 6"/></g>' % (ICON_FILL, ICON_STROKE)
    ),
    "playing": '<path %s d="M4 11h4v9H4zM10 4h4v16h-4zM16 14h4v6h-4z"/>' % ICON_FILL,
    "up-next": (
        '<g %s><path d="M5.2 5.4l6.6 6.6-6.6 6.6"/><path d="M12 5.4l6.6 6.6-6.6 6.6"/></g>' % ICON_STROKE
    ),
}


def icon_svg(name, color="currentColor"):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
        "%s</svg>" % ICONS[name].replace("currentColor", color)
    )


def icon_sprite():
    symbols = "".join(
        '<symbol id="icon-%s" viewBox="0 0 24 24">%s</symbol>' % (name, markup)
        for name, markup in ICONS.items()
    )
    return '<svg xmlns="http://www.w3.org/2000/svg" hidden aria-hidden="true">%s</svg>' % symbols


def icon_mask(name):
    return "data:image/svg+xml," + urllib.parse.quote(icon_svg(name, "#000"), safe=" ,./:=-")


class Page:
    def __init__(self):
        style = PAGE_STYLE.replace("{{ICON_PLAYING}}", icon_mask("playing")).replace(
            "{{ICON_UP_NEXT}}", icon_mask("up-next")
        )
        style_hash = base64.b64encode(hashlib.sha256(style.encode("utf-8")).digest())
        script_hash = base64.b64encode(hashlib.sha256(PAGE_SCRIPT.encode("utf-8")).digest())
        html = (
            PAGE_TEMPLATE.replace("{{VERSION}}", VERSION, 1)
            .replace("{{ICONS}}", icon_sprite(), 1)
            .replace("{{STYLE}}", style, 1)
            .replace("{{SCRIPT}}", PAGE_SCRIPT, 1)
        )
        self.raw = html.encode("utf-8")
        self.gzip = gzip.compress(self.raw, 9)
        self.headers = {
            "Cache-Control": "no-cache",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "; ".join(
                [
                    "default-src 'none'",
                    "script-src 'sha256-%s'" % script_hash.decode("ascii"),
                    "style-src 'sha256-%s'" % style_hash.decode("ascii"),
                    "img-src 'self' data: blob:",
                    "media-src 'self' blob:",
                    "connect-src 'self'",
                    "base-uri 'none'",
                    "form-action 'none'",
                    "frame-ancestors 'none'",
                ]
            ),
        }


class BadBananaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, library, password, page):
        self.library = library
        self.password = password
        self.page = page
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, RequestHandler)

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, CLIENT_GONE_ERRORS) or not Console.enabled():
            return
        super().handle_error(request, client_address)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "BadBanana/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = SOCKET_TIMEOUT

    def version_string(self):
        return self.server_version

    def log_message(self, format, *args):
        if not Console.enabled() or getattr(self, "path", "").startswith("/api/status"):
            return
        sys.stderr.write("%s %s %s\n" % (timestamp(), self.address_string(), format % args))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def send_body(self, status, body, content_type, headers=None, head=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not head and body:
            self.wfile.write(body)

    def send_text(self, status, text, head=False, headers=None):
        self.send_body(status, text.encode("utf-8"), "text/plain; charset=utf-8", headers, head)

    def send_compressible(self, raw, compressed, content_type, headers, head):
        headers = dict(headers, Vary="Accept-Encoding")
        body = raw
        if len(raw) >= GZIP_MIN_BYTES and accepts_gzip(self.headers.get("Accept-Encoding")):
            body = compressed
            headers["Content-Encoding"] = "gzip"
        self.send_body(HTTPStatus.OK, body, content_type, headers, head)

    def send_json(self, payload, head=False):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_body(
            HTTPStatus.OK,
            raw,
            "application/json; charset=utf-8",
            {"Cache-Control": "no-store"},
            head,
        )

    def authorized(self, head):
        password = self.server.password
        if not password:
            return True
        header = self.headers.get("Authorization", "")
        if header[:6].lower() == "basic ":
            try:
                credentials = base64.b64decode(header[6:].strip(), validate=True)
                supplied = credentials.split(b":", 1)[1] if b":" in credentials else b""
                if hmac.compare_digest(supplied, password.encode("utf-8")):
                    return True
            except ValueError:
                pass
        self.send_text(
            HTTPStatus.UNAUTHORIZED,
            "authentication required\n",
            head,
            {"WWW-Authenticate": 'Basic realm="badbanana", charset="UTF-8"'},
        )
        return False

    def do_GET(self):
        self.dispatch(head=False)

    def do_HEAD(self):
        self.dispatch(head=True)

    def accept_write(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_POST_BYTES:
            self.close_connection = True
            self.send_text(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request too large\n")
            return False
        if length:
            self.rfile.read(length)
        if not self.authorized(head=False):
            return False
        if self.headers.get(CSRF_HEADER) != "1":
            self.send_text(HTTPStatus.FORBIDDEN, "missing %s header\n" % CSRF_HEADER)
            return False
        return True

    def do_POST(self):
        try:
            if not self.accept_write():
                return
            if urlsplit(self.path).path != "/api/rescan":
                self.send_text(HTTPStatus.NOT_FOUND, "not found\n")
                return
            count = self.server.library.scan()
            self.send_json({"ok": True, "count": count})
        except CLIENT_GONE_ERRORS:
            self.close_connection = True

    def do_DELETE(self):
        try:
            if not self.accept_write():
                return
            match = ART_PURGE_ROUTE.fullmatch(urlsplit(self.path).path)
            if not match:
                self.send_text(HTTPStatus.NOT_FOUND, "not found\n")
                return
            purged = self.server.library.online.purge(match.group(1), "track finished")
            self.send_json({"ok": True, "purged": purged})
        except CLIENT_GONE_ERRORS:
            self.close_connection = True

    def dispatch(self, head):
        try:
            if not self.authorized(head):
                return
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                page = self.server.page
                self.send_compressible(
                    page.raw, page.gzip, "text/html; charset=utf-8", page.headers, head
                )
            elif path == "/api/library":
                raw, compressed = self.server.library.get_snapshot()
                self.send_compressible(
                    raw,
                    compressed,
                    "application/json; charset=utf-8",
                    {"Cache-Control": "no-store"},
                    head,
                )
            elif path == "/api/status":
                self.send_json(system_status(self.server.library.root), head)
            else:
                match = TRACK_ROUTE.fullmatch(path)
                track = self.server.library.get(match.group(2)) if match else None
                if not match:
                    self.send_text(HTTPStatus.NOT_FOUND, "not found\n", head)
                elif not track:
                    self.send_text(HTTPStatus.NOT_FOUND, "no such track\n", head)
                elif match.group(1) == "stream":
                    self.send_stream(track, head)
                else:
                    self.send_art(track, head)
        except CLIENT_GONE_ERRORS:
            self.close_connection = True

    def send_art(self, track, head):
        art = self.server.library.artwork(track["id"])
        if not art:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        data, mime, source = art
        self.send_body(
            HTTPStatus.OK,
            data,
            mime,
            {
                "Cache-Control": "no-store",
                "Cross-Origin-Resource-Policy": "same-origin",
                "X-Art-Source": source,
            },
            head,
        )

    def send_stream(self, track, head):
        try:
            handle = open(track["path"], "rb")
        except OSError:
            self.send_text(HTTPStatus.NOT_FOUND, "file missing\n", head)
            return
        with handle:
            stat = os.fstat(handle.fileno())
            size = stat.st_size
            etag = '"%x-%x"' % (int(stat.st_mtime), size)
            start, end, status = 0, size - 1, HTTPStatus.OK
            range_header = self.headers.get("Range")
            if_range = self.headers.get("If-Range")
            if range_header and (not if_range or if_range == etag):
                requested = parse_range(range_header, size)
                if requested is None:
                    self.send_body(
                        HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                        b"",
                        "text/plain; charset=utf-8",
                        {"Content-Range": "bytes */%d" % size},
                        head,
                    )
                    return
                if requested != "ignore":
                    start, end = requested
                    status = HTTPStatus.PARTIAL_CONTENT
            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header("Content-Type", track["mime"])
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", email.utils.formatdate(stat.st_mtime, usegmt=True))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.end_headers()
            if head:
                return
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    self.close_connection = True
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def lan_address():
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe_socket.connect(("10.255.255.255", 1))
        return probe_socket.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe_socket.close()


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        description="BAD BANANA - terminal-style music streaming server"
    )
    parser.add_argument(
        "-m",
        "--music",
        default=os.environ.get("BADBANANA_DIR", "~/Music"),
        help="music folder to serve (default: ~/Music)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("BADBANANA_HOST", "0.0.0.0"),
        help="address to listen on (default: all interfaces)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=port_number,
        default=os.environ.get("BADBANANA_PORT", "8080"),
        help="port to listen on (default: 8080)",
    )
    parser.add_argument(
        "--no-online-art",
        action="store_true",
        default=os.environ.get("BADBANANA_ONLINE_ART", "1").strip().lower() in FALSE_WORDS,
        help="only use art embedded in files or found in album folders",
    )
    parser.add_argument(
        "--contact",
        default=os.environ.get("BADBANANA_CONTACT", MUSICBRAINZ_CONTACT),
        help="email or project URL sent to MusicBrainz with album art lookups",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=os.environ.get("BADBANANA_VERBOSE", "0").strip().lower() not in FALSE_WORDS,
        help="keep logging requests and album art activity after startup",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("BADBANANA_PASSWORD") or None,
        help="require this password via HTTP basic auth (any username)",
    )
    return parser.parse_args(argv)


def stop_on_signal(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    arguments = parse_arguments(argv)
    Console.verbose = arguments.verbose
    Identity.contact = clean_text(arguments.contact)[:200]
    root = os.path.realpath(os.path.expanduser(arguments.music))
    if not os.path.isdir(root):
        print("music folder not found: %s  (use --music /path/to/music)" % root)
        return 2
    online = OnlineArt(enabled=not arguments.no_online_art)
    atexit.register(online.close)
    library = Library(root, online)
    print(BANNER)
    if online.enabled:
        log("online album art: musicbrainz + cover art archive")
        if Console.verbose:
            log("temporary art folder: %s" % online.directory)
    else:
        log("online album art disabled: using embedded and folder art only")
    log("scanning %s" % library.root)
    library.scan()
    try:
        server = BadBananaServer(
            (arguments.host, arguments.port), library, arguments.password, Page()
        )
    except OSError as error:
        log("cannot listen on %s:%d: %s" % (arguments.host, arguments.port, error))
        return 1
    signal.signal(signal.SIGTERM, stop_on_signal)
    if arguments.host in ("0.0.0.0", "::", ""):
        shown_host = lan_address()
    elif ":" in arguments.host:
        shown_host = "[%s]" % arguments.host
    else:
        shown_host = arguments.host
    log(
        "serving on http://%s:%d%s"
        % (shown_host, arguments.port, "   (password protected)" if arguments.password else "")
    )
    log("press ctrl+c to quit")
    Console.serving = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(flush=True)
        log("shutting down")
    finally:
        server.server_close()
        online.close()
    return 0


PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#050d2b">
<meta name="color-scheme" content="dark">
<title>BAD BANANA</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%23050d2b'/%3E%3Ctext x='3' y='13' font-family='monospace' font-size='13' fill='%23c6ff1a'%3E%3E%3C/text%3E%3C/svg%3E">
<style>{{STYLE}}</style>
</head>
<body class="hyper">
{{ICONS}}
<div id="boot" role="status" aria-live="polite"></div>
<header>
<pre id="logo" aria-label="BAD BANANA">╔╗ ╔═╗╔╦╗  ╔╗ ╔═╗╔╗╔╔═╗╔╗╔╔═╗
╠╩╗╠═╣ ║║  ╠╩╗╠═╣║║║╠═╣║║║╠═╣
╚═╝╩ ╩═╩╝  ╚═╝╩ ╩╝╚╝╩ ╩╝╚╝╩ ╩ <small>v{{VERSION}}</small></pre>
<div id="sys">
<div id="clock">--:--:--</div>
<div id="sysline">connecting…</div>
</div>
</header>
<main>
<section id="left">
<div class="panel" id="now-playing">
<div class="ttl">NOW PLAYING</div>
<div class="ttr" id="art-label"></div>
<div id="artbox">
<canvas id="art" role="img" aria-label="album art"></canvas>
</div>
<div class="kv"><span class="k">TITLE  │ </span><span id="np-title" class="v hi"></span></div>
<div class="kv"><span class="k">ARTIST │ </span><span id="np-artist" class="v"></span></div>
<div class="kv"><span class="k">ALBUM  │ </span><span id="np-album" class="v"></span></div>
<div class="kv"><span class="k">FILE   │ </span><span id="np-meta" class="v dim"></span></div>
<div class="kv"><span class="k">NEXT   │ </span><span id="np-next" class="v dim">—</span></div>
<div id="progress" class="line">
<span id="elapsed">--:--</span>
<span id="seekbar" class="bar" role="slider" aria-label="seek" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"></span>
<span id="duration">--:--</span>
</div>
<div id="controls" class="line">
<button type="button" class="btn" data-action="prev" title="previous (p)" aria-label="previous track">[<svg class="icon" aria-hidden="true" focusable="false"><use href="#icon-previous"></use></svg>]</button>
<button type="button" class="btn" data-action="toggle" id="btn-toggle" title="play/pause (space)" aria-label="play">[<svg class="icon" aria-hidden="true" focusable="false"><use href="#icon-play"></use></svg>]</button>
<button type="button" class="btn" data-action="next" title="next (n)" aria-label="next track">[<svg class="icon" aria-hidden="true" focusable="false"><use href="#icon-next"></use></svg>]</button>
<button type="button" class="btn gap" data-action="shuffle" id="btn-shuffle" title="shuffle (s)" aria-label="shuffle on" aria-pressed="true">[<svg class="icon" aria-hidden="true" focusable="false"><use href="#icon-shuffle"></use></svg>]</button>
<button type="button" class="btn" data-action="repeat" id="btn-repeat" title="repeat (r)" aria-label="repeat all">[<svg class="icon" aria-hidden="true" focusable="false"><use href="#icon-repeat"></use></svg>]</button>
</div>
<div id="volume" class="line">
<span class="volume-control">VOL <span id="volume-slider">[<span id="volbar" class="bar" role="slider" tabindex="0" aria-label="volume" aria-valuemin="0" aria-valuemax="100" aria-valuenow="100"></span>]</span></span>
<span class="volume-control" id="volpct">100%</span>
<span class="volume-device">VOL  device buttons</span>
<button type="button" class="btn" data-action="mute" id="btn-mute" title="mute (m)" aria-label="mute" aria-pressed="false">[<svg class="icon" aria-hidden="true" focusable="false"><use href="#icon-volume"></use></svg>]</button>
</div>
</div>
<div class="panel" id="spectrum-panel">
<div class="ttl">SPECTRUM</div>
<div class="ttr" id="spectrum-label">idle</div>
<div id="spectrum" aria-hidden="true"></div>
<div id="spectrum-axis" class="dim" aria-hidden="true"></div>
</div>
</section>
<section id="right">
<div class="panel" id="library-panel">
<div class="ttl">LIBRARY</div>
<div class="ttr" id="library-count"></div>
<div id="list" role="listbox" aria-label="library"></div>
</div>
<div class="panel" id="activity-panel">
<div class="ttl">ACTIVITY</div>
<div class="ttr">type help below</div>
<div id="activity" role="log" aria-live="polite"></div>
</div>
</section>
</main>
<footer>
<div id="status">
<span id="status-left">-- STOPPED --</span>
<span id="status-right"></span>
</div>
<div id="terminal" role="log" aria-live="polite" aria-label="command output" hidden></div>
<form id="command-form" autocomplete="off">
<label id="prompt" for="command">guest@badbanana:~/music$</label>
<input id="command" name="command" type="text" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go" placeholder="type help">
</form>
</footer>
<audio id="deck-a" preload="auto"></audio>
<audio id="deck-b" preload="auto"></audio>
<span id="measure" aria-hidden="true"></span>
<script>{{SCRIPT}}</script>
</body>
</html>
"""

PAGE_STYLE = r"""
:root {
    --fg: #c6ff1a;
    --dim: #7f9f22;
    --faint: #1b2c5c;
    --bg: #050d2b;
    --hi: #efff9a;
    --glow: rgba(198, 255, 26, 0.45);
    --err: #ff6b8b;
    --warn: #ffd75f;
}

body.green {
    --fg: #33ff66;
    --dim: #1c8a3c;
    --faint: #0d3d1a;
    --bg: #040a05;
    --hi: #c2ffd2;
    --glow: rgba(51, 255, 102, 0.45);
}

body.amber {
    --fg: #ffb000;
    --dim: #a06a00;
    --faint: #3d2900;
    --bg: #0b0700;
    --hi: #ffe3a6;
    --glow: rgba(255, 176, 0, 0.45);
}

body.ice {
    --fg: #cfe3ff;
    --dim: #6f86a8;
    --faint: #222c3d;
    --bg: #05070b;
    --hi: #ffffff;
    --glow: rgba(160, 200, 255, 0.35);
}

*,
*::before,
*::after {
    box-sizing: border-box;
}

[hidden] {
    display: none !important;
}

html,
body {
    margin: 0;
    height: 100%;
    background: var(--bg);
    color: var(--fg);
    font: 14px/1.35 "DejaVu Sans Mono", "IBM Plex Mono", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    -webkit-text-size-adjust: 100%;
    text-size-adjust: 100%;
}

body {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    text-shadow: 0 0 4px var(--glow);
}

::selection {
    background: var(--fg);
    color: var(--bg);
}

.dim {
    color: var(--dim);
}

.hi {
    color: var(--hi);
}

#measure {
    position: absolute;
    top: 0;
    left: -9999px;
    visibility: hidden;
    white-space: pre;
}

header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 16px;
    padding: 12px 16px 2px;
}

#logo {
    margin: 0;
    line-height: 1.05;
    color: var(--hi);
    white-space: pre;
}

#logo small {
    color: var(--dim);
    font-size: 1em;
}

.boot-logo {
    margin: 0;
    line-height: 1.05;
    font: inherit;
    white-space: pre;
}

#sys {
    text-align: right;
    color: var(--dim);
    white-space: nowrap;
    line-height: 1.4;
}

main {
    flex: 1;
    display: grid;
    grid-template-columns: minmax(340px, 40%) minmax(0, 1fr);
    gap: 20px;
    padding: 18px 14px 4px;
    min-height: 0;
}

#left,
#right {
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-height: 0;
    min-width: 0;
}

#left {
    overflow-x: hidden;
    overflow-y: auto;
    padding-top: 8px;
    margin-top: -8px;
}

.panel {
    position: relative;
    min-width: 0;
    min-height: 0;
    padding: 14px 12px 10px;
    border: 3px double var(--dim);
}

.panel > .ttl,
.panel > .ttr {
    position: absolute;
    top: -0.78em;
    padding: 0 6px;
    background: var(--bg);
    white-space: nowrap;
}

.panel > .ttl {
    left: 12px;
    color: var(--hi);
    letter-spacing: 0.08em;
}

.panel > .ttl::before {
    content: "╡ ";
    color: var(--dim);
}

.panel > .ttl::after {
    content: " ╞";
    color: var(--dim);
}

.panel > .ttr {
    right: 12px;
    color: var(--dim);
}

#now-playing {
    flex: none;
}

#artbox {
    display: flex;
    justify-content: center;
    margin: 2px 0 10px;
}

#art {
    display: block;
    width: 300px;
    height: 300px;
    user-select: none;
}

#art.glow {
    filter: drop-shadow(0 0 3px var(--glow));
}

.kv {
    display: flex;
    overflow: hidden;
    white-space: nowrap;
}

.kv .k {
    flex: none;
    color: var(--dim);
    white-space: pre;
}

.kv .v {
    overflow: hidden;
    text-overflow: ellipsis;
}

.line {
    margin-top: 6px;
    overflow: hidden;
    white-space: nowrap;
}

#progress {
    margin-top: 10px;
}

.bar {
    cursor: pointer;
    touch-action: none;
    user-select: none;
}

.btn {
    margin: 0;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-shadow: inherit;
    cursor: pointer;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
}

.btn.gap {
    margin-left: 1ch;
}

.icon {
    display: inline-block;
    width: 1.2em;
    height: 1.2em;
    margin: 0 0.3ch;
    vertical-align: -0.27em;
    overflow: visible;
    filter: drop-shadow(0 0 2px var(--glow));
}

#volume-slider {
    padding: 4px 0;
    cursor: pointer;
    touch-action: none;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
}

#volbar:focus-visible {
    outline: 0;
    background: var(--fg);
    color: var(--bg);
    text-shadow: none;
}

.volume-device {
    display: none;
    color: var(--dim);
}

#volume.device .volume-control {
    display: none;
}

#volume.device .volume-device {
    display: inline;
}

.btn:focus-visible {
    outline: 0;
    background: var(--fg);
    color: var(--bg);
    text-shadow: none;
}

@media (hover: hover) {
    .btn:hover {
        background: var(--fg);
        color: var(--bg);
        text-shadow: none;
    }

    .row:hover {
        background: var(--faint);
    }
}

.btn.on {
    color: var(--hi);
}

.btn.off {
    color: var(--dim);
}

#spectrum-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 9em;
}

#spectrum {
    position: relative;
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    min-height: 4em;
    overflow: hidden;
    line-height: 1;
    white-space: pre;
}

#spectrum .vh {
    color: var(--hi);
}

#spectrum .peaks {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    color: var(--hi);
    pointer-events: none;
}

#spectrum .peaks > div {
    flex: none;
    height: 1em;
}

#spectrum .p1 {
    opacity: 0.2;
}

#spectrum .p2 {
    opacity: 0.4;
}

#spectrum .p3 {
    opacity: 0.6;
}

#spectrum .p4 {
    opacity: 0.8;
}

#spectrum .p5 {
    opacity: 1;
}

#spectrum.quiet,
#spectrum.quiet .vh {
    color: var(--dim);
}

#spectrum-axis {
    overflow: hidden;
    line-height: 1.2;
    white-space: pre;
}

#library-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
}

#list {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    scrollbar-color: var(--dim) transparent;
    scrollbar-width: thin;
}

.row {
    display: flex;
    gap: 1ch;
    padding: 0 0.5ch;
    white-space: nowrap;
    cursor: pointer;
}

.row .n {
    flex: none;
    color: var(--dim);
}

.row .m {
    flex: none;
    align-self: center;
    width: 1em;
    height: 1em;
    color: var(--hi);
}

.row .t {
    flex: 1 1 58%;
    overflow: hidden;
    text-overflow: ellipsis;
}

.row .a {
    flex: 1 1 32%;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--dim);
}

.row .d {
    flex: none;
    color: var(--dim);
}

.row.cur {
    color: var(--hi);
}

.row.cur .m,
.row.nxt .m {
    background-color: currentColor;
    -webkit-mask: var(--marker) center / contain no-repeat;
    mask: var(--marker) center / contain no-repeat;
}

.row.cur .m {
    --marker: url("{{ICON_PLAYING}}");
}

.row.nxt .m {
    --marker: url("{{ICON_UP_NEXT}}");
    color: var(--dim);
}

.row.sel {
    background: var(--fg);
    color: var(--bg);
    text-shadow: none;
}

.row.sel .n,
.row.sel .a,
.row.sel .d,
.row.sel .m {
    color: var(--bg);
}

.grp {
    margin-top: 0.7em;
    padding: 0 0.5ch;
    overflow: hidden;
    color: var(--dim);
    white-space: nowrap;
}

.grp:first-child {
    margin-top: 0;
}

.grp b {
    color: var(--fg);
    font-weight: normal;
}

.empty {
    padding: 1em 0.5ch;
    color: var(--dim);
    white-space: pre-wrap;
}

#activity-panel {
    flex: none;
}

#activity {
    height: 7.2em;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    scrollbar-color: var(--dim) transparent;
    scrollbar-width: thin;
}

.l-err {
    color: var(--err);
}

.l-warn {
    color: var(--warn);
}

.l-dim {
    color: var(--dim);
}

.l-hi {
    color: var(--hi);
}

footer {
    padding: 10px 14px 12px;
}

#terminal {
    max-height: min(11em, 18vh);
    margin-top: 6px;
    overflow-y: auto;
    word-break: break-word;
    scrollbar-color: var(--dim) transparent;
    scrollbar-width: thin;
}

.t-line {
    white-space: pre-wrap;
}

.t-echo {
    margin-top: 0.4em;
    white-space: pre-wrap;
}

.t-echo:first-child {
    margin-top: 0;
}

.t-prompt {
    margin-right: 1ch;
    color: var(--hi);
}

.t-head {
    margin-top: 0.4em;
    color: var(--hi);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.t-head::before {
    content: "── ";
    color: var(--dim);
}

.t-table {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    column-gap: 2ch;
    padding-left: 2ch;
}

.t-table .tk {
    color: var(--fg);
    white-space: nowrap;
}

.t-table .tv {
    color: var(--dim);
    overflow-wrap: anywhere;
}

.t-table.strong .tv {
    color: var(--fg);
}

.t-table .tv.l-warn {
    color: var(--warn);
}

#status {
    display: flex;
    justify-content: space-between;
    gap: 2ch;
    padding: 0 1ch;
    overflow: hidden;
    background: var(--dim);
    color: var(--bg);
    text-shadow: none;
    white-space: nowrap;
}

#status-left {
    cursor: pointer;
}

#command-form {
    display: flex;
    align-items: center;
    margin: 6px 0 0;
}

#prompt {
    color: var(--hi);
    white-space: nowrap;
}

#command::placeholder {
    color: var(--dim);
    opacity: 1;
}

#command {
    flex: 1;
    min-width: 0;
    padding: 0 0 0 1ch;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--fg);
    font: inherit;
    font-size: max(16px, 1em);
    caret-color: var(--fg);
    text-shadow: inherit;
}

#boot {
    position: fixed;
    inset: 0;
    z-index: 40;
    padding: 28px;
    overflow: auto;
    background: var(--bg);
    white-space: pre-wrap;
    cursor: pointer;
    transition: opacity 0.35s;
}

#boot.gone {
    opacity: 0;
    pointer-events: none;
}

#boot .ok {
    color: var(--hi);
}

#boot .bad {
    color: var(--warn);
}

#boot .entry {
    display: flex;
    flex-wrap: wrap;
    gap: 0 1ch;
    white-space: nowrap;
}

#boot .entry .label {
    flex: none;
}

#boot .entry .leader {
    flex: 1 1 4ch;
    min-width: 4ch;
    overflow: hidden;
    color: var(--dim);
}

#boot .entry .value {
    flex: none;
    margin-left: auto;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
}

.blink {
    animation: blink 1s steps(1) infinite;
}

@keyframes blink {
    50% {
        opacity: 0;
    }
}

@media (prefers-reduced-motion: reduce) {
    .blink {
        animation: none;
    }
}

@media (max-width: 899px) {
    html,
    body {
        height: auto;
    }

    html {
        overflow-x: hidden;
    }

    html,
    body {
        overflow-x: clip;
    }

    body {
        min-height: 100%;
        overflow-y: visible;
        font-size: 13px;
    }

    header {
        flex-direction: column;
        align-items: flex-start;
        gap: 6px;
        padding: 10px 10px 0;
    }

    #logo {
        font-size: 9px;
    }

    #sys {
        max-width: 100%;
        font-size: 11px;
        text-align: left;
        white-space: normal;
    }

    #controls,
    #volume {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        column-gap: 1ch;
        white-space: normal;
    }

    #controls .btn,
    #volume > * {
        white-space: nowrap;
    }

    .btn.gap {
        margin-left: 0;
    }

    #status {
        flex-wrap: wrap;
        gap: 0 2ch;
    }

    #boot {
        padding: 18px 14px;
    }

    #terminal {
        max-height: 8.5em;
    }

    .t-table {
        grid-template-columns: minmax(0, 1fr);
    }

    .t-table .tk {
        margin-top: 0.2em;
        white-space: normal;
    }

    .t-table .tv {
        padding-left: 2ch;
    }

    main {
        display: block;
        padding: 16px 10px 0;
    }

    #left,
    #right {
        margin-bottom: 20px;
        overflow: visible;
    }

    #list {
        flex: none;
        height: 62vh;
    }

    #spectrum {
        flex: none;
        height: 6em;
    }

    #spectrum-panel {
        min-height: 0;
    }

    .row .a {
        display: none;
    }

    footer {
        padding-bottom: max(12px, env(safe-area-inset-bottom));
    }
}
"""

PAGE_SCRIPT = r"""
(() => {
    "use strict";

    const RAMP = " .'`^,:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$";
    const RAMP_LAST = RAMP.length - 1;
    const SCRAMBLE = "#%&@$*+=-:.<>/|01";
    const BLOCKS = [" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"];
    const THEMES = ["hyper", "green", "amber", "ice"];
    const ART_MODES = ["color", "blocks", "mono"];
    const REPEAT_MODES = ["off", "all", "one"];
    const REPEAT_ICONS = { off: "repeat-off", all: "repeat", one: "repeat-one" };
    const SPECTRUM_LOW_HZ = 40;
    const SPECTRUM_HIGH_HZ = 16000;
    const SPECTRUM_LABELS = [[60, "60"], [250, "250"], [1000, "1k"], [4000, "4k"], [12000, "12k"]];
    const STATUS_INTERVAL_MS = 15000;
    const SAVE_INTERVAL_MS = 5000;
    const REVEAL_MS = 650;
    const VINYL_FRAME_MS = 90;
    const SPECTRUM_ATTACK_SECONDS = 0.05;
    const SPECTRUM_RELEASE_SECONDS = 0.24;
    const SPECTRUM_PEAK_FADE_SECONDS = 0.4;
    const SPECTRUM_PEAK_PROMINENCE = 0.06;
    const SPECTRUM_PEAK_DROP = 0.025;
    const SPECTRUM_PEAK_RISE = 0.02;
    const SPECTRUM_PEAK_MINIMUM = 0.06;
    const SPECTRUM_PEAK_GAP = 1.5;
    const SPECTRUM_PEAK_STEPS = 5;
    const SPECTRUM_SWAY = 0.1;
    const SPECTRUM_SWAY_HZ = 0.22;
    const SPECTRUM_IDLE_LEVEL = 0.28;
    const PROGRESS_FRAME_MS = 250;
    const MAX_HISTORY = 500;
    const MAX_ACTIVITY_LINES = 300;
    const MAX_TERMINAL_NODES = 400;
    const MAX_CONSECUTIVE_ERRORS = 5;
    const ALBUM_LIST_LIMIT = 60;
    const VOLUME_STEP = 0.05;
    const SEEK_STEP = 10;
    const CROSSFADE_DEFAULT = 8;
    const CROSSFADE_MAX = 12;
    const CROSSFADE_STEPS = 64;
    const PREFETCH_DELAY_MS = 4000;
    const PREFETCH_MAX_BYTES = 80 * 1024 * 1024;
    const TWIN_TOLERANCE_SECONDS = 0.15;
    const TWIN_SYNC_MS = 500;
    const POSITION_SYNC_MS = 1000;
    const BACKGROUND_SWITCH_SECONDS = 0.35;
    const USER_AGENT = navigator.userAgent || "";
    const IS_IOS = /iPad|iPhone|iPod/.test(USER_AGENT) || (/Macintosh/.test(USER_AGENT) && navigator.maxTouchPoints > 1);
    const IS_SAFARI = IS_IOS || (/Safari\//.test(USER_AGENT) && !/Chrome\/|Chromium\/|CriOS|FxiOS|Edg\/|OPR\//.test(USER_AGENT));
    const ONLINE_SOURCES = ["musicbrainz"];
    const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const $ = (selector) => document.querySelector(selector);
    const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
    const plural = (count, noun) => `${count} ${noun}${count === 1 ? "" : "s"}`;
    const pad3 = (value) => String(value).padStart(3, "0");
    const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
    const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ESCAPES[character]);
    const pick = (value, allowed, fallback) => (allowed.includes(value) ? value : fallback);
    const cycle = (value, list) => list[(list.indexOf(value) + 1) % list.length];

    function formatTime(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) {
            return "--:--";
        }
        const whole = Math.floor(seconds);
        const hours = Math.floor(whole / 3600);
        const minutes = Math.floor((whole % 3600) / 60);
        const secs = String(whole % 60).padStart(2, "0");
        if (hours) {
            return `${hours}:${String(minutes).padStart(2, "0")}:${secs}`;
        }
        return `${String(minutes).padStart(2, "0")}:${secs}`;
    }

    function formatSize(bytes) {
        if (!bytes) {
            return "";
        }
        const units = ["B", "KB", "MB", "GB"];
        let value = bytes;
        let unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
            value /= 1024;
            unit += 1;
        }
        return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
    }

    function formatUptime(seconds) {
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return days ? `${days}d ${hours}h` : `${hours}h ${minutes}m`;
    }

    function parseClock(text) {
        const parts = text.split(":").map((part) => Number(part));
        if (!parts.length || parts.some((part) => !Number.isFinite(part) || part < 0)) {
            return NaN;
        }
        return parts.reduce((total, part) => total * 60 + part, 0);
    }

    const storage = {
        get(key, fallback) {
            try {
                const raw = window.localStorage.getItem(`bb.${key}`);
                return raw === null ? fallback : JSON.parse(raw);
            } catch (error) {
                return fallback;
            }
        },
        set(key, value) {
            try {
                window.localStorage.setItem(`bb.${key}`, JSON.stringify(value));
            } catch (error) {
                return;
            }
        },
    };

    const ui = {
        body: document.body,
        themeColor: $("meta[name=theme-color]"),
        boot: $("#boot"),
        logo: $("#logo"),
        clock: $("#clock"),
        sysline: $("#sysline"),
        art: $("#art"),
        artLabel: $("#art-label"),
        title: $("#np-title"),
        artist: $("#np-artist"),
        album: $("#np-album"),
        meta: $("#np-meta"),
        next: $("#np-next"),
        progress: $("#progress"),
        elapsed: $("#elapsed"),
        seekbar: $("#seekbar"),
        duration: $("#duration"),
        toggle: $("#btn-toggle"),
        shuffle: $("#btn-shuffle"),
        repeat: $("#btn-repeat"),
        mute: $("#btn-mute"),
        volume: $("#volume"),
        volbar: $("#volbar"),
        volumeSlider: $("#volume-slider"),
        volpct: $("#volpct"),
        spectrum: $("#spectrum"),
        spectrumAxis: $("#spectrum-axis"),
        spectrumLabel: $("#spectrum-label"),
        list: $("#list"),
        left: $("#left"),
        libraryCount: $("#library-count"),
        activity: $("#activity"),
        terminal: $("#terminal"),
        statusLeft: $("#status-left"),
        statusRight: $("#status-right"),
        prompt: $("#prompt"),
        form: $("#command-form"),
        command: $("#command"),
        measure: $("#measure"),
    };

    function storedNumber(key, fallback, minimum, maximum) {
        const value = Number(storage.get(key, fallback));
        return clamp(Number.isFinite(value) ? value : fallback, minimum, maximum);
    }

    const state = {
        library: [],
        view: [],
        albums: [],
        info: {},
        status: null,
        selected: 0,
        current: -1,
        filter: "",
        history: [],
        shuffleBag: [],
        commandHistory: [],
        commandCursor: 0,
        terminalDepth: 0,
        shuffle: storage.get("shuffle", true) !== false,
        repeat: pick(storage.get("repeat", "all"), REPEAT_MODES, "all"),
        artMode: pick(storage.get("art", "color"), ART_MODES, "color"),
        theme: pick(storage.get("palette", "hyper"), THEMES, "hyper"),
        spectrum: storage.get("viz", true) !== false,
        crossfade: storedNumber("fade", CROSSFADE_DEFAULT, 0, CROSSFADE_MAX),
        volume: 1,
        muted: false,
        deck: 0,
        upNext: -1,
        fading: null,
        autoplay: false,
        buffering: false,
        errors: 0,
        pendingSeek: 0,
        scrubbing: null,
        booted: false,
        bootFast: false,
        statusTimer: 0,
    };

    const metrics = {
        charWidth: 8.4,
        fontSize: 14,
        ratio: 0.6,
        fontFamily: "monospace",
        spectrumColumns: 32,
        spectrumRows: 8,
    };

    const graph = {
        context: null,
        analyser: null,
        master: null,
        bins: null,
        twin: null,
        twinSource: "",
        failed: false,
    };

    const engine = {
        native: IS_SAFARI,
    };

    function createDeck(audio) {
        return {
            audio,
            gain: null,
            level: 0,
            trackId: "",
            objectUrl: "",
            controller: null,
            cached: false,
            status: "",
            art: null,
        };
    }

    const decks = [createDeck($("#deck-a")), createDeck($("#deck-b"))];
    decks[0].level = 1;

    const volumeControllable = (() => {
        try {
            const probe = document.createElement("audio");
            probe.volume = 0.5;
            return Math.abs(probe.volume - 0.5) < 0.01;
        } catch (error) {
            return false;
        }
    })();

    const art = {
        context: ui.art.getContext("2d"),
        image: null,
        source: "",
        status: "no art",
        layout: null,
        sprite: null,
        pixels: { key: "", data: null },
        loadToken: 0,
        revealToken: 0,
        revealing: false,
    };

    const spectrum = {
        bands: [],
        targets: new Float32Array(0),
        blurred: new Float32Array(0),
        values: new Float32Array(0),
        peakLevel: new Float32Array(0),
        peakLife: new Float32Array(0),
        climb: new Float32Array(0),
        trough: new Float32Array(0),
        base: new Float32Array(0),
        rising: new Uint8Array(0),
        peakLines: [],
        lines: [],
        columns: 0,
        lastTime: 0,
        message: "",
        label: "",
    };

    const timers = {
        progress: 0,
        vinyl: 0,
        save: 0,
        resize: 0,
        prefetch: 0,
        twin: 0,
        position: 0,
    };

    const typewriters = new WeakMap();

    function columnsOf(element) {
        return Math.max(8, Math.floor((element.clientWidth - 1) / metrics.charWidth));
    }

    function measure() {
        const style = window.getComputedStyle(ui.body);
        const width = ui.measure.getBoundingClientRect().width / 100;
        if (width > 0) {
            metrics.charWidth = width;
        }
        metrics.fontSize = parseFloat(style.fontSize) || 14;
        metrics.fontFamily = style.fontFamily || "monospace";
        metrics.ratio = metrics.charWidth / metrics.fontSize;
        metrics.spectrumColumns = columnsOf(ui.spectrum);
        metrics.spectrumRows = clamp(Math.floor(ui.spectrum.clientHeight / metrics.fontSize), 3, 18);
    }

    function setText(element, text) {
        if (element.textContent !== text) {
            element.textContent = text;
        }
    }

    function log(message, kind) {
        if (state.terminalDepth > 0) {
            termLine(message, kind);
            return;
        }
        const line = document.createElement("div");
        if (kind) {
            line.className = `l-${kind}`;
        }
        line.textContent = message;
        ui.activity.appendChild(line);
        while (ui.activity.childNodes.length > MAX_ACTIVITY_LINES) {
            ui.activity.removeChild(ui.activity.firstChild);
        }
        ui.activity.scrollTop = ui.activity.scrollHeight;
    }

    function terminalAppend(node) {
        ui.terminal.appendChild(node);
        while (ui.terminal.childNodes.length > MAX_TERMINAL_NODES) {
            ui.terminal.removeChild(ui.terminal.firstChild);
        }
        ui.terminal.hidden = false;
        ui.terminal.scrollTop = ui.terminal.scrollHeight;
        ui.form.scrollIntoView({ block: "nearest" });
    }

    function termElement(tag, className, text) {
        const element = document.createElement(tag);
        element.className = className;
        if (text !== undefined) {
            element.textContent = text;
        }
        return element;
    }

    function termLine(text, kind) {
        terminalAppend(termElement("div", kind ? `t-line l-${kind}` : "t-line", text));
    }

    function termHeading(text) {
        terminalAppend(termElement("div", "t-head", text));
    }

    function termTable(rows, strong) {
        const table = termElement("div", strong ? "t-table strong" : "t-table");
        rows.forEach(([key, value, kind]) => {
            table.appendChild(termElement("span", "tk", key));
            table.appendChild(termElement("span", kind ? `tv l-${kind}` : "tv", value));
        });
        terminalAppend(table);
    }

    function termEcho(text) {
        const line = termElement("div", "t-echo");
        line.appendChild(termElement("span", "t-prompt", ui.prompt.textContent));
        line.appendChild(document.createTextNode(text));
        terminalAppend(line);
    }

    function clearTerminal() {
        ui.terminal.replaceChildren();
        ui.terminal.hidden = true;
    }

    function inTerminal(action) {
        state.terminalDepth += 1;
        try {
            return action();
        } finally {
            state.terminalDepth -= 1;
        }
    }

    function themeColors() {
        const style = window.getComputedStyle(ui.body);
        return {
            fg: style.getPropertyValue("--fg").trim(),
            hi: style.getPropertyValue("--hi").trim(),
            faint: style.getPropertyValue("--faint").trim(),
            bg: style.getPropertyValue("--bg").trim(),
        };
    }

    function applyTheme() {
        ui.body.classList.remove(...THEMES);
        ui.body.classList.add(state.theme);
        ui.themeColor.setAttribute("content", themeColors().bg);
    }

    async function request(path, options) {
        const response = await fetch(path, Object.assign({ cache: "no-store", credentials: "same-origin" }, options));
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    }

    function collectAlbums(tracks) {
        const albums = new Map();
        tracks.forEach((track) => {
            const key = `${track.album}\u0000${track.albumartist}`;
            if (!albums.has(key)) {
                albums.set(key, { album: track.album, artist: track.albumartist, count: 0 });
            }
            albums.get(key).count += 1;
        });
        return Array.from(albums.values());
    }

    async function loadLibrary() {
        const data = await request("/api/library");
        const tracks = Array.isArray(data.tracks) ? data.tracks : [];
        const currentTrack = state.library[state.current];
        tracks.forEach((track, index) => {
            track.index = index;
            track.number = index + 1;
            track.search = `${track.title} ${track.artist} ${track.album} ${track.albumartist}`.toLowerCase();
        });
        state.info = data;
        state.library = tracks;
        state.history = [];
        state.current = currentTrack ? tracks.findIndex((track) => track.id === currentTrack.id) : -1;
        state.upNext = -1;
        state.albums = collectAlbums(tracks);
        ui.prompt.textContent = `guest@${data.host || "badbanana"}:~/${data.root || "music"}$`;
        applyFilter(state.filter, true);
        return data;
    }

    function applyFilter(query, quiet) {
        state.filter = String(query || "").trim();
        const words = state.filter.toLowerCase().split(/\s+/).filter(Boolean);
        state.view = state.library
            .filter((track) => words.every((word) => track.search.includes(word)))
            .map((track) => track.index);
        state.shuffleBag = [];
        state.selected = Math.max(0, state.view.indexOf(state.current));
        renderList();
        planNext(false);
        renderStatus();
        if (quiet) {
            return;
        }
        if (state.filter) {
            const suffix = state.view.length === 1 ? "" : "es";
            log(`find "${state.filter}": ${state.view.length} match${suffix}  (esc or 'clear' to reset)`, "dim");
        } else {
            log(`filter cleared: ${plural(state.view.length, "track")}`, "dim");
        }
    }

    function renderList() {
        const parts = [];
        let lastGroup = null;
        state.view.forEach((index, position) => {
            const track = state.library[index];
            const group = `${track.album}\u0000${track.albumartist}`;
            if (group !== lastGroup) {
                lastGroup = group;
                parts.push(
                    `<div class="grp" aria-hidden="true">╾─ <b>${escapeHtml(track.album)}</b> · ` +
                    `${escapeHtml(track.albumartist)} ${"─".repeat(200)}</div>`
                );
            }
            const classes = ["row"];
            if (index === state.current) {
                classes.push("cur");
            }
            if (position === state.selected) {
                classes.push("sel");
            }
            parts.push(
                `<div class="${classes.join(" ")}" role="option" ` +
                `aria-selected="${position === state.selected}" data-pos="${position}">` +
                `<span class="n">${pad3(track.number)}</span>` +
                `<span class="m"></span>` +
                `<span class="t">${escapeHtml(track.title)}</span>` +
                `<span class="a">${escapeHtml(track.artist)}</span>` +
                `<span class="d">${track.duration ? formatTime(track.duration) : "--:--"}</span>` +
                `</div>`
            );
        });
        if (!state.view.length) {
            const message = state.filter
                ? `  no tracks match "${escapeHtml(state.filter)}"\n  press esc to clear`
                : "  library is empty.\n  copy music into the folder on your pi, then type: rescan";
            parts.push(`<div class="empty">${message}</div>`);
        }
        ui.list.innerHTML = parts.join("");
        ui.libraryCount.textContent = state.filter
            ? `${state.view.length}/${state.library.length} · find: ${state.filter}`
            : `${plural(state.library.length, "track")} · ${plural(state.albums.length, "album")}`;
        scrollToSelected();
    }

    function rowAt(position) {
        return position >= 0 ? ui.list.querySelector(`.row[data-pos="${position}"]`) : null;
    }

    function markRows() {
        ui.list.querySelectorAll(".row.sel, .row.cur, .row.nxt").forEach((row) => {
            row.classList.remove("sel", "cur", "nxt");
            row.setAttribute("aria-selected", "false");
        });
        const selected = rowAt(state.selected);
        if (selected) {
            selected.classList.add("sel");
            selected.setAttribute("aria-selected", "true");
        }
        const current = rowAt(state.view.indexOf(state.current));
        if (current) {
            current.classList.add("cur");
        }
        if (state.upNext >= 0 && state.upNext !== state.current) {
            const upcoming = rowAt(state.view.indexOf(state.upNext));
            if (upcoming) {
                upcoming.classList.add("nxt");
            }
        }
    }

    function scrollToSelected() {
        const row = rowAt(state.selected);
        if (!row) {
            return;
        }
        const list = ui.list;
        if (row.offsetTop - row.offsetHeight * 1.5 < list.scrollTop) {
            list.scrollTop = Math.max(0, row.offsetTop - row.offsetHeight * 2);
        } else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) {
            list.scrollTop = row.offsetTop + row.offsetHeight * 2 - list.clientHeight;
        }
    }

    function moveSelection(delta) {
        if (!state.view.length) {
            return;
        }
        state.selected = clamp(state.selected + delta, 0, state.view.length - 1);
        markRows();
        scrollToSelected();
    }

    function activeDeck() {
        return decks[state.deck];
    }

    function idleDeck() {
        return decks[1 - state.deck];
    }

    function media() {
        return activeDeck().audio;
    }

    function trackById(id) {
        return id ? state.library.find((track) => track.id === id) || null : null;
    }

    function streamUrl(track) {
        return `/stream/${encodeURIComponent(track.id)}`;
    }

    function ensureAudioGraph() {
        if (graph.context) {
            resumeAudio();
            syncTwin();
            return;
        }
        if (!state.spectrum || graph.failed) {
            return;
        }
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) {
            graph.failed = true;
            return;
        }
        let context;
        try {
            context = new AudioContextClass();
        } catch (error) {
            graph.failed = true;
            log(`spectrum unavailable: ${error.message}`, "dim");
            return;
        }
        const analyser = context.createAnalyser();
        analyser.fftSize = 2048;
        analyser.smoothingTimeConstant = 0.74;
        graph.context = context;
        graph.analyser = analyser;
        graph.bins = new Uint8Array(analyser.frequencyBinCount);
        spectrum.columns = 0;
        if (engine.native) {
            connectTwin(context, analyser);
        } else {
            connectDecks(context, analyser);
        }
        applyVolume();
        syncTwin();
    }

    function connectDecks(context, analyser) {
        const mix = context.createGain();
        const master = context.createGain();
        mix.connect(analyser);
        analyser.connect(master);
        master.connect(context.destination);
        graph.master = master;
        decks.forEach((deck) => {
            try {
                const source = context.createMediaElementSource(deck.audio);
                const gain = context.createGain();
                gain.gain.value = deck.level;
                source.connect(gain);
                gain.connect(mix);
                deck.gain = gain;
            } catch (error) {
                deck.gain = null;
            }
        });
    }

    function connectTwin(context, analyser) {
        const twin = document.createElement("audio");
        twin.preload = "auto";
        const silence = context.createGain();
        silence.gain.value = 0;
        try {
            context.createMediaElementSource(twin).connect(analyser);
        } catch (error) {
            graph.failed = true;
            return;
        }
        analyser.connect(silence);
        silence.connect(context.destination);
        graph.twin = twin;
    }

    function syncTwin() {
        const twin = graph.twin;
        if (!twin) {
            return;
        }
        const main = media();
        const source = main.currentSrc || "";
        if (document.hidden || main.paused || !source || state.current < 0) {
            if (!twin.paused) {
                twin.pause();
            }
            return;
        }
        if (graph.twinSource !== source) {
            graph.twinSource = source;
            twin.src = source;
        }
        if (twin.readyState >= 1 && Math.abs(twin.currentTime - main.currentTime) > TWIN_TOLERANCE_SECONDS) {
            twin.currentTime = main.currentTime;
        }
        if (twin.paused) {
            twin.play().catch(() => undefined);
        }
    }

    function deviceVolumeOnly() {
        return engine.native && !volumeControllable;
    }

    function setParam(param, level, glide) {
        const now = graph.context.currentTime;
        const from = param.value;
        param.cancelScheduledValues(0);
        if (glide) {
            param.setValueAtTime(from, now);
            param.setTargetAtTime(level, now, glide);
        } else {
            param.setValueAtTime(level, now);
        }
    }

    function resumeAudio() {
        if (graph.context && graph.context.state !== "running" && !document.hidden) {
            graph.context.resume().catch(() => undefined);
        }
    }

    function applyVolume() {
        const level = state.muted ? 0 : state.volume;
        if (graph.master) {
            setParam(graph.master.gain, level, 0.012);
        }
        decks.forEach((deck) => {
            const routed = Boolean(graph.master && deck.gain);
            const elementLevel = routed ? 1 : state.volume * deck.level;
            deck.audio.volume = clamp(elementLevel, 0, 1);
            deck.audio.muted = !routed && state.muted;
        });
    }

    function setDeckLevel(deck, level) {
        deck.level = level;
        if (deck.gain) {
            setParam(deck.gain.gain, level, 0);
        }
        applyVolume();
    }

    function startPlayback(audio) {
        state.autoplay = true;
        const attempt = (audio || media()).play();
        if (attempt) {
            attempt.catch((error) => {
                if (error.name === "NotAllowedError") {
                    log("the browser blocked playback — press ►", "warn");
                } else if (error.name !== "AbortError") {
                    log(`playback failed: ${error.message}`, "err");
                }
            });
        }
        syncTwin();
    }

    function purgeArt(track) {
        if (!track || !track.art) {
            return;
        }
        fetch(`/api/art/${encodeURIComponent(track.id)}`, {
            method: "DELETE",
            headers: { "X-BadBanana": "1" },
            credentials: "same-origin",
            cache: "no-store",
            keepalive: true,
        }).catch(() => undefined);
    }

    function resetDeck(deck) {
        if (deck.controller) {
            deck.controller.abort();
            deck.controller = null;
        }
        deck.audio.pause();
        if (deck.audio.getAttribute("src")) {
            deck.audio.removeAttribute("src");
            deck.audio.load();
        }
        if (deck.objectUrl) {
            URL.revokeObjectURL(deck.objectUrl);
            deck.objectUrl = "";
        }
        deck.trackId = "";
        deck.art = null;
        deck.cached = false;
        deck.status = "";
    }

    function deckLoaded(deck, track) {
        return Boolean(track) && deck.trackId === track.id && Boolean(deck.audio.getAttribute("src"));
    }

    function loadIntoActive(track) {
        const active = activeDeck();
        const standby = idleDeck();
        let source = streamUrl(track);
        let objectUrl = "";
        let prefetchedArt = null;
        if (deckLoaded(standby, track) && standby.objectUrl) {
            objectUrl = standby.objectUrl;
            prefetchedArt = standby.art;
            standby.objectUrl = "";
            source = objectUrl;
        }
        if (standby.trackId === track.id) {
            resetDeck(standby);
        }
        const previousUrl = active.objectUrl;
        active.trackId = track.id;
        active.objectUrl = objectUrl;
        active.cached = Boolean(objectUrl);
        active.art = null;
        active.status = "";
        active.audio.src = source;
        if (previousUrl && previousUrl !== objectUrl) {
            URL.revokeObjectURL(previousUrl);
        }
        return prefetchedArt;
    }

    function pushHistory(index) {
        if (index < 0) {
            return;
        }
        state.history.push(index);
        if (state.history.length > MAX_HISTORY) {
            state.history.shift();
        }
    }

    function selectCurrent() {
        const position = state.view.indexOf(state.current);
        if (position >= 0) {
            state.selected = position;
        }
    }

    function randomIndex(limit) {
        return Math.floor(Math.random() * limit);
    }

    function shuffled(items) {
        const result = items.slice();
        for (let position = result.length - 1; position > 0; position -= 1) {
            const other = randomIndex(position + 1);
            [result[position], result[other]] = [result[other], result[position]];
        }
        return result;
    }

    function albumKey(index) {
        const track = state.library[index];
        return track ? `${track.album}\u0000${track.albumartist}` : "";
    }

    function spreadAlbums(indexes, previousIndex) {
        const groups = new Map();
        shuffled(indexes).forEach((index) => {
            const key = albumKey(index);
            if (!groups.has(key)) {
                groups.set(key, []);
            }
            groups.get(key).push(index);
        });
        const queues = shuffled([...groups.values()]);
        const order = [];
        let last = previousIndex >= 0 ? groups.get(albumKey(previousIndex)) || null : null;
        let remaining = indexes.length;
        while (remaining > 0) {
            const open = queues.filter((queue) => queue.length && queue !== last);
            let pick = null;
            if (open.length) {
                const largest = open.reduce((best, queue) => (queue.length > best.length ? queue : best));
                if (largest.length * 2 > remaining + 1) {
                    pick = largest;
                } else {
                    let ticket = randomIndex(open.reduce((total, queue) => total + queue.length, 0));
                    pick = open.find((queue) => {
                        ticket -= queue.length;
                        return ticket < 0;
                    });
                }
            } else {
                pick = last;
            }
            order.push(pick.shift());
            last = pick;
            remaining -= 1;
        }
        return order;
    }

    function nextShuffled() {
        const pool = new Set(state.view);
        state.shuffleBag = state.shuffleBag.filter((index) => pool.has(index) && index !== state.current);
        if (!state.shuffleBag.length) {
            state.shuffleBag = spreadAlbums(state.view.filter((index) => index !== state.current), state.current);
        }
        return state.shuffleBag.length ? state.shuffleBag[0] : -1;
    }

    function chooseNext(wrap, ignoreRepeatOne) {
        if (!state.view.length) {
            return -1;
        }
        if (state.current < 0) {
            if (state.shuffle) {
                return nextShuffled();
            }
            return state.view[state.selected] !== undefined ? state.view[state.selected] : state.view[0];
        }
        if (state.repeat === "one" && !ignoreRepeatOne) {
            return state.current;
        }
        if (state.shuffle) {
            const next = nextShuffled();
            if (next >= 0) {
                return next;
            }
            return wrap ? state.current : -1;
        }
        const position = state.view.indexOf(state.current);
        if (position < 0) {
            return state.view[0];
        }
        if (position + 1 < state.view.length) {
            return state.view[position + 1];
        }
        return wrap ? state.view[0] : -1;
    }

    function planNext(force) {
        let next = -1;
        if (state.current >= 0) {
            const keep = !force
                && state.shuffle
                && state.upNext >= 0
                && state.upNext !== state.current
                && state.view.includes(state.upNext);
            next = keep ? state.upNext : chooseNext(state.repeat === "all", false);
        }
        state.upNext = next;
        const wanted = next >= 0 && next !== state.current ? state.library[next].id : "";
        if (!state.fading && idleDeck().trackId !== wanted) {
            discardPrefetch();
            schedulePrefetch();
        }
        renderUpNext();
        markRows();
    }

    function discardPrefetch() {
        window.clearTimeout(timers.prefetch);
        if (state.fading) {
            return;
        }
        const deck = idleDeck();
        if (!deck.trackId) {
            return;
        }
        const track = trackById(deck.trackId);
        const current = state.library[state.current];
        if (track && (!current || current.id !== track.id)) {
            purgeArt(track);
        }
        resetDeck(deck);
    }

    function schedulePrefetch() {
        window.clearTimeout(timers.prefetch);
        const track = state.library[state.upNext];
        if (state.fading || !track || state.upNext === state.current || idleDeck().trackId === track.id) {
            return;
        }
        timers.prefetch = window.setTimeout(() => prefetchTrack(track), PREFETCH_DELAY_MS);
    }

    async function prefetchTrack(track) {
        if (state.fading || state.library[state.upNext] !== track) {
            return;
        }
        const deck = idleDeck();
        resetDeck(deck);
        const controller = new AbortController();
        deck.controller = controller;
        deck.trackId = track.id;
        deck.status = "loading";
        renderUpNext();
        let source = streamUrl(track);
        if (track.size > 0 && track.size <= PREFETCH_MAX_BYTES) {
            try {
                const response = await fetch(source, {
                    cache: "no-store",
                    credentials: "same-origin",
                    signal: controller.signal,
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const blob = await response.blob();
                if (controller.signal.aborted) {
                    return;
                }
                deck.objectUrl = URL.createObjectURL(blob);
                deck.cached = true;
                source = deck.objectUrl;
            } catch (error) {
                if (controller.signal.aborted) {
                    return;
                }
            }
        }
        deck.audio.preload = "auto";
        deck.audio.src = source;
        deck.audio.load();
        const prefetchedArt = await fetchArt(track, controller.signal);
        if (controller.signal.aborted) {
            return;
        }
        deck.art = prefetchedArt;
        deck.controller = null;
        deck.status = deck.cached ? "cached" : "buffering";
        renderUpNext();
        log(`up next: ${track.title} — ${deck.cached ? `cached in memory (${formatSize(track.size)})` : "buffering"}`, "dim");
    }

    function fadeCurve(rising) {
        const curve = new Float32Array(CROSSFADE_STEPS);
        for (let step = 0; step < CROSSFADE_STEPS; step += 1) {
            const angle = (step / (CROSSFADE_STEPS - 1)) * (Math.PI / 2);
            curve[step] = rising ? Math.sin(angle) : Math.cos(angle);
        }
        return curve;
    }

    function crossfadeAvailable() {
        if (engine.native) {
            return volumeControllable && !document.hidden;
        }
        return (Boolean(graph.context) && decks.every((deck) => deck.gain)) || volumeControllable;
    }

    function crossfadeSeconds(outgoingDuration, incomingDuration) {
        if (state.crossfade <= 0 || !crossfadeAvailable()) {
            return 0;
        }
        const incomingLimit = incomingDuration > 0 ? incomingDuration / 3 : Infinity;
        return Math.min(state.crossfade, outgoingDuration / 3, incomingLimit);
    }

    function crossfadeDecks(outgoing, incoming, seconds) {
        if (graph.context && outgoing.gain && incoming.gain) {
            try {
                const now = graph.context.currentTime;
                [[outgoing, false], [incoming, true]].forEach(([deck, rising]) => {
                    deck.gain.gain.cancelScheduledValues(0);
                    deck.gain.gain.setValueCurveAtTime(fadeCurve(rising), now, seconds);
                    deck.level = rising ? 1 : 0;
                });
                return;
            } catch (error) {
                setDeckLevel(outgoing, 1);
                setDeckLevel(incoming, 0);
            }
        }
        const started = performance.now();
        state.fading.interval = window.setInterval(() => {
            const progress = clamp((performance.now() - started) / (seconds * 1000), 0, 1);
            setDeckLevel(outgoing, Math.cos(progress * (Math.PI / 2)));
            setDeckLevel(incoming, Math.sin(progress * (Math.PI / 2)));
            if (progress >= 1 && state.fading) {
                window.clearInterval(state.fading.interval);
            }
        }, 50);
    }

    function checkCrossfade() {
        const audio = media();
        if (state.fading || audio.paused || state.upNext < 0 || state.upNext === state.current) {
            return;
        }
        const duration = knownDuration();
        const track = state.library[state.upNext];
        const incoming = idleDeck();
        if (engine.native && document.hidden && duration && duration - audio.currentTime <= BACKGROUND_SWITCH_SECONDS) {
            startTransition(0);
            return;
        }
        if (!duration || !deckLoaded(incoming, track)) {
            return;
        }
        if (!incoming.cached && incoming.audio.readyState < 3) {
            return;
        }
        const incomingDuration = Number.isFinite(incoming.audio.duration) ? incoming.audio.duration : track.duration;
        const seconds = crossfadeSeconds(duration, incomingDuration);
        const remaining = duration - audio.currentTime;
        if (seconds > 0 && remaining <= seconds) {
            startTransition(Math.max(0.5, Math.min(seconds, remaining)));
        }
    }

    function startTransition(seconds) {
        const index = state.upNext;
        const track = state.library[index];
        if (!track) {
            return;
        }
        window.clearTimeout(timers.prefetch);
        finishTransition();
        if (engine.native && seconds <= 0) {
            switchInPlace(index);
            return;
        }
        const outgoing = activeDeck();
        const incoming = idleDeck();
        const outgoingTrack = state.library[state.current];
        if (!deckLoaded(incoming, track)) {
            resetDeck(incoming);
            incoming.trackId = track.id;
            incoming.audio.src = streamUrl(track);
        }
        if (incoming.controller) {
            incoming.controller.abort();
            incoming.controller = null;
        }
        state.deck = 1 - state.deck;
        pushHistory(state.current);
        state.current = index;
        state.pendingSeek = 0;
        state.buffering = false;
        selectCurrent();
        setDeckLevel(incoming, seconds > 0 ? 0 : 1);
        ensureAudioGraph();
        startPlayback(incoming.audio);
        if (seconds > 0) {
            state.fading = { outgoing, trackId: outgoingTrack ? outgoingTrack.id : "", interval: 0, timer: 0 };
            crossfadeDecks(outgoing, incoming, seconds);
            state.fading.timer = window.setTimeout(finishTransition, seconds * 1000 + 150);
            log(`► crossfade ${Math.round(seconds)}s → #${pad3(track.number)} ${track.title} — ${track.artist}`, "hi");
        } else {
            setDeckLevel(outgoing, 0);
            resetDeck(outgoing);
            if (outgoingTrack && outgoingTrack.id !== track.id) {
                purgeArt(outgoingTrack);
            }
            log(`► #${pad3(track.number)} ${track.title} — ${track.artist}`, "hi");
        }
        renderNowPlaying(track);
        loadArt(track, incoming.art);
        scrollToSelected();
        updateMediaMetadata(track);
        renderControls();
        renderStatus();
        saveState();
        planNext(true);
    }

    function switchInPlace(index) {
        const track = state.library[index];
        const outgoingTrack = state.library[state.current];
        pushHistory(state.current);
        state.current = index;
        state.pendingSeek = 0;
        state.buffering = false;
        selectCurrent();
        const prefetchedArt = loadIntoActive(track);
        setDeckLevel(activeDeck(), 1);
        startPlayback();
        if (outgoingTrack && outgoingTrack.id !== track.id) {
            purgeArt(outgoingTrack);
        }
        log(`► #${pad3(track.number)} ${track.title} — ${track.artist}`, "hi");
        renderNowPlaying(track);
        loadArt(track, prefetchedArt);
        scrollToSelected();
        updateMediaMetadata(track);
        renderControls();
        renderStatus();
        saveState();
        planNext(true);
    }

    function finishTransition() {
        const fading = state.fading;
        if (!fading) {
            return;
        }
        state.fading = null;
        window.clearTimeout(fading.timer);
        window.clearInterval(fading.interval);
        setDeckLevel(fading.outgoing, 0);
        setDeckLevel(activeDeck(), 1);
        resetDeck(fading.outgoing);
        const current = state.library[state.current];
        const previous = trackById(fading.trackId);
        if (previous && (!current || current.id !== previous.id)) {
            purgeArt(previous);
        }
        schedulePrefetch();
        renderUpNext();
        renderControls();
        renderStatus();
    }

    function releaseFinishedTrack() {
        const deck = activeDeck();
        const track = state.library[state.current];
        discardPrefetch();
        if (!deck.objectUrl || !track) {
            return;
        }
        const objectUrl = deck.objectUrl;
        deck.objectUrl = "";
        deck.cached = false;
        deck.audio.preload = "metadata";
        deck.audio.src = streamUrl(track);
        URL.revokeObjectURL(objectUrl);
    }

    function endOfList() {
        releaseFinishedTrack();
        purgeArt(state.library[state.current]);
        art.loadToken += 1;
        art.image = null;
        art.source = "";
        art.status = "purged";
        drawArt(true);
        log("— end of list — album art purged", "dim");
    }

    function handleEnded(event) {
        if (event.target !== media()) {
            if (state.fading && event.target === state.fading.outgoing.audio) {
                finishTransition();
            }
            return;
        }
        if (state.current >= 0 && (state.repeat === "one" || state.upNext === state.current)) {
            media().currentTime = 0;
            startPlayback();
            return;
        }
        if (state.upNext >= 0) {
            startTransition(0);
            return;
        }
        endOfList();
    }

    function playTrack(index, options) {
        const settings = options || {};
        const track = state.library[index];
        if (!track) {
            return;
        }
        finishTransition();
        const previous = state.library[state.current];
        if (previous && previous.id !== track.id) {
            purgeArt(previous);
        }
        if (state.current !== index && !settings.fromHistory) {
            pushHistory(state.current);
        }
        state.current = index;
        state.pendingSeek = settings.at || 0;
        state.buffering = false;
        selectCurrent();
        const outgoing = activeDeck();
        const standby = idleDeck();
        let target = outgoing;
        let prefetchedArt = null;
        if (engine.native) {
            prefetchedArt = loadIntoActive(track);
        } else if (deckLoaded(standby, track)) {
            if (standby.controller) {
                standby.controller.abort();
                standby.controller = null;
            }
            state.deck = 1 - state.deck;
            target = standby;
            prefetchedArt = standby.art;
            resetDeck(outgoing);
        } else {
            resetDeck(outgoing);
            outgoing.trackId = track.id;
            outgoing.audio.src = streamUrl(track);
        }
        setDeckLevel(target, 1);
        setDeckLevel(idleDeck(), 0);
        if (state.pendingSeek && target.audio.readyState >= 1) {
            seekTo(state.pendingSeek);
            state.pendingSeek = 0;
        }
        if (settings.paused) {
            state.autoplay = false;
            const resumeAt = settings.at ? ` @ ${formatTime(settings.at)}` : "";
            log(`loaded #${pad3(track.number)} ${track.title} — ${track.artist}${resumeAt}  (space to play)`, "dim");
        } else {
            ensureAudioGraph();
            startPlayback();
            log(`► #${pad3(track.number)} ${track.title} — ${track.artist}`, "hi");
        }
        renderNowPlaying(track);
        loadArt(track, prefetchedArt);
        scrollToSelected();
        updateMediaMetadata(track);
        renderControls();
        renderStatus();
        saveState();
        planNext(true);
    }

    function togglePlayback() {
        ensureAudioGraph();
        if (state.current < 0) {
            const index = chooseNext(true, true);
            if (index < 0) {
                log("nothing to play", "warn");
                return;
            }
            playTrack(index);
            return;
        }
        if (media().paused) {
            startPlayback();
        } else {
            pausePlayback();
        }
    }

    function pausePlayback() {
        finishTransition();
        media().pause();
    }

    function resumePlayback() {
        if (state.current < 0) {
            togglePlayback();
            return;
        }
        ensureAudioGraph();
        if (media().paused) {
            startPlayback();
        }
    }

    function stopPlayback() {
        pausePlayback();
        if (state.current >= 0) {
            media().currentTime = 0;
        }
        log("stopped", "dim");
    }

    function playNext(automatic, ignoreRepeatOne) {
        if (!state.view.length) {
            return;
        }
        if (automatic && state.repeat === "one" && !ignoreRepeatOne && state.current >= 0) {
            media().currentTime = 0;
            startPlayback();
            return;
        }
        let index = state.upNext;
        if (index < 0 || index === state.current) {
            index = chooseNext(!automatic || state.repeat === "all", true);
        }
        if (index < 0 || (index === state.current && automatic)) {
            if (automatic) {
                endOfList();
            }
            return;
        }
        playTrack(index);
    }

    function playPrevious() {
        if (state.current >= 0 && media().currentTime > 3) {
            media().currentTime = 0;
            return;
        }
        if (state.history.length) {
            playTrack(state.history.pop(), { fromHistory: true });
            return;
        }
        if (!state.view.length) {
            return;
        }
        const position = state.view.indexOf(state.current);
        const index = position > 0 ? state.view[position - 1] : state.view[state.view.length - 1];
        playTrack(index, { fromHistory: true });
    }

    function knownDuration() {
        const duration = media().duration;
        return Number.isFinite(duration) && duration > 0 ? duration : 0;
    }

    function seekTo(seconds) {
        const duration = knownDuration();
        if (!duration || state.current < 0) {
            return;
        }
        media().currentTime = clamp(seconds, 0, Math.max(0, duration - 0.25));
    }

    function seekBy(seconds) {
        seekTo(media().currentTime + seconds);
    }

    function seekFraction(fraction) {
        seekTo(fraction * knownDuration());
    }

    function setVolume(level) {
        resumeAudio();
        state.volume = clamp(Math.round(level * 100) / 100, 0, 1);
        state.muted = false;
        storage.set("volume", state.volume);
        applyVolume();
        renderVolume();
        renderStatus();
    }

    function toggleMute() {
        resumeAudio();
        state.muted = !state.muted;
        applyVolume();
        renderVolume();
        renderStatus();
    }

    function setCrossfade(seconds) {
        state.crossfade = clamp(Math.round(seconds), 0, CROSSFADE_MAX);
        storage.set("fade", state.crossfade);
        renderStatus();
        log(state.crossfade ? `crossfade ${state.crossfade}s` : "crossfade off (tracks still start instantly)", "dim");
    }

    function renderUpNext() {
        let text = "—";
        if (state.current >= 0) {
            const track = state.library[state.upNext];
            if (state.repeat === "one") {
                text = "repeat one";
            } else if (track && state.upNext === state.current) {
                text = "repeat";
            } else if (track) {
                const deck = idleDeck();
                const status = !state.fading && deck.trackId === track.id ? deck.status || "loading" : "queued";
                text = `${track.title} — ${track.artist}  [${status}]`;
            } else {
                text = "end of list";
            }
        }
        setText(ui.next, text);
    }

    function setShuffle(enabled) {
        state.shuffle = enabled;
        storage.set("shuffle", enabled);
        planNext(true);
        renderControls();
        renderStatus();
        log(`shuffle ${enabled ? "on" : "off"}`, "dim");
    }

    function setRepeat(mode) {
        state.repeat = mode;
        storage.set("repeat", mode);
        planNext(true);
        renderControls();
        renderStatus();
        log(`repeat ${mode}`, "dim");
    }

    function setArtMode(mode) {
        state.artMode = mode;
        storage.set("art", mode);
        drawArt(true);
        log(`art renderer: ${mode}`, "dim");
    }

    function setTheme(theme) {
        state.theme = theme;
        storage.set("palette", theme);
        applyTheme();
        drawArt(false);
        log(`phosphor: ${theme}`, "dim");
    }

    function setSpectrum(enabled) {
        state.spectrum = enabled;
        storage.set("viz", enabled);
        if (enabled) {
            graph.failed = false;
            ensureAudioGraph();
            log("spectrum on", "dim");
        } else {
            log(graph.context ? "spectrum off — reload the page to fully detach it" : "spectrum off", "dim");
        }
    }

    function saveState() {
        const track = state.library[state.current];
        if (track) {
            storage.set("last", { id: track.id, t: media().currentTime || 0 });
        }
    }

    function updateMediaMetadata(track) {
        if (!("mediaSession" in navigator) || typeof window.MediaMetadata !== "function") {
            return;
        }
        try {
            navigator.mediaSession.metadata = new window.MediaMetadata({
                title: track.title,
                artist: track.artist,
                album: track.album,
                artwork: track.art
                    ? ["256x256", "512x512"].map((sizes) => ({ src: `/art/${encodeURIComponent(track.id)}`, sizes }))
                    : [],
            });
        } catch (error) {
            return;
        }
        updatePositionState(true);
    }

    function updatePositionState(force) {
        if (!("mediaSession" in navigator)) {
            return;
        }
        const now = performance.now();
        if (!force && now - timers.position < POSITION_SYNC_MS) {
            return;
        }
        timers.position = now;
        const audio = media();
        try {
            navigator.mediaSession.playbackState = state.current < 0 ? "none" : audio.paused ? "paused" : "playing";
        } catch (error) {
            return;
        }
        const duration = knownDuration();
        if (!duration || typeof navigator.mediaSession.setPositionState !== "function") {
            return;
        }
        try {
            navigator.mediaSession.setPositionState({
                duration,
                playbackRate: audio.playbackRate || 1,
                position: clamp(audio.currentTime || 0, 0, duration),
            });
        } catch (error) {
            return;
        }
    }

    function bindMediaSession() {
        if (!("mediaSession" in navigator)) {
            return;
        }
        const handlers = {
            play: () => resumePlayback(),
            pause: () => pausePlayback(),
            stop: () => stopPlayback(),
            previoustrack: () => playPrevious(),
            nexttrack: () => playNext(false),
            seekbackward: () => seekBy(-SEEK_STEP),
            seekforward: () => seekBy(SEEK_STEP),
            seekto: (details) => {
                if (details && Number.isFinite(details.seekTime)) {
                    seekTo(details.seekTime);
                }
            },
        };
        Object.keys(handlers).forEach((action) => {
            try {
                navigator.mediaSession.setActionHandler(action, handlers[action]);
            } catch (error) {
                return;
            }
        });
    }

    function typeInto(element, text) {
        window.clearInterval(typewriters.get(element));
        if (reduceMotion) {
            element.textContent = text;
            return;
        }
        let shown = 0;
        element.textContent = "";
        const timer = window.setInterval(() => {
            shown += 2;
            element.textContent = text.slice(0, shown) + (shown < text.length ? "█" : "");
            if (shown >= text.length) {
                window.clearInterval(timer);
            }
        }, 16);
        typewriters.set(element, timer);
    }

    function renderNowPlaying(track) {
        typeInto(ui.title, track ? track.title : "— nothing playing —");
        ui.artist.textContent = track ? track.artist : "";
        ui.album.textContent = track ? track.album + (track.track ? `  · track ${track.track}` : "") : "";
        ui.meta.textContent = track
            ? `#${pad3(track.number)}  ${String(track.ext).toUpperCase()}  ${formatSize(track.size)}`
            : "";
        document.title = track ? `${track.title} — ${track.artist} · BAD BANANA` : "BAD BANANA";
    }

    function setIcon(button, name) {
        const use = button.querySelector("use");
        const href = `#icon-${name}`;
        if (use && use.getAttribute("href") !== href) {
            use.setAttribute("href", href);
        }
    }

    function renderControls() {
        const playing = !media().paused;
        setIcon(ui.toggle, playing ? "pause" : "play");
        ui.toggle.setAttribute("aria-label", playing ? "pause" : "play");
        setIcon(ui.shuffle, state.shuffle ? "shuffle" : "shuffle-off");
        ui.shuffle.classList.toggle("on", state.shuffle);
        ui.shuffle.classList.toggle("off", !state.shuffle);
        ui.shuffle.setAttribute("aria-pressed", String(state.shuffle));
        ui.shuffle.setAttribute("aria-label", state.shuffle ? "shuffle on" : "shuffle off");
        setIcon(ui.repeat, REPEAT_ICONS[state.repeat]);
        ui.repeat.classList.toggle("on", state.repeat !== "off");
        ui.repeat.classList.toggle("off", state.repeat === "off");
        ui.repeat.setAttribute("aria-label", `repeat ${state.repeat}`);
    }

    function renderVolume() {
        ui.volume.classList.toggle("device", deviceVolumeOnly());
        const width = clamp(columnsOf(ui.volume) - 20, 8, 30);
        const level = state.muted ? 0 : state.volume;
        const filled = Math.round(level * width);
        const percent = Math.round(state.volume * 100);
        setText(ui.volbar, "█".repeat(filled) + "·".repeat(width - filled));
        setText(ui.volpct, `${String(percent).padStart(3)}%`);
        ui.volbar.setAttribute("aria-valuenow", String(percent));
        setIcon(ui.mute, state.muted ? "volume-off" : "volume");
        ui.mute.classList.toggle("on", state.muted);
        ui.mute.setAttribute("aria-pressed", String(state.muted));
        ui.mute.setAttribute("aria-label", state.muted ? "unmute" : "mute");
    }

    function bufferedUntil(position) {
        let end = 0;
        try {
            const ranges = media().buffered;
            for (let index = 0; index < ranges.length; index += 1) {
                if (ranges.start(index) <= position + 1) {
                    end = Math.max(end, ranges.end(index));
                }
            }
        } catch (error) {
            return 0;
        }
        return end;
    }

    function renderProgress() {
        const track = state.library[state.current];
        const duration = knownDuration() || (track && track.duration) || 0;
        let position = track ? media().currentTime || 0 : 0;
        if (state.scrubbing !== null && duration) {
            position = state.scrubbing * duration;
        }
        const left = formatTime(position);
        const right = track ? formatTime(duration) : "--:--";
        const width = Math.max(8, columnsOf(ui.progress) - left.length - right.length - 3);
        const filled = duration ? Math.floor(clamp(position / duration, 0, 1) * width) : 0;
        const buffered = duration ? Math.floor(clamp(bufferedUntil(position) / duration, 0, 1) * width) : 0;
        const blinkOff = media().paused && state.scrubbing === null && Math.floor(performance.now() / 530) % 2 === 1;
        let bar = "";
        for (let column = 0; column < width; column += 1) {
            if (column < filled) {
                bar += "█";
            } else if (column === filled && track) {
                bar += blinkOff ? "░" : "▌";
            } else if (column < buffered) {
                bar += "▒";
            } else {
                bar += "░";
            }
        }
        setText(ui.elapsed, left);
        setText(ui.duration, right);
        setText(ui.seekbar, bar);
        ui.seekbar.setAttribute("aria-valuenow", String(duration ? Math.round((position / duration) * 100) : 0));
    }

    function crossfadeLabel() {
        if (engine.native && !volumeControllable) {
            return "n/a";
        }
        return state.crossfade ? `${state.crossfade}s` : "off";
    }

    function renderStatus() {
        const track = state.library[state.current];
        let mode = "-- STOPPED --";
        if (track) {
            if (state.fading) {
                mode = "-- CROSSFADE --";
            } else if (state.buffering && !media().paused) {
                mode = "-- BUFFERING --";
            } else {
                mode = media().paused ? "-- PAUSED --" : "-- PLAYING --";
            }
        }
        const position = state.view.indexOf(state.current);
        const counter = track ? `  ${position >= 0 ? position + 1 : "-"}/${state.view.length}` : "";
        const volume = deviceVolumeOnly() ? "device" : `${Math.round(state.volume * 100)}%`;
        const muted = state.muted ? "(m)" : "";
        setText(ui.statusLeft, mode + counter);
        setText(
            ui.statusRight,
            [
                `SHUF:${state.shuffle ? "on" : "off"}`,
                `RPT:${state.repeat}`,
                `XF:${crossfadeLabel()}`,
                `VOL:${volume}${muted}`,
                `ART:${state.artMode}`,
            ].join("  ")
        );
        setText(ui.artLabel, art.image ? `art:${state.artMode} · ${art.source || "local"}` : art.status);
    }

    function artLayout() {
        const available = ui.art.parentElement.clientWidth || 300;
        const mobile = window.innerWidth < 900;
        const tall = mobile
            ? window.innerHeight * 0.55
            : Math.min(window.innerHeight * 0.4, (ui.left.clientHeight || window.innerHeight) * 0.4);
        const size = Math.max(120, Math.floor(Math.min(available, tall)));
        let columns = 64;
        if (size < 240) {
            columns = 40;
        } else if (size < 380) {
            columns = 52;
        }
        const rows = Math.max(8, Math.round(columns * metrics.ratio));
        return {
            size,
            columns,
            rows,
            cellWidth: size / columns,
            cellHeight: size / rows,
            scale: clamp(window.devicePixelRatio || 1, 1, 3),
        };
    }

    function prepareCanvas(canvas, layout) {
        canvas.width = Math.round(layout.size * layout.scale);
        canvas.height = Math.round(layout.size * layout.scale);
        const context = canvas.getContext("2d");
        context.setTransform(canvas.width / layout.size, 0, 0, canvas.height / layout.size, 0, 0);
        context.font = `100px ${metrics.fontFamily}`;
        const glyphRatio = context.measureText("M").width / 100 || 0.6;
        const fontSize = Math.min(layout.cellHeight * 1.1, layout.cellWidth / glyphRatio);
        context.font = `${fontSize}px ${metrics.fontFamily}`;
        context.textAlign = "center";
        context.textBaseline = "middle";
        return context;
    }

    function sampleImage(image, columns, rows) {
        const key = `${image.src}|${columns}x${rows}`;
        if (art.pixels.key === key) {
            return art.pixels.data;
        }
        const large = document.createElement("canvas");
        large.width = columns * 4;
        large.height = rows * 4;
        const largeContext = large.getContext("2d");
        largeContext.imageSmoothingQuality = "high";
        const side = Math.min(image.naturalWidth, image.naturalHeight);
        largeContext.drawImage(
            image,
            (image.naturalWidth - side) / 2,
            (image.naturalHeight - side) / 2,
            side,
            side,
            0,
            0,
            large.width,
            large.height
        );
        const small = document.createElement("canvas");
        small.width = columns;
        small.height = rows;
        const smallContext = small.getContext("2d", { willReadFrequently: true });
        smallContext.imageSmoothingQuality = "high";
        smallContext.drawImage(large, 0, 0, columns, rows);
        const rgba = smallContext.getImageData(0, 0, columns, rows).data;
        const luminance = new Float32Array(columns * rows);
        let low = 1;
        let high = 0;
        for (let index = 0; index < luminance.length; index += 1) {
            const offset = index * 4;
            const value = (0.2126 * rgba[offset] + 0.7152 * rgba[offset + 1] + 0.0722 * rgba[offset + 2]) / 255;
            luminance[index] = value;
            low = Math.min(low, value);
            high = Math.max(high, value);
        }
        const span = Math.max(0.15, high - low);
        for (let index = 0; index < luminance.length; index += 1) {
            luminance[index] = Math.pow(clamp((luminance[index] - low) / span, 0, 1), 0.9);
        }
        const data = { rgba, luminance };
        art.pixels = { key, data };
        return data;
    }

    function drawBlocks(context, layout) {
        const { columns, rows, size } = layout;
        const pixels = sampleImage(art.image, columns, rows * 2);
        const tiny = document.createElement("canvas");
        tiny.width = columns;
        tiny.height = rows * 2;
        tiny.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(pixels.rgba), columns, rows * 2), 0, 0);
        context.imageSmoothingEnabled = false;
        context.drawImage(tiny, 0, 0, size, size);
    }

    function drawGlyphs(context, layout, colors) {
        const { columns, rows, cellWidth, cellHeight } = layout;
        const pixels = sampleImage(art.image, columns, rows);
        const mono = state.artMode === "mono";
        if (mono) {
            context.fillStyle = colors.fg;
        }
        for (let y = 0; y < rows; y += 1) {
            for (let x = 0; x < columns; x += 1) {
                const index = y * columns + x;
                const glyph = RAMP[Math.round(pixels.luminance[index] * RAMP_LAST)];
                if (glyph === " ") {
                    continue;
                }
                if (!mono) {
                    const offset = index * 4;
                    const red = pixels.rgba[offset];
                    const green = pixels.rgba[offset + 1];
                    const blue = pixels.rgba[offset + 2];
                    const boost = 0.45 + (0.55 * 255) / Math.max(red, green, blue, 1);
                    const channel = (value) => Math.min(255, Math.round(value * boost));
                    context.fillStyle = `rgb(${channel(red)},${channel(green)},${channel(blue)})`;
                }
                context.fillText(glyph, (x + 0.5) * cellWidth, (y + 0.5) * cellHeight);
            }
        }
    }

    function drawVinyl(context, layout, colors) {
        const { columns, rows, cellWidth, cellHeight } = layout;
        const angle = media().paused ? 0.7 : (performance.now() / 1000) * 1.6;
        context.fillStyle = colors.fg;
        for (let y = 0; y < rows; y += 1) {
            for (let x = 0; x < columns; x += 1) {
                const nx = ((x + 0.5) / columns) * 2 - 1;
                const ny = ((y + 0.5) / rows) * 2 - 1;
                const radius = Math.hypot(nx, ny);
                let level;
                if (radius > 0.97 || radius < 0.06) {
                    level = 0;
                } else if (radius > 0.93) {
                    level = 0.5;
                } else if (radius < 0.1) {
                    level = 0.25;
                } else if (radius < 0.34) {
                    level = 0.78 + 0.08 * Math.sin(radius * 60);
                } else {
                    let delta = Math.atan2(ny, nx) - angle;
                    delta = Math.atan2(Math.sin(2 * delta), Math.cos(2 * delta)) / 2;
                    level = 0.1 + 0.1 * (0.5 + 0.5 * Math.sin(radius * 120)) + 0.5 * Math.exp(-delta * delta * 14);
                }
                const glyph = RAMP[Math.round(clamp(level, 0, 1) * RAMP_LAST)];
                if (glyph !== " ") {
                    context.fillText(glyph, (x + 0.5) * cellWidth, (y + 0.5) * cellHeight);
                }
            }
        }
    }

    function buildSprite(layout) {
        const sprite = document.createElement("canvas");
        const context = prepareCanvas(sprite, layout);
        const colors = themeColors();
        if (!art.image) {
            drawVinyl(context, layout, colors);
        } else if (state.artMode === "blocks") {
            drawBlocks(context, layout);
        } else {
            drawGlyphs(context, layout, colors);
        }
        return sprite;
    }

    function paintArt(reveal) {
        const layout = art.layout;
        const context = art.context;
        const { size, rows, columns, cellWidth, cellHeight } = layout;
        const cut = reveal >= 1 ? rows : Math.floor(reveal * rows);
        context.clearRect(0, 0, size, size);
        if (cut > 0) {
            const sourceHeight = (cut * cellHeight * art.sprite.height) / size;
            context.drawImage(art.sprite, 0, 0, art.sprite.width, sourceHeight, 0, 0, size, cut * cellHeight);
        }
        if (cut >= rows) {
            return;
        }
        const colors = themeColors();
        context.globalAlpha = 0.85;
        context.fillStyle = colors.hi;
        context.fillRect(0, cut * cellHeight, size, cellHeight);
        context.globalAlpha = 1;
        context.fillStyle = colors.faint;
        for (let y = cut + 1; y < rows; y += 1) {
            for (let x = 0; x < columns; x += 1) {
                if (Math.random() < 0.4) {
                    const glyph = SCRAMBLE[Math.floor(Math.random() * SCRAMBLE.length)];
                    context.fillText(glyph, (x + 0.5) * cellWidth, (y + 0.5) * cellHeight);
                }
            }
        }
    }

    function drawArt(animate) {
        const layout = artLayout();
        art.layout = layout;
        ui.art.style.width = `${layout.size}px`;
        ui.art.style.height = `${layout.size}px`;
        art.context = prepareCanvas(ui.art, layout);
        ui.art.classList.toggle("glow", !art.image || state.artMode === "mono");
        art.sprite = buildSprite(layout);
        renderStatus();
        art.revealToken += 1;
        const token = art.revealToken;
        if (!animate || reduceMotion) {
            art.revealing = false;
            paintArt(1);
            return;
        }
        art.revealing = true;
        const started = performance.now();
        const step = (now) => {
            if (token !== art.revealToken) {
                return;
            }
            const progress = Math.min(1, (now - started) / REVEAL_MS);
            paintArt(progress);
            if (progress < 1) {
                window.requestAnimationFrame(step);
            } else {
                art.revealing = false;
            }
        };
        window.requestAnimationFrame(step);
    }

    function decodeImage(blob) {
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(blob);
            const image = new Image();
            image.decoding = "async";
            image.onload = () => {
                URL.revokeObjectURL(url);
                if (image.naturalWidth > 0 && image.naturalHeight > 0) {
                    resolve(image);
                } else {
                    reject(new Error("empty image"));
                }
            };
            image.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error("unreadable image"));
            };
            image.src = url;
        });
    }

    async function fetchArt(track, signal) {
        if (!track || !track.art) {
            return null;
        }
        try {
            const response = await fetch(`/art/${encodeURIComponent(track.id)}`, {
                cache: "no-store",
                credentials: "same-origin",
                signal,
            });
            if (!response.ok || response.status === 204) {
                return null;
            }
            const source = response.headers.get("X-Art-Source") || "local";
            const image = await decodeImage(await response.blob());
            return { image, source };
        } catch (error) {
            return null;
        }
    }

    function showArt(fetched) {
        art.image = fetched ? fetched.image : null;
        art.source = fetched ? fetched.source : "";
        art.status = "no art";
        if (fetched && ONLINE_SOURCES.includes(fetched.source)) {
            log(`art: downloaded from ${fetched.source} → ascii (purged when the track finishes)`, "dim");
        }
        drawArt(true);
    }

    async function loadArt(track, prefetched) {
        art.loadToken += 1;
        const token = art.loadToken;
        art.image = null;
        art.source = "";
        if (prefetched) {
            showArt(prefetched);
            return;
        }
        if (!track || !track.art) {
            art.status = "no art";
            drawArt(true);
            return;
        }
        art.status = "fetching…";
        drawArt(false);
        const fetched = await fetchArt(track);
        if (token === art.loadToken) {
            showArt(fetched);
        }
    }

    function animateVinyl() {
        if (art.image || art.revealing || media().paused || !art.layout) {
            return;
        }
        art.sprite = buildSprite(art.layout);
        paintArt(1);
    }

    function buildSpectrumBands(columns) {
        const nyquist = (graph.context ? graph.context.sampleRate : 44100) / 2;
        const bins = graph.analyser ? graph.analyser.frequencyBinCount : 1024;
        const high = Math.min(SPECTRUM_HIGH_HZ, nyquist);
        const ratio = high / SPECTRUM_LOW_HZ;
        spectrum.bands = [];
        for (let column = 0; column < columns; column += 1) {
            const from = SPECTRUM_LOW_HZ * Math.pow(ratio, column / columns);
            const to = SPECTRUM_LOW_HZ * Math.pow(ratio, (column + 1) / columns);
            const first = Math.min(bins - 1, Math.floor((from / nyquist) * bins));
            const last = Math.min(bins, Math.max(first + 1, Math.ceil((to / nyquist) * bins)));
            spectrum.bands.push([first, last]);
        }
        spectrum.targets = new Float32Array(columns);
        spectrum.blurred = new Float32Array(columns);
        spectrum.values = new Float32Array(columns);
        spectrum.peakLevel = new Float32Array(columns);
        spectrum.peakLife = new Float32Array(columns);
        spectrum.climb = new Float32Array(columns);
        spectrum.trough = new Float32Array(columns);
        spectrum.base = new Float32Array(columns);
        spectrum.rising = new Uint8Array(columns).fill(1);
        spectrum.columns = columns;
        spectrum.lines = [];
        const axis = new Array(columns).fill("─");
        let lastEnd = -1;
        SPECTRUM_LABELS.forEach(([frequency, label]) => {
            const column = Math.round((columns * Math.log(frequency / SPECTRUM_LOW_HZ)) / Math.log(ratio));
            if (column > lastEnd + 1 && column + label.length <= columns) {
                for (let offset = 0; offset < label.length; offset += 1) {
                    axis[column + offset] = label[offset];
                }
                lastEnd = column + label.length;
            }
        });
        ui.spectrumAxis.textContent = axis.join("");
    }

    function setSpectrumLabel(text) {
        if (spectrum.label !== text) {
            spectrum.label = text;
            ui.spectrumLabel.textContent = text;
        }
    }

    function approach(current, target, seconds, elapsed) {
        return current + (target - current) * (1 - Math.exp(-elapsed / seconds));
    }

    function ensureSpectrumRows(rows) {
        if (spectrum.lines.length === rows && ui.spectrum.childElementCount === rows + 1) {
            return;
        }
        ui.spectrum.replaceChildren();
        spectrum.lines = [];
        spectrum.peakLines = [];
        const overlay = document.createElement("div");
        overlay.className = "peaks";
        const hotRows = Math.max(1, Math.round(rows * 0.25));
        for (let row = rows - 1; row >= 0; row -= 1) {
            const line = document.createElement("div");
            if (row >= rows - hotRows) {
                line.className = "vh";
            }
            ui.spectrum.appendChild(line);
            spectrum.lines[row] = line;
            const peakLine = document.createElement("div");
            overlay.appendChild(peakLine);
            spectrum.peakLines[row] = { element: peakLine, html: "" };
        }
        ui.spectrum.appendChild(overlay);
    }

    function trackPeak(column, value, live) {
        const { peakLevel, peakLife, climb, trough, base, rising } = spectrum;
        if (!live) {
            rising[column] = 1;
            climb[column] = value;
            base[column] = value;
            return;
        }
        if (rising[column]) {
            if (value >= climb[column]) {
                climb[column] = value;
            } else if (climb[column] - value >= SPECTRUM_PEAK_DROP) {
                const prominent = climb[column] - base[column] >= SPECTRUM_PEAK_PROMINENCE;
                if (prominent && climb[column] >= SPECTRUM_PEAK_MINIMUM) {
                    peakLevel[column] = climb[column];
                    peakLife[column] = 1;
                }
                rising[column] = 0;
                trough[column] = value;
            }
        } else if (value <= trough[column]) {
            trough[column] = value;
        } else if (value - trough[column] >= SPECTRUM_PEAK_RISE) {
            rising[column] = 1;
            climb[column] = value;
            base[column] = trough[column];
        }
    }

    function renderPeaks(rows, maximum) {
        const { columns, peakLevel, peakLife } = spectrum;
        const cells = Array.from({ length: rows }, () => null);
        for (let column = 0; column < columns; column += 1) {
            if (peakLife[column] <= 0) {
                continue;
            }
            const height = Math.min(maximum - 0.5, peakLevel[column] * maximum + SPECTRUM_PEAK_GAP);
            const row = clamp(Math.floor(height / 8), 0, rows - 1);
            const glyph = height - row * 8 < 4 ? "▁" : "▔";
            const step = clamp(Math.ceil(peakLife[column] * SPECTRUM_PEAK_STEPS), 1, SPECTRUM_PEAK_STEPS);
            if (!cells[row]) {
                cells[row] = new Array(columns).fill(" ");
            }
            cells[row][column] = `<span class="p${step}">${glyph}</span>`;
        }
        for (let row = 0; row < rows; row += 1) {
            const html = cells[row] ? cells[row].join("") : "";
            const slot = spectrum.peakLines[row];
            if (slot.html !== html) {
                slot.html = html;
                slot.element.innerHTML = html;
            }
        }
    }

    function spectrumTargets(live, seconds) {
        const { columns, targets, bands } = spectrum;
        if (live) {
            graph.analyser.getByteFrequencyData(graph.bins);
            for (let column = 0; column < columns; column += 1) {
                const [first, last] = bands[column];
                let total = 0;
                for (let bin = first; bin < last; bin += 1) {
                    total += graph.bins[bin];
                }
                const energy = total / Math.max(1, last - first) / 255;
                targets[column] = Math.pow(energy, 1.5) * (1 + (0.6 * column) / columns);
            }
            return;
        }
        if (reduceMotion) {
            targets.fill(0);
            return;
        }
        const breath = 0.6 + 0.4 * Math.sin(seconds * 0.37);
        for (let column = 0; column < columns; column += 1) {
            const phase = seconds * 0.9 + (column / columns) * Math.PI * 2.4;
            targets[column] = SPECTRUM_IDLE_LEVEL * breath * (0.55 + 0.45 * Math.sin(phase));
        }
    }

    function blurSpectrum() {
        const { columns, targets, blurred } = spectrum;
        for (let pass = 0; pass < 2; pass += 1) {
            const source = pass === 0 ? targets : blurred;
            const copy = Float32Array.from(source);
            for (let column = 0; column < columns; column += 1) {
                const left = copy[Math.max(0, column - 1)];
                const right = copy[Math.min(columns - 1, column + 1)];
                blurred[column] = (left + 2 * copy[column] + right) / 4;
            }
        }
    }

    function renderSpectrum(now) {
        if (spectrum.columns !== metrics.spectrumColumns) {
            buildSpectrumBands(metrics.spectrumColumns);
        }
        const elapsed = clamp((now - (spectrum.lastTime || now)) / 1000, 0, 0.1);
        spectrum.lastTime = now;
        const playing = !media().paused && state.current >= 0;
        if (!graph.analyser && playing) {
            let message = "[ tap anywhere to start the spectrum ]";
            if (!state.spectrum) {
                message = "[ spectrum off — type: viz on ]";
            } else if (graph.failed) {
                message = "[ spectrum unavailable in this browser ]";
            }
            if (spectrum.message !== message) {
                spectrum.message = message;
                spectrum.lines = [];
                ui.spectrum.textContent = message;
            }
            setSpectrumLabel(state.spectrum ? "waiting" : "off");
            return;
        }
        spectrum.message = "";
        const { columns, blurred, values, peakLife } = spectrum;
        const rows = metrics.spectrumRows;
        const live = Boolean(graph.analyser) && playing;
        const seconds = now / 1000;
        ensureSpectrumRows(rows);
        spectrumTargets(live, seconds);
        blurSpectrum();
        for (let column = 0; column < columns; column += 1) {
            let target = blurred[column];
            if (live && !reduceMotion) {
                target *= 1 + SPECTRUM_SWAY * Math.sin(2 * Math.PI * (SPECTRUM_SWAY_HZ * seconds - column / columns));
            }
            target = clamp(target, 0, 1);
            const value = values[column];
            const response = target > value ? SPECTRUM_ATTACK_SECONDS : SPECTRUM_RELEASE_SECONDS;
            values[column] = approach(value, target, response, elapsed);
            peakLife[column] = Math.max(0, peakLife[column] - elapsed / SPECTRUM_PEAK_FADE_SECONDS);
            if (values[column] >= spectrum.peakLevel[column]) {
                peakLife[column] = 0;
            }
            trackPeak(column, values[column], live);
        }
        ui.spectrum.classList.toggle("quiet", !live);
        if (live && graph.context) {
            setSpectrumLabel(`live · ${graph.context.sampleRate / 1000}kHz`);
        } else {
            setSpectrumLabel(playing || state.current >= 0 ? "breathing" : "idle");
        }
        const maximum = rows * 8;
        for (let row = rows - 1; row >= 0; row -= 1) {
            let line = "";
            for (let column = 0; column < columns; column += 1) {
                const level = values[column] * maximum - row * 8;
                if (level >= 7.5) {
                    line += "█";
                } else if (level >= 0.5) {
                    line += BLOCKS[clamp(Math.round(level), 1, 8)];
                } else {
                    line += row === 0 ? "_" : " ";
                }
            }
            setText(spectrum.lines[row], line);
        }
        renderPeaks(rows, maximum);
    }

    function frame(now) {
        window.requestAnimationFrame(frame);
        renderSpectrum(now);
        if (graph.twin && now - timers.twin >= TWIN_SYNC_MS) {
            timers.twin = now;
            syncTwin();
        }
        if (now - timers.progress >= PROGRESS_FRAME_MS) {
            timers.progress = now;
            renderProgress();
        }
        if (now - timers.vinyl >= VINYL_FRAME_MS) {
            timers.vinyl = now;
            animateVinyl();
        }
        if (now - timers.save >= SAVE_INTERVAL_MS) {
            timers.save = now;
            if (!media().paused) {
                saveState();
            }
        }
    }

    function tickClock() {
        const now = new Date();
        const date = now.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" });
        const time = now.toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
            second: "2-digit",
            hour12: true,
        });
        ui.clock.textContent = `${date}  ${time}`;
    }

    async function pollStatus() {
        try {
            const status = await request("/api/status");
            state.status = status;
            const parts = [status.host];
            if (Number.isFinite(status.temp_c)) {
                parts.push(`${status.temp_c.toFixed(1)}°C`);
            }
            if (Array.isArray(status.load)) {
                parts.push(`load ${Number(status.load[0]).toFixed(2)}`);
            }
            if (Number.isFinite(status.uptime_s)) {
                parts.push(`up ${formatUptime(status.uptime_s)}`);
            }
            ui.sysline.textContent = parts.join(" │ ");
        } catch (error) {
            state.status = null;
            ui.sysline.textContent = "!! server unreachable";
        }
    }

    const HELP_SECTIONS = [
        ["playback", [
            ["play [n | text]", "play track n, the first match for text, or resume"],
            ["pause · resume · stop", "pause, resume, or stop and rewind"],
            ["next · prev", "skip forward or back"],
            ["seek <1:23 | +10 | -10>", "jump within the track"],
            ["fade <0-12>", "crossfade seconds between tracks (0 = off)"],
        ]],
        ["library", [
            ["find <text>", "filter the library (shortcut: /text)"],
            ["clear", "remove the filter"],
            ["albums", "list albums"],
            ["album <n>", "show one album from the list"],
            ["rescan", "re-index the music folder"],
        ]],
        ["sound & look", [
            ["vol <0-100>", "set the volume"],
            ["shuffle [on | off]", "shuffle tracks"],
            ["repeat [off | all | one]", "repeat mode"],
            ["art [color | blocks | mono]", "album art style"],
            ["theme [hyper | green | amber | ice]", "colour scheme"],
            ["viz [on | off]", "spectrum scope"],
        ]],
        ["system", [
            ["sys", "raspberry pi vitals"],
            ["cls", "clear this output (or press esc)"],
            ["help", "show this help"],
        ]],
    ];

    const KEY_HELP = [
        ["space", "play / pause"],
        ["n · p", "next / previous track"],
        ["← · →", "seek 10 seconds"],
        ["↑ ↓ · j k", "move the selection"],
        ["pgup · pgdn", "move the selection by a page"],
        ["home · end · g G", "jump to the top or bottom"],
        ["enter", "play the selection"],
        ["/", "find"],
        [":", "type a command"],
        ["s · r", "shuffle / repeat"],
        ["+ · -", "volume up / down"],
        ["m", "mute"],
        ["c · t", "art style / theme"],
        ["esc", "clear the filter, then this output"],
    ];

    function toggleArgument(argument, current) {
        if (argument === "on") {
            return true;
        }
        if (argument === "off") {
            return false;
        }
        return argument ? null : !current;
    }

    const COMMANDS = {
        help() {
            HELP_SECTIONS.forEach(([title, rows]) => {
                termHeading(title);
                termTable(rows);
            });
            termHeading("keys");
            termTable(KEY_HELP);
        },
        play(argument) {
            if (!argument) {
                resumePlayback();
                return;
            }
            if (/^\d+$/.test(argument)) {
                const index = Number.parseInt(argument, 10) - 1;
                if (state.library[index]) {
                    playTrack(index);
                } else {
                    log(`no track #${argument}`, "err");
                }
                return;
            }
            const words = argument.toLowerCase().split(/\s+/);
            const match = state.library.find((track) => words.every((word) => track.search.includes(word)));
            if (match) {
                playTrack(match.index);
            } else {
                log(`no match for "${argument}"`, "err");
            }
        },
        pause() {
            pausePlayback();
        },
        resume() {
            resumePlayback();
        },
        stop() {
            stopPlayback();
        },
        next() {
            playNext(false);
        },
        prev() {
            playPrevious();
        },
        find(argument) {
            applyFilter(argument);
        },
        clear() {
            applyFilter("");
        },
        albums() {
            if (!state.albums.length) {
                termLine("no albums", "dim");
                return;
            }
            termHeading(`albums · ${state.albums.length}`);
            termTable(
                state.albums.slice(0, ALBUM_LIST_LIMIT).map((album, index) => [
                    `[${String(index + 1).padStart(2, "0")}]`,
                    `${album.album} — ${album.artist} · ${plural(album.count, "track")}`,
                ]),
                true
            );
            if (state.albums.length > ALBUM_LIST_LIMIT) {
                termLine(`… ${state.albums.length - ALBUM_LIST_LIMIT} more — use find`, "dim");
            }
            termLine("album <n> shows one", "dim");
        },
        album(argument) {
            const album = state.albums[Number.parseInt(argument, 10) - 1];
            if (!album) {
                log("usage: album <n>  (see: albums)", "dim");
                return;
            }
            applyFilter(`${album.album} ${album.artist}`);
        },
        shuffle(argument) {
            const value = toggleArgument(argument, state.shuffle);
            if (value === null) {
                log("usage: shuffle [on|off]", "dim");
            } else {
                setShuffle(value);
            }
        },
        repeat(argument) {
            if (REPEAT_MODES.includes(argument)) {
                setRepeat(argument);
            } else if (!argument) {
                setRepeat(cycle(state.repeat, REPEAT_MODES));
            } else {
                log("usage: repeat off|all|one", "dim");
            }
        },
        vol(argument) {
            const value = Number.parseInt(argument, 10);
            if (Number.isNaN(value)) {
                log(`volume ${Math.round(state.volume * 100)}%`);
                return;
            }
            setVolume(clamp(value, 0, 100) / 100);
        },
        fade(argument) {
            const value = Number.parseInt(argument, 10);
            if (Number.isNaN(value)) {
                const current = state.crossfade ? `${state.crossfade}s` : "off";
                log(`crossfade ${current}  (usage: fade 0-${CROSSFADE_MAX})`, "dim");
                return;
            }
            setCrossfade(value);
        },
        seek(argument) {
            if (!argument) {
                log("usage: seek 1:23 | +10 | -10", "dim");
                return;
            }
            if (state.current < 0) {
                log("nothing is playing", "dim");
                return;
            }
            if (/^[+-]\d+$/.test(argument)) {
                seekBy(Number.parseInt(argument, 10));
                return;
            }
            const seconds = parseClock(argument);
            if (Number.isNaN(seconds)) {
                log(`bad time: ${argument}`, "err");
                return;
            }
            seekTo(seconds);
        },
        art(argument) {
            if (ART_MODES.includes(argument)) {
                setArtMode(argument);
            } else if (!argument) {
                setArtMode(cycle(state.artMode, ART_MODES));
            } else {
                log("usage: art color|blocks|mono", "dim");
            }
        },
        theme(argument) {
            if (THEMES.includes(argument)) {
                setTheme(argument);
            } else if (!argument) {
                setTheme(cycle(state.theme, THEMES));
            } else {
                log(`usage: theme ${THEMES.join("|")}`, "dim");
            }
        },
        viz(argument) {
            const value = toggleArgument(argument, state.spectrum);
            if (value === null) {
                log("usage: viz [on|off]", "dim");
            } else {
                setSpectrum(value);
            }
        },
        async sys() {
            await pollStatus();
            const status = state.status;
            if (!status) {
                termLine("no status available", "err");
                return;
            }
            const rows = [
                ["host", status.host],
                ["system", `${state.info.machine || "?"} · python ${state.info.python || "?"}`],
            ];
            if (Number.isFinite(status.temp_c)) {
                const filled = Math.round(clamp((status.temp_c - 30) / 55, 0, 1) * 10);
                rows.push([
                    "cpu temp",
                    `${status.temp_c.toFixed(1)}°C [${"█".repeat(filled)}${"·".repeat(10 - filled)}]`,
                    status.temp_c > 75 ? "warn" : "",
                ]);
            }
            if (Array.isArray(status.load)) {
                rows.push(["load", status.load.map((value) => Number(value).toFixed(2)).join(" · ")]);
            }
            if (Number.isFinite(status.uptime_s)) {
                rows.push(["uptime", formatUptime(status.uptime_s)]);
            }
            if (Number.isFinite(status.disk_free_gb)) {
                rows.push(["disk", `${status.disk_free_gb} GB free of ${status.disk_total_gb} GB`]);
            }
            rows.push([
                "library",
                [
                    plural(state.info.count, "track"),
                    plural(state.info.albums, "album"),
                    plural(state.info.artists, "artist"),
                ].join(" · "),
            ]);
            termHeading("system");
            termTable(rows, true);
        },
        async rescan() {
            termLine("rescanning music folder…", "dim");
            await request("/api/rescan", { method: "POST", headers: { "X-BadBanana": "1" } });
            await loadLibrary();
            termLine(`indexed ${plural(state.library.length, "track")} · ${plural(state.albums.length, "album")}`, "hi");
        },
        cls() {
            clearTerminal();
        },
    };

    const ALIASES = {
        "?": "help",
        h: "help",
        search: "find",
        grep: "find",
        ls: "albums",
        clr: "cls",
        volume: "vol",
    };

    function runCommand(line) {
        const text = line.trim();
        if (!text) {
            return;
        }
        termEcho(text);
        inTerminal(() => {
            if (text.startsWith("/")) {
                applyFilter(text.slice(1));
                return;
            }
            const [word, ...rest] = text.split(/\s+/);
            const name = word.toLowerCase();
            const key = Object.prototype.hasOwnProperty.call(COMMANDS, name) ? name : ALIASES[name];
            const handler = key ? COMMANDS[key] : null;
            if (!handler) {
                termLine(`${word}: command not found — try 'help'`, "err");
                return;
            }
            const argument = rest.join(" ");
            let result;
            try {
                result = handler(key === "find" ? argument : argument.toLowerCase());
            } catch (error) {
                termLine(`error: ${error.message}`, "err");
                return;
            }
            if (result && typeof result.then === "function") {
                result.catch((error) => termLine(`error: ${error.message}`, "err"));
            }
        });
    }

    function completeCommand() {
        const value = ui.command.value.toLowerCase();
        if (value.includes(" ")) {
            return;
        }
        const matches = Object.keys(COMMANDS).filter((name) => name.startsWith(value));
        if (matches.length === 1) {
            ui.command.value = `${matches[0]} `;
        } else if (matches.length > 1) {
            termLine(matches.join("  "), "dim");
        }
    }

    function fractionAt(element, event) {
        const bounds = element.getBoundingClientRect();
        return bounds.width ? clamp((event.clientX - bounds.left) / bounds.width, 0, 1) : 0;
    }

    function bindScrubber(element, onMove, onCommit, track) {
        const measure = track || element;
        let active = null;
        element.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) {
                return;
            }
            event.preventDefault();
            active = event.pointerId;
            element.setPointerCapture(event.pointerId);
            onMove(fractionAt(measure, event));
        });
        element.addEventListener("pointermove", (event) => {
            if (active === event.pointerId) {
                onMove(fractionAt(measure, event));
            }
        });
        element.addEventListener("pointerup", (event) => {
            if (active !== event.pointerId) {
                return;
            }
            active = null;
            if (element.hasPointerCapture(event.pointerId)) {
                element.releasePointerCapture(event.pointerId);
            }
            onCommit(fractionAt(measure, event));
        });
        element.addEventListener("pointercancel", (event) => {
            if (active === event.pointerId) {
                active = null;
                onCommit(null);
            }
        });
        element.addEventListener("lostpointercapture", (event) => {
            if (active === event.pointerId) {
                active = null;
                onCommit(null);
            }
        });
    }

    function handleVolumeKeys(event) {
        const steps = {
            ArrowLeft: -VOLUME_STEP,
            ArrowDown: -VOLUME_STEP,
            ArrowRight: VOLUME_STEP,
            ArrowUp: VOLUME_STEP,
            PageDown: -0.2,
            PageUp: 0.2,
        };
        if (Object.prototype.hasOwnProperty.call(steps, event.key)) {
            setVolume(state.volume + steps[event.key]);
        } else if (event.key === "Home") {
            setVolume(0);
        } else if (event.key === "End") {
            setVolume(1);
        } else {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
    }

    const ACTIONS = {
        prev: () => playPrevious(),
        toggle: () => togglePlayback(),
        next: () => playNext(false),
        shuffle: () => setShuffle(!state.shuffle),
        repeat: () => setRepeat(cycle(state.repeat, REPEAT_MODES)),
        mute: () => toggleMute(),
    };

    function handleClick(event) {
        const button = event.target.closest("[data-action]");
        if (button) {
            const action = ACTIONS[button.dataset.action];
            if (action) {
                action();
            }
            return;
        }
        const row = event.target.closest(".row");
        if (row) {
            const position = Number(row.dataset.pos);
            state.selected = position;
            playTrack(state.view[position]);
            return;
        }
        if (event.target.closest("#status-left")) {
            togglePlayback();
        }
    }

    function handleCommandKeys(event) {
        if (event.key === "Escape") {
            if (ui.command.value) {
                ui.command.value = "";
            } else {
                ui.command.blur();
                KEYS.Escape();
            }
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            if (state.commandCursor > 0) {
                state.commandCursor -= 1;
                ui.command.value = state.commandHistory[state.commandCursor];
            }
        } else if (event.key === "ArrowDown") {
            event.preventDefault();
            state.commandCursor = Math.min(state.commandHistory.length, state.commandCursor + 1);
            ui.command.value = state.commandHistory[state.commandCursor] || "";
        } else if (event.key === "Tab") {
            event.preventDefault();
            completeCommand();
        }
    }

    const KEYS = {
        " ": () => togglePlayback(),
        n: () => playNext(false),
        p: () => playPrevious(),
        ArrowRight: () => seekBy(SEEK_STEP),
        ArrowLeft: () => seekBy(-SEEK_STEP),
        ArrowDown: () => moveSelection(1),
        j: () => moveSelection(1),
        ArrowUp: () => moveSelection(-1),
        k: () => moveSelection(-1),
        PageDown: () => moveSelection(15),
        PageUp: () => moveSelection(-15),
        Home: () => moveSelection(-Infinity),
        g: () => moveSelection(-Infinity),
        End: () => moveSelection(Infinity),
        G: () => moveSelection(Infinity),
        Enter: () => {
            if (state.view.length) {
                playTrack(state.view[state.selected]);
            }
        },
        "/": () => {
            ui.command.value = "find ";
            ui.command.focus();
        },
        ":": () => {
            ui.command.value = "";
            ui.command.focus();
        },
        s: () => setShuffle(!state.shuffle),
        r: () => setRepeat(cycle(state.repeat, REPEAT_MODES)),
        "+": () => setVolume(state.volume + VOLUME_STEP),
        "=": () => setVolume(state.volume + VOLUME_STEP),
        "-": () => setVolume(state.volume - VOLUME_STEP),
        _: () => setVolume(state.volume - VOLUME_STEP),
        m: () => toggleMute(),
        c: () => setArtMode(cycle(state.artMode, ART_MODES)),
        t: () => setTheme(cycle(state.theme, THEMES)),
        "?": () => COMMANDS.help(),
        Escape: () => {
            if (state.filter) {
                applyFilter("");
            } else if (!ui.terminal.hidden) {
                clearTerminal();
            }
        },
    };

    function handleKeydown(event) {
        if (!state.booted) {
            if (!["Shift", "Control", "Alt", "Meta"].includes(event.key)) {
                event.preventDefault();
                dismissBoot();
            }
            return;
        }
        const target = event.target;
        if (target === ui.command) {
            return;
        }
        if (target instanceof HTMLButtonElement && (event.key === " " || event.key === "Enter")) {
            return;
        }
        if (event.ctrlKey || event.metaKey || event.altKey) {
            return;
        }
        const action = Object.prototype.hasOwnProperty.call(KEYS, event.key) ? KEYS[event.key] : null;
        if (action) {
            event.preventDefault();
            action();
        }
    }

    function handleResize() {
        window.clearTimeout(timers.resize);
        timers.resize = window.setTimeout(() => {
            measure();
            fitBoot();
            spectrum.columns = 0;
            drawArt(false);
            renderVolume();
            renderProgress();
        }, 150);
    }

    function bindDeckEvents(deck) {
        const audio = deck.audio;
        const isActive = () => audio === media();
        audio.addEventListener("play", () => {
            if (!isActive()) {
                return;
            }
            state.autoplay = true;
            resumeAudio();
            renderControls();
            renderStatus();
            syncTwin();
            updatePositionState(true);
        });
        audio.addEventListener("pause", () => {
            if (!isActive()) {
                return;
            }
            renderControls();
            renderStatus();
            saveState();
            syncTwin();
            updatePositionState(true);
        });
        audio.addEventListener("ended", handleEnded);
        audio.addEventListener("timeupdate", () => {
            if (isActive()) {
                checkCrossfade();
                updatePositionState(false);
            }
        });
        audio.addEventListener("seeked", () => {
            if (isActive()) {
                syncTwin();
                updatePositionState(true);
            }
        });
        audio.addEventListener("ratechange", () => {
            if (isActive()) {
                updatePositionState(true);
            }
        });
        audio.addEventListener("waiting", () => {
            if (isActive()) {
                state.buffering = true;
                renderStatus();
            }
        });
        audio.addEventListener("playing", () => {
            if (isActive()) {
                state.buffering = false;
                state.errors = 0;
                renderStatus();
            }
        });
        audio.addEventListener("loadedmetadata", () => {
            if (!isActive()) {
                return;
            }
            if (state.pendingSeek) {
                seekTo(state.pendingSeek);
                state.pendingSeek = 0;
            }
            updatePositionState(true);
            const track = state.library[state.current];
            const duration = knownDuration();
            if (track && duration && Math.abs((track.duration || 0) - duration) > 1) {
                track.duration = duration;
                const row = rowAt(state.view.indexOf(state.current));
                if (row) {
                    row.querySelector(".d").textContent = formatTime(duration);
                }
            }
        });
        audio.addEventListener("error", () => {
            if (!audio.getAttribute("src")) {
                return;
            }
            if (!isActive()) {
                if (deck.trackId) {
                    deck.status = "unplayable";
                    renderUpNext();
                }
                return;
            }
            const track = state.library[state.current];
            if (!track) {
                return;
            }
            const code = audio.error ? audio.error.code : "?";
            log(`ERR ${code}: can't play "${track.title}" (.${track.ext}) — format not supported by this browser?`, "err");
            state.buffering = false;
            renderStatus();
            if (!state.autoplay) {
                return;
            }
            state.errors += 1;
            if (state.errors < MAX_CONSECUTIVE_ERRORS) {
                const failed = track.id;
                window.setTimeout(() => {
                    const current = state.library[state.current];
                    if (current && current.id === failed) {
                        playNext(true, true);
                    }
                }, 1500);
            } else {
                log("too many errors in a row; stopped", "err");
            }
        });
    }

    function handleVisibility() {
        saveState();
        if (!document.hidden) {
            resumeAudio();
            spectrum.lastTime = 0;
            updatePositionState(true);
        }
        syncTwin();
        renderStatus();
    }

    function bindEvents() {
        decks.forEach(bindDeckEvents);

        document.addEventListener("click", handleClick);
        document.addEventListener("keydown", handleKeydown);
        document.addEventListener("pointerdown", () => {
            if (state.booted && !graph.context && state.spectrum && !graph.failed) {
                ensureAudioGraph();
            }
        });
        document.addEventListener("visibilitychange", handleVisibility);
        window.addEventListener("pagehide", () => {
            saveState();
            purgeArt(state.library[state.current]);
            const upcoming = trackById(idleDeck().trackId);
            if (upcoming && upcoming !== state.library[state.current]) {
                purgeArt(upcoming);
            }
        });
        window.addEventListener("resize", handleResize);
        if (typeof window.ResizeObserver === "function") {
            new window.ResizeObserver(handleResize).observe(ui.terminal);
        }

        ui.boot.addEventListener("click", dismissBoot);
        ui.command.addEventListener("keydown", handleCommandKeys);
        ui.form.addEventListener("submit", (event) => {
            event.preventDefault();
            const value = ui.command.value;
            if (value.trim()) {
                state.commandHistory.push(value);
                state.commandCursor = state.commandHistory.length;
            }
            ui.command.value = "";
            runCommand(value);
        });

        bindScrubber(
            ui.seekbar,
            (fraction) => {
                if (state.current >= 0 && knownDuration()) {
                    state.scrubbing = fraction;
                    renderProgress();
                }
            },
            (fraction) => {
                const scrubbing = state.scrubbing;
                state.scrubbing = null;
                if (fraction !== null && scrubbing !== null) {
                    seekFraction(fraction);
                }
                renderProgress();
            }
        );
        bindScrubber(
            ui.volumeSlider,
            (fraction) => setVolume(fraction),
            (fraction) => {
                if (fraction !== null) {
                    setVolume(fraction);
                }
            },
            ui.volbar
        );
        ui.volbar.addEventListener("keydown", handleVolumeKeys);

        bindMediaSession();
    }

    function dismissBoot() {
        if (state.booted) {
            return;
        }
        state.booted = true;
        state.bootFast = true;
        ensureAudioGraph();
        ui.boot.classList.add("gone");
        window.setTimeout(() => {
            ui.boot.hidden = true;
        }, 400);
        measure();
        spectrum.columns = 0;
        drawArt(false);
        renderVolume();
        renderProgress();
    }

    function bootLine(text, kind) {
        const line = document.createElement("div");
        if (kind) {
            line.className = kind;
        }
        line.textContent = text || "\u00a0";
        ui.boot.appendChild(line);
        fitBoot();
        return line;
    }

    function playbackSummary() {
        if (engine.native && !volumeControllable) {
            return "gapless · background play";
        }
        const fade = state.crossfade ? `${state.crossfade}s crossfade` : "gapless";
        return `${fade} · background play`;
    }

    function bootEntry(label, value, kind) {
        const line = document.createElement("div");
        line.className = kind ? `entry ${kind}` : "entry";
        const labelElement = document.createElement("span");
        labelElement.className = "label";
        labelElement.textContent = label;
        const leader = document.createElement("span");
        leader.className = "leader";
        leader.setAttribute("aria-hidden", "true");
        leader.textContent = ".".repeat(400);
        const valueElement = document.createElement("span");
        valueElement.className = "value";
        valueElement.textContent = value;
        line.append(labelElement, leader, valueElement);
        ui.boot.appendChild(line);
        fitBoot();
        return line;
    }

    function fitBoot() {
        if (ui.boot.hidden) {
            return;
        }
        ui.boot.style.fontSize = "";
        const style = window.getComputedStyle(ui.boot);
        const available = ui.boot.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const base = parseFloat(style.fontSize) || metrics.fontSize;
        let longest = 0;
        Array.from(ui.boot.children).forEach((child) => {
            if (child.classList.contains("entry")) {
                const label = child.querySelector(".label").textContent.length;
                const value = child.querySelector(".value").textContent.length;
                longest = Math.max(longest, label + value + 6);
            } else {
                const lines = child.textContent.split("\n");
                lines.forEach((line) => {
                    longest = Math.max(longest, line.trimEnd().length);
                });
            }
        });
        if (!longest || available <= 0) {
            return;
        }
        const fitted = Math.floor((available / (longest * metrics.ratio)) * 10) / 10;
        if (fitted < base) {
            ui.boot.style.fontSize = `${Math.max(8, fitted)}px`;
        }
    }

    async function connect() {
        for (;;) {
            try {
                const [data, status] = await Promise.all([
                    loadLibrary(),
                    request("/api/status").catch(() => ({})),
                ]);
                return { data, status };
            } catch (error) {
                bootLine(`[FAIL] cannot reach server (${error.message}) — retrying in 3s`, "bad");
                log(`cannot reach server (${error.message}) — retrying`, "err");
                await sleep(3000);
            }
        }
    }

    async function boot() {
        const logo = ui.logo.cloneNode(true);
        logo.removeAttribute("id");
        logo.querySelectorAll("small").forEach((element) => element.remove());
        logo.className = "boot-logo ok";
        ui.boot.appendChild(logo);
        fitBoot();
        bootLine("");
        const banner = bootLine("BAD BANANA terminal audio subsystem");
        const { data, status } = await connect();
        banner.textContent = `BAD BANANA/${data.version || "?"} terminal audio subsystem`;
        fitBoot();
        const layout = artLayout();
        const providers = Array.isArray(data.online_art) ? data.online_art : [];
        const entries = [
            [`host ${data.host}`, `${data.machine} · python ${data.python}`, ""],
            ["[ OK ] mounted library", `~/${data.root}`, "ok"],
            [
                "[ OK ] indexed",
                [plural(data.count, "track"), plural(data.albums, "album"), plural(data.artists, "artist")].join(" · "),
                "ok",
            ],
            ["[ OK ] tag reader", "built-in (no extra packages)", "ok"],
            ["[ OK ] stream server", "http range / seek enabled", "ok"],
            ["[ OK ] playback", playbackSummary(), "ok"],
            providers.length
                ? ["[ OK ] album art", `${providers.join(" → ")} · auto-purge`, "ok"]
                : ["[ OK ] album art", "local files only", "ok"],
            ["[ OK ] ascii renderer", `${layout.columns}×${layout.rows} · ${state.artMode}`, "ok"],
        ];
        if (Number.isFinite(status.temp_c)) {
            const hot = status.temp_c > 75;
            entries.push([`${hot ? "[WARN]" : "[ OK ]"} cpu temperature`, `${status.temp_c.toFixed(1)}°C`, hot ? "bad" : "ok"]);
        }
        for (const [label, value, kind] of entries) {
            bootEntry(label, value, kind);
            if (!state.bootFast) {
                await sleep(70);
            }
        }
        bootLine("");
        const prompt = bootLine("press any key to continue ");
        const cursor = document.createElement("span");
        cursor.className = "blink";
        cursor.textContent = "█";
        prompt.appendChild(cursor);
        pollStatus();
        state.statusTimer = window.setInterval(pollStatus, STATUS_INTERVAL_MS);
        log(`ready — ${plural(data.count, "track")}. tap a track or press space to play.`, "hi");
        const last = storage.get("last", null);
        const lastTrack = last && typeof last.id === "string" ? state.library.find((track) => track.id === last.id) : null;
        if (lastTrack && state.current < 0) {
            const at = Number(last.t);
            playTrack(lastTrack.index, { paused: true, at: Number.isFinite(at) && at > 5 ? at : 0 });
        }
    }

    function initialise() {
        ui.measure.textContent = "M".repeat(100);
        state.volume = storedNumber("volume", 1, 0, 1);
        if (navigator.audioSession) {
            try {
                navigator.audioSession.type = "playback";
            } catch (error) {
                log("audio session type unavailable", "dim");
            }
        }
        applyVolume();
        applyTheme();
        measure();
        bindEvents();
        renderControls();
        renderVolume();
        renderNowPlaying(null);
        drawArt(false);
        renderStatus();
        tickClock();
        window.setInterval(tickClock, 1000);
        window.requestAnimationFrame(frame);
        boot();
    }

    initialise();
})();
"""

if __name__ == "__main__":
    sys.exit(main())
