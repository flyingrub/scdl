from base64 import b64encode
from dataclasses import dataclass
from typing import Optional, Type, TypeVar, Union, Callable
from types import MappingProxyType

from mutagen import FileType, flac, oggopus, id3, wave, mp3


JPEG_MIME_TYPE: str = 'image/jpeg'


@dataclass(frozen=True)
class MetadataInfo:
    artist: str
    title: str
    description: Optional[str]
    genre: Optional[str]

    artwork_jpeg: Optional[bytes]

    link: Optional[str]
    date: Optional[str]

    album_title: Optional[str]
    album_author: Optional[str]
    album_track_num: Optional[int]


def _get_flac_pic(jpeg_data: bytes) -> flac.Picture:
    pic = flac.Picture()
    pic.data = jpeg_data
    pic.mime = JPEG_MIME_TYPE
    pic.type = id3.PictureType.COVER_FRONT
    return pic


def _get_apic(jpeg_data: bytes) -> id3.APIC:
    return id3.APIC(
        encoding=3,
        mime=JPEG_MIME_TYPE,
        type=3,
        desc='Cover',
        data=jpeg_data,
    )


def _assemble_common(file: FileType, meta: MetadataInfo) -> None:
    file['artist'] = meta.artist
    file['title'] = meta.title

    if meta.genre:
        file['genre'] = meta.genre

    if meta.link:
        file['website'] = meta.link

    if meta.date:
        file['date'] = meta.date

    if meta.album_title:
        file['album'] = meta.album_title

    if meta.album_author:
        file['albumartist'] = meta.album_author

    if meta.album_track_num is not None:
        file['tracknumber'] = str(meta.album_track_num)


def _assemble_flac(file: flac.FLAC, meta: MetadataInfo) -> None:
    _assemble_common(file, meta)

    if meta.description:
        file['description'] = meta.description

    if meta.artwork_jpeg:
        file.add_picture(_get_flac_pic(meta.artwork_jpeg))


def _assemble_opus(file: oggopus.OggOpus, meta: MetadataInfo) -> None:
    _assemble_common(file, meta)

    if meta.description:
        file['comment'] = meta.description

    if meta.artwork_jpeg:
        pic = _get_flac_pic(meta.artwork_jpeg).write()
        file['metadata_block_picture'] = b64encode(pic).decode()


def _assemble_wav_or_mp3(file: Union[wave.WAVE, mp3.MP3], meta: MetadataInfo) -> None:
    file['TIT2'] = id3.TIT2(encoding=3, text=meta.title)
    file['TPE1'] = id3.TPE1(encoding=3, text=meta.artist)

    if meta.description:
        file['COMM'] = id3.COMM(encoding=3, lang='ENG', text=meta.description)

    if meta.genre:
        file['TCON'] = id3.TCON(encoding=3, text=meta.genre)

    if meta.link:
        file['WOAS'] = id3.WOAS(url=meta.link)

    if meta.date:
        file['TDAT'] = id3.TDAT(encoding=3, text=meta.date)

    if meta.album_title:
        file['TALB'] = id3.TALB(encoding=3, text=meta.album_title)

    if meta.album_author:
        file['TPE2'] = id3.TPE2(encoding=3, text=meta.album_author)

    if meta.album_track_num is not None:
        file['TRCK'] = id3.TRCK(encoding=3, text=str(meta.album_track_num))

    if meta.artwork_jpeg:
        file['APIC'] = _get_apic(meta.artwork_jpeg)


T = TypeVar('T')
METADATA_ASSEMBLERS: MappingProxyType[Type[T], Callable[[T, MetadataInfo], None]] = MappingProxyType({
    flac.FLAC: _assemble_flac,
    oggopus.OggOpus: _assemble_opus,
    wave.WAVE: _assemble_wav_or_mp3,
    mp3.MP3: _assemble_wav_or_mp3,
})

