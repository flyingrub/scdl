"""scdl allows you to download music from Soundcloud

Usage:
    scdl (-l <track_url> | -s <search_query> | me) [-a | -f | -C | -t | -p | -r]
    [-c | --force-metadata][-o <offset>][--hidewarnings][--debug | --error]
    [--path <path>][--addtofile][--addtimestamp][--onlymp3][--hide-progress][--min-size <size>]
    [--max-size <size>][--no-album-tag][--no-playlist-folder][--duration-limit <time>]
    [--skip-known-drm]
    [--download-archive <file>][--sync <file>][--extract-artist][--flac][--original-art]
    [--original-name][--original-metadata][--no-original][--only-original]
    [--name-format <format>][--strict-playlist][--playlist-name-format <format>]
    [--client-id <id>][--auth-token <token>][--overwrite][--no-playlist][--opus]
    [--add-description][--yt-dlp-args <argstring>]

    scdl -h | --help
    scdl --version


Options:
    -h --help                       Show this screen
    --version                       Show version
    -l [url]                        URL can be track/playlist/user
    -s [search_query]               Search for a track/playlist/user and use the first result
    -a                              Download all tracks of user (including reposts)
    -t                              Download all uploads of a user (no reposts)
    -f                              Download all favorites (likes) of a user
    -C                              Download all tracks commented on by a user
    -p                              Download all playlists of a user
    -r                              Download all reposts of user
    -c                              Continue if a downloaded file already exists
    --force-metadata                This will set metadata on already downloaded track
    -o [offset]                     Start downloading a playlist from the [offset]th track
                                    Indexing starts with 1.
    --addtimestamp                  Add track creation timestamp to filename,
                                    which allows for chronological sorting
                                    (Deprecated. Use --name-format instead.)
    --addtofile                     Add artist to filename if missing
    --debug                         Set log level to DEBUG
    --error                         Set log level to ERROR
    --download-archive [file]       Keep track of track IDs in an archive file,
                                    and skip already-downloaded files
    --extract-artist                Set artist tag from title instead of username
    --hide-progress                 Hide the wget progress bar
    --hidewarnings                  Hide Warnings. (use with precaution)
    --max-size [max-size]           Skip tracks larger than size (k/m/g)
    --min-size [min-size]           Skip tracks smaller than size (k/m/g)
    --no-playlist-folder            Download playlist tracks into main directory,
                                    instead of making a playlist subfolder
    --onlymp3                       Download only mp3 files
    --path [path]                   Use a custom path for downloaded files
    --sync [file]                   Compares an archive file to a playlist and downloads/removes
                                    any changed tracks
    --flac                          Convert original files to .flac. Only works if the original
                                    file is lossless quality
    --no-album-tag                  On some player track get the same cover art if from the same
                                    album, this prevent it
    --duration-limit [time]         Set an upper limit for duration of a track, e.g. 10:00
    --skip-known-drm                 Skip tracks with no downloadable formats (DRM-protected
                                    or geo-restricted) and remember them, so future runs skip
                                    without re-querying
    --original-art                  Download original cover art, not just 500x500 JPEG
    --original-name                 Do not change name of original file downloads
    --original-metadata             Do not change metadata of original file downloads
    --no-original                   Do not download original file; only mp3, m4a, or opus
    --only-original                 Only download songs with original file available
    --name-format [format]          Specify the downloaded file name format. Use "-" to download
                                    to stdout
    --playlist-name-format [format] Specify the downloaded file name format, if it is being
                                    downloaded as part of a playlist
    --client-id [id]                Specify the client_id to use
    --auth-token [token]            Specify the auth token to use
    --overwrite                     Overwrite file if it already exists
    --strict-playlist               Abort playlist downloading if one track fails to download
    --no-playlist                   Skip downloading playlists
    --add-description               Adds the description to a separate txt file
    --opus                          Prefer downloading opus streams over mp3 streams
    --yt-dlp-args [argstring]       String with custom args to forward to yt-dlp
"""

from __future__ import annotations

import configparser
import importlib
import importlib.metadata
import json
import logging
import os
import posixpath
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from docopt import docopt
from soundcloud import (
    AlbumPlaylist,
    SoundCloud,
    Track,
    User,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import locked_file

from scdl import utils
from scdl.patches.mutagen_postprocessor import MutagenPP
from scdl.patches.original_filename_preprocessor import OriginalFilenamePP
from scdl.patches.switch_outtmpl_preprocessor import OuttmplPP
from scdl.patches.sync_download_archive import SyncDownloadHelper

if TYPE_CHECKING:
    if sys.version_info < (3, 11):
        from typing_extensions import Unpack
    else:
        from typing import Unpack

logging.setLoggerClass(utils.YTLogger)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SCDLArgs(TypedDict):
    C: bool
    a: bool
    add_description: bool
    addtimestamp: bool
    addtofile: bool
    auth_token: str | None
    c: bool
    client_id: str | None
    debug: bool
    download_archive: str | None
    duration_limit: str | None
    skip_known_drm: bool
    error: bool
    extract_artist: bool
    f: bool
    flac: bool
    force_metadata: bool
    hide_progress: bool
    hidewarnings: bool
    l: str  # noqa: E741
    max_size: str | None
    me: bool
    min_size: str | None
    name_format: str
    no_album_tag: bool
    no_original: bool
    no_playlist: bool
    no_playlist_folder: bool
    o: int | None
    only_original: bool
    onlymp3: bool
    opus: bool
    original_art: bool
    original_metadata: bool
    original_name: bool
    overwrite: bool
    p: bool
    path: Path
    playlist_name_format: str
    r: bool
    strict_playlist: bool
    sync: str | None
    s: str | None
    t: bool
    yt_dlp_args: str


__version__ = importlib.metadata.version("scdl")


def _main() -> None:
    """Main function, parses the URL from command line arguments"""
    logger.addHandler(logging.StreamHandler())

    # Parse arguments
    arguments = docopt(__doc__, version=__version__)

    if arguments["--debug"]:
        logger.level = logging.DEBUG
    elif arguments["--error"]:
        logger.level = logging.ERROR

    if "XDG_CONFIG_HOME" in os.environ:
        config_file = Path(os.environ["XDG_CONFIG_HOME"], "scdl", "scdl.cfg")
    else:
        config_file = Path.home().joinpath(".config", "scdl", "scdl.cfg")

    # import conf file
    config = _get_config(config_file)

    logger.info(f"[scdl] SCDL version {__version__}")

    client_id = arguments["--client-id"] or config["scdl"]["client_id"]
    token = arguments["--auth-token"] or config["scdl"]["auth_token"]

    client = SoundCloud(client_id, token if token else None)

    if not client.is_client_id_valid():
        if arguments["--client-id"]:
            logger.warning(
                "[scdl] Invalid client_id specified by --client-id argument. "
                "Using a dynamically generated client_id",
            )
        elif config["scdl"]["client_id"]:
            logger.warning(
                f"[scdl] Invalid client_id in {config_file}. Using a dynamically generated client_id",
            )
        else:
            logger.info("[scdl] Generating dynamic client_id")
        client = SoundCloud(None, token if token else None)
        if not client.is_client_id_valid():
            logger.error("[scdl] Dynamically generated client_id is not valid")
            sys.exit(1)
        config["scdl"]["client_id"] = client.client_id
        arguments["--client-id"] = client.client_id
        # save client_id
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(config_file, "w", encoding="utf-8") as f:
            config.write(f)

    if (token or arguments["me"]) and not client.is_auth_token_valid():
        if arguments["--auth-token"]:
            logger.error("[scdl] Invalid auth_token specified by --auth-token argument")
        else:
            logger.error(f"[scdl] Invalid auth_token in {config_file}")
        sys.exit(1)

    if arguments["-o"] is not None:
        try:
            arguments["-o"] = int(arguments["-o"])
            if arguments["-o"] < 1:
                raise ValueError
        except Exception:
            logger.error("[scdl] Offset should be a positive integer")
            sys.exit(1)

    if not arguments["--name-format"]:
        arguments["--name-format"] = config["scdl"]["name_format"]

    if not arguments["--playlist-name-format"]:
        arguments["--playlist-name-format"] = config["scdl"]["playlist_name_format"]

    if arguments["me"]:
        # set url to profile associated with auth token
        me = client.get_me()
        assert me is not None
        arguments["-l"] = me.permalink_url

    if arguments["-s"]:
        url = _search_soundcloud(client, arguments["-s"])
        if url:
            arguments["-l"] = url
        else:
            logger.error("[scdl] Search failed")
            sys.exit(1)

    arguments["--path"] = Path(arguments["--path"] or config["scdl"]["path"] or ".").resolve()

    # convert arguments dict to python-friendly kwarg names (no hyphens)
    python_args = {}
    for key, value in arguments.items():
        key = key.strip("-").replace("-", "_")
        python_args[key] = value

    python_args["client_id"] = client.client_id
    python_args["auth_token"] = client.auth_token
    url = python_args.pop("l")

    assert url is not None

    download_url(url, **python_args)


def _search_soundcloud(client: SoundCloud, query: str) -> str | None:
    """Search SoundCloud and return the URL of the first result."""
    try:
        results = list(client.search(query, limit=1))
        if results:
            item = results[0]
            logger.info(f"Search resolved to url {item.permalink_url}")
            if isinstance(item, (Track, AlbumPlaylist, User)):
                return item.permalink_url
            logger.warning(f"Unexpected search result type: {type(item)}")
        logger.error(f"No results found for query: {query}")
        return None
    except Exception as e:
        logger.error(f"Error searching SoundCloud: {e}")
        return None




def resolve_time_limit(time_limit: str = "") -> int:
    """Convert HH:MM:SS or MM:SS into seconds."""
    if not time_limit:
        return 0
    return sum(int(x) * 60 ** i for i, x in enumerate(reversed(time_limit.split(":"))))

def _get_config(config_file: Path) -> configparser.RawConfigParser:
    """Gets config from scdl.cfg"""
    config = configparser.RawConfigParser()

    default_config_file = Path(__file__).with_name("scdl.cfg")

    config_file.parent.mkdir(parents=True, exist_ok=True)

    # load default config first
    with open(default_config_file, encoding="utf-8") as f:
        config.read_file(f)

    try:
        with locked_file(config_file, "r", encoding="utf-8") as f:
            config.read_file(f)
    except Exception as err:
        logger.warning(f"Error while reading config file: {err}")

    try:
        with locked_file(config_file, "w", encoding="utf-8") as f:
            config.write(f)
    except Exception as err:
        logger.warning(f"Error while writing config file: {err}")

    return config


def _convert_v2_name_format(s: str) -> str:
    replacements = {
        "{id}": "%(id)s",
        "{user[username]}": "%(uploader)s",
        "{user[id]}": "%(uploader_id)s",
        "{user[permalink_url]}": "%(uploader_url)s",
        "{timestamp}": "%(timestamp)s",
        "{title}": "%(title)s",
        "{description}": "%(description)s",
        "{duration}": "%(duration)s",
        "{permalink_url}": "%(webpage_url)s",
        "{license}": "%(license)s",
        "{playback_count}": "%(view_count)s",
        "{likes_count}": "%(like_count)s",
        "{comment_count}": "%(comment_count)s",
        "{reposts_count}": "%(respost_count)s",
        "{playlist[author]}": "%(playlist_uploader)s",
        "{playlist[title]}": "%(playlist)s",
        "{playlist[id]}": "%(playlist_id)s",
        "{playlist[tracknumber]}": "%(playlist_index)s",
        "{playlist[tracknumber_total]}": "%(playlist_count)s",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    if not s.endswith(".%(ext)s"):
        s += ".%(ext)s"
    return s


def _build_ytdl_output_filename(scdl_args: SCDLArgs, in_playlist: bool, force_suffix: str | None = None) -> str:
    if scdl_args.get("name_format") == "-":
        return "-"

    playlist_format = "%(playlist|)s"
    if in_playlist:
        track_format = _convert_v2_name_format(scdl_args["playlist_name_format"])
    else:
        track_format = _convert_v2_name_format(scdl_args["name_format"])

    if scdl_args.get("addtimestamp") or scdl_args.get("addtofile"):
        track_format = "%(title)s.%(ext)s"
        if scdl_args.get("addtofile"):
            track_format = "%(uploader)s - " + track_format
        if scdl_args.get("addtimestamp"):
            track_format = "%(timestamp)s_" + track_format

    base = scdl_args["path"]
    if scdl_args.get("no_playlist_folder") or not in_playlist:
        ret = base / track_format
    else:
        ret = base / playlist_format / track_format

    if force_suffix:
        ret = ret.with_suffix(force_suffix)

    return ret.as_posix()


def _build_ytdl_format_specifier(scdl_args: SCDLArgs) -> str:
    fmt = "ba"
    if scdl_args.get("min_size"):
        fmt += f"[filesize_approx>={scdl_args['min_size']}]"
    if scdl_args.get("max_size"):
        fmt += f"[filesize_approx<={scdl_args['max_size']}]"
    if scdl_args.get("no_original"):
        fmt += "[format_id!=download]"
    if scdl_args.get("only_original"):
        fmt += "[format_id=download]"
    if scdl_args.get("onlymp3"):
        fmt += "[format_id*=mp3]"
    return fmt


def _build_ytdl_params(url: str, scdl_args: SCDLArgs) -> tuple[str, dict, list]:
    # return download url, ytdl params, and postprocessors

    if scdl_args.get("a"):
        pass
    elif scdl_args.get("t"):
        url = posixpath.join(url, "tracks")
    elif scdl_args.get("f"):
        url = posixpath.join(url, "likes")
    elif scdl_args.get("C"):
        url = posixpath.join(url, "comments")
    elif scdl_args.get("p"):
        url = posixpath.join(url, "sets")
    elif scdl_args.get("r"):
        url = posixpath.join(url, "reposts")

    params: dict = {}

    # default params
    params["--embed-metadata"] = True
    params["--embed-thumbnail"] = True
    params["--remux-video"] = "aac>m4a"
    params["--extractor-args"] = "soundcloud:formats=*_aac,*_mp3"  # ignore opus by default
    params["--use-extractors"] = "soundcloud.*"
    params["--output-na-placeholder"] = ""
    params["--parse-metadata"] = []
    params["--trim-filenames"] = "240b"
    postprocessors = [
        (
            OuttmplPP(
                _build_ytdl_output_filename(scdl_args, False),
                _build_ytdl_output_filename(scdl_args, True),
            ),
            "pre_process",
        )
    ]

    if scdl_args.get("strict_playlist"):
        params["--abort-on-error"] = True

    if not scdl_args.get("c") and not scdl_args.get("download_archive") and not scdl_args.get("sync"):
        params["--break-on-existing"] = True

    # if not scdl_args.get("force_metadata"):
    #     https://github.com/yt-dlp/yt-dlp/issues/1467
    #     params["--no-post-overwrites"] = True  # noqa: ERA001

    if scdl_args.get("o"):
        params["--playlist-items"] = f"{scdl_args.get('o')}:"

    if scdl_args.get("extract_artist"):
        params["--parse-metadata"] += [
            r"%(title)s:(?P<meta_artist>.*?)\s+[-−–—―]\s*(?P<meta_title>.*)",  # noqa: RUF001
        ]

    if scdl_args.get("debug"):
        params["--verbose"] = True

    if scdl_args.get("error"):
        params["--quiet"] = True

    if scdl_args.get("download_archive"):
        params["--download-archive"] = scdl_args.get("download_archive")

    if scdl_args.get("hide_progress"):
        params["--no-progress"] = True

    if scdl_args.get("max_size"):
        params["--max-filesize"] = scdl_args.get("max_size")
    if scdl_args.get("min_size"):
        params["--min-filesize"] = scdl_args.get("min_size")

    params["-f"] = _build_ytdl_format_specifier(scdl_args)

    if scdl_args.get("flac"):
        params["--recode-video"] = "aiff>flac/alac>flac/wav>flac"

    if not scdl_args.get("no_album_tag"):
        params["--parse-metadata"] += [
            "%(playlist)s:%(meta_album)s",
            "%(playlist_uploader)s:%(meta_album_artist)s",
            "%(playlist_index)s:%(meta_track)s",
        ]

    if scdl_args.get("original_name") and not scdl_args.get("no_original"):
        postprocessors.append((OriginalFilenamePP(), "pre_process"))

    if not scdl_args.get("original_art"):
        params["--thumbnail-id"] = "t500x500"

    if scdl_args.get("name_format") == "-":
        # https://github.com/yt-dlp/yt-dlp/issues/8815
        # https://github.com/yt-dlp/yt-dlp/issues/126
        params["--embed-metadata"] = False
        params["--embed-thumbnail"] = False

    if scdl_args.get("original_metadata"):
        params["--embed-metadata"] = False
        params["--embed-thumbnail"] = False
    else:
        postprocessors.append((MutagenPP(scdl_args["force_metadata"]), "post_process"))

    if scdl_args.get("auth_token"):
        params["--username"] = "oauth"
        params["--password"] = scdl_args.get("auth_token")

    if scdl_args.get("overwrite"):
        params["--force-overwrites"] = True

    if scdl_args.get("no_playlist"):
        existing = params.get("--match-filters")
        filt = "!playlist_uploader"
        params["--match-filters"] = f"{existing} & {filt}" if existing else filt

    if scdl_args.get("add_description"):
        params["--print-to-file"] = (
            "description",
            _build_ytdl_output_filename(scdl_args, False, ".txt"),
        )

    if scdl_args.get("opus"):
        params["--extractor-args"] = "soundcloud:formats=*_aac,*_opus,*_mp3"

    argv = []
    for param, value in params.items():
        if value is False:
            continue
        if value is True:
            argv.append(param)
        elif isinstance(value, list):
            for v in value:
                argv.append(param)
                argv.append(v)
        elif isinstance(value, tuple):
            argv.append(param)
            argv += list(value)
        else:
            argv.append(param)
            argv.append(value)

    logger.debug(f"[debug] yt-dlp args: {url} {' '.join(argv)}")

    return url, utils.cli_to_api(argv), postprocessors


def _duration_cache_path(download_archive: str | None) -> Path | None:
    """Sidecar cache for durations, see _fact_cache_path for why it's separate."""
    return _fact_cache_path(download_archive, ".durations.jsonl")


def _fact_cache_path(download_archive: str | None, suffix: str) -> Path | None:
    """Derive a sidecar cache path from --download-archive.

    Deliberately *separate* files from the download archive itself, and from
    each other. The archive means "this file was downloaded"; caching a
    filter rejection there too would mean that dropping or loosening the
    filter on a later run makes tracks look already-downloaded when they
    were never actually fetched. These sidecars instead store plain facts
    (track ID -> some property, e.g. duration or "has no formats") with no
    notion of "should this be skipped" baked in, so any run's filter
    settings get applied freshly against the same cached ground truth, no
    matter what was in effect on previous runs - including no filter at all.
    """
    if not download_archive:
        return None
    return Path(str(download_archive)).with_suffix(suffix)


def _load_fact_cache(path: Path, field: str) -> dict[str, Any]:
    cache: dict[str, Any] = {}
    if not path.exists():
        return cache
    try:
        with locked_file(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    cache[str(entry["id"])] = entry[field]
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        logger.debug(f"Could not read cache at {path}", exc_info=True)
    return cache


def _append_fact_cache(path: Path, track_id: str, field: str, value: Any) -> None:
    try:
        with locked_file(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": track_id, field: value}) + "\n")
    except OSError:
        logger.debug(f"Could not write cache entry for {track_id} at {path}", exc_info=True)


def _compose_match_filters(*filters: Any) -> Any:
    """Chain match_filter callables: first non-None rejection wins, else pass."""
    filters = [f for f in filters if f is not None]
    if not filters:
        return None

    def combined(info_dict: dict, *, incomplete: bool = False) -> str | None:
        for f in filters:
            try:
                result = f(info_dict, incomplete=incomplete)
            except TypeError:
                result = None if incomplete else f(info_dict)
            if result is not None:
                return result
        return None

    return combined


def download_url(url: str, **scdl_args: Unpack[SCDLArgs]) -> None:
    url, params, postprocessors = _build_ytdl_params(url, scdl_args)

    params["logger"] = logger

    # we handle this with custom MutagenPP for now
    params["postprocessors"] = [
        pp for pp in params["postprocessors"] if pp["key"] not in ("EmbedThumbnail", "FFmpegMetadata")
    ]

    yt_dlp_args = scdl_args.get("yt_dlp_args")
    if yt_dlp_args:
        argv = shlex.split(yt_dlp_args)
        overrides = utils.cli_to_api(argv)
        params = {**params, **overrides}

    base_match_filter = params.get("match_filter")
    active_filters = []

    duration_limit = scdl_args.get("duration_limit")
    if duration_limit:
        limit_seconds = resolve_time_limit(duration_limit)
        cache_path = _duration_cache_path(scdl_args.get("download_archive"))
        duration_cache = _load_fact_cache(cache_path, "duration") if cache_path else {}

        def duration_filter(info_dict: dict, *, incomplete: bool = False) -> str | None:
            track_id = info_dict.get("id")
            duration = duration_cache.get(str(track_id)) if track_id is not None else None
            if duration is None:
                # Not cached yet - use whatever this extraction pass knows. If this
                # is the pass that finally resolved it, remember it for next time,
                # regardless of whether it happens to pass *this* run's limit -
                # a future run might use a different --duration-limit (or none),
                # and the cached fact stays correct either way.
                duration = info_dict.get("duration")
                if duration is not None and track_id is not None and cache_path:
                    duration_cache[str(track_id)] = float(duration)
                    _append_fact_cache(cache_path, str(track_id), "duration", float(duration))
            if duration is not None and duration > limit_seconds:
                title = info_dict.get("title") or track_id or "entry"
                return f"{title} duration {duration:.0f}s exceeds --duration-limit ({limit_seconds}s), skipping"
            return None

        active_filters.append(duration_filter)

    if scdl_args.get("skip_known_drm"):
        # --ignore-no-formats-error stops yt-dlp from hard-erroring on tracks with
        # no usable formats (DRM-protected, or geo-restricted - yt-dlp doesn't
        # expose which, both collapse to the same "no formats" signal) and instead
        # returns a normal result with formats=[], which we can filter and cache
        # like duration. Without this, such tracks show up as ERROR lines every
        # single run rather than being skippable at all.
        params["ignore_no_formats_error"] = True
        cache_path = _fact_cache_path(scdl_args.get("download_archive"), ".no_formats.jsonl")
        no_formats_cache = _load_fact_cache(cache_path, "no_formats") if cache_path else {}

        def drm_filter(info_dict: dict, *, incomplete: bool = False) -> str | None:
            track_id = info_dict.get("id")
            if track_id is None:
                return None
            no_formats = no_formats_cache.get(str(track_id))
            if no_formats is None and "formats" in info_dict:
                no_formats = not info_dict.get("formats")
                if cache_path:
                    no_formats_cache[str(track_id)] = no_formats
                    _append_fact_cache(cache_path, str(track_id), "no_formats", no_formats)
            if no_formats:
                title = info_dict.get("title") or track_id or "entry"
                return f"{title} has no downloadable formats (DRM-protected or geo-restricted), skipping"
            return None

        active_filters.append(drm_filter)

    if active_filters:
        params["match_filter"] = _compose_match_filters(*active_filters, base_match_filter)

    with YoutubeDL(params) as ydl:
        if scdl_args["client_id"]:
            ydl.cache.store("soundcloud", "client_id", scdl_args["client_id"])
        for pp, when in postprocessors:
            ydl.add_post_processor(pp, when)

        sync = SyncDownloadHelper(scdl_args, ydl)
        ydl.download(url)
        sync.post_download()


if __name__ == "__main__":
    _main()
