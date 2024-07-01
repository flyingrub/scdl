#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

"""scdl allows you to download music from Soundcloud

Usage:
    scdl (-l <track_url> | me) [-a | -f | -C | -t | -p | -r][-c | --force-metadata]
    [-n <maxtracks>][-o <offset>][--hidewarnings][--debug | --error][--path <path>]
    [--addtofile][--addtimestamp][--onlymp3][--hide-progress][--min-size <size>]
    [--max-size <size>][--remove][--no-album-tag][--no-playlist-folder]
    [--download-archive <file>][--sync <file>][--extract-artist][--flac][--original-art]
    [--original-name][--original-metadata][--no-original][--only-original]
    [--name-format <format>][--strict-playlist][--playlist-name-format <format>]
    [--client-id <id>][--auth-token <token>][--overwrite][--no-playlist][--opus]
    
    scdl -h | --help
    scdl --version


Options:
    -h --help                       Show this screen
    --version                       Show version
    -l [url]                        URL can be track/playlist/user
    -n [maxtracks]                  Download the n last tracks of a playlist according to the creation date
    -a                              Download all tracks of user (including reposts)
    -t                              Download all uploads of a user (no reposts)
    -f                              Download all favorites (likes) of a user
    -C                              Download all tracks commented on by a user
    -p                              Download all playlists of a user
    -r                              Download all reposts of user
    -c                              Continue if a downloaded file already exists
    --force-metadata                This will set metadata on already downloaded track
    -o [offset]                     Start downloading a playlist from the [offset]th track (starting with 1)
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
    --remove                        Remove any files not downloaded from execution
    --sync [file]                   Compares an archive file to a playlist and downloads/removes any changed tracks
    --flac                          Convert original files to .flac. Only works if the original file is lossless quality
    --no-album-tag                  On some player track get the same cover art if from the same album, this prevent it
    --original-art                  Download original cover art, not just 500x500 JPEG
    --original-name                 Do not change name of original file downloads
    --original-metadata             Do not change metadata of original file downloads
    --no-original                   Do not download original file; only mp3, m4a, or opus
    --only-original                 Only download songs with original file available
    --name-format [format]          Specify the downloaded file name format
    --playlist-name-format [format] Specify the downloaded file name format, if it is being downloaded as part of a playlist
    --client-id [id]                Specify the client_id to use
    --auth-token [token]            Specify the auth token to use
    --overwrite                     Overwrite file if it already exists
    --strict-playlist               Abort playlist downloading if one track fails to download
    --no-playlist                   Skip downloading playlists
    --opus                          Prefer downloading opus streams over mp3 streams
"""

import atexit
import asyncio
import configparser
import contextlib
import io
import itertools
import logging
import math
import mimetypes
import queue
import threading
from typing import List, Optional, TypedDict, Tuple, IO, Union

mimetypes.init()

import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
import warnings
from dataclasses import asdict

import filelock
import mutagen
from mutagen.easymp4 import EasyMP4

EasyMP4.RegisterTextKey("website", "purl")

import requests
from docopt import docopt
from pathvalidate import sanitize_filename
from soundcloud import (BasicAlbumPlaylist, BasicTrack, MiniTrack, SoundCloud,
                        Transcoding)
from tqdm import tqdm

from scdl import __version__, utils
from scdl.metadata_assembler import METADATA_ASSEMBLERS, MetadataInfo

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addFilter(utils.ColorizeFilter())

CHUNK_SIZE = 1024

fileToKeep = []

class SoundCloudException(Exception):
    pass

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        logger.error("\nGoodbye!")
    else:
        logger.error("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    sys.exit(1)

sys.excepthook = handle_exception


class PlaylistInfo(TypedDict):
    author: str
    id: int
    title: str

file_lock_dirs: List[pathlib.Path] = []


def clean_up_locks():
    for dir in file_lock_dirs:
        for lock in dir.glob("*.scdl.lock"):
            try:
                lock.unlink(True)
            except Exception:
                pass


atexit.register(clean_up_locks)


def get_filelock(path: pathlib.Path, timeout: int = 10):
    path = pathlib.Path(path)
    path = path.resolve()
    file_lock_dirs.append(path.parent)
    lock_path = str(path) + ".scdl.lock"
    return filelock.FileLock(lock_path, timeout=timeout)


def main():
    """
    Main function, parses the URL from command line arguments
    """

    # exit if ffmpeg not installed
    if not is_ffmpeg_available():
        logger.error("ffmpeg is not installed")
        sys.exit(1)

    # Parse arguments
    arguments = docopt(__doc__, version=__version__)

    if arguments["--debug"]:
        logger.level = logging.DEBUG
    elif arguments["--error"]:
        logger.level = logging.ERROR

    if "XDG_CONFIG_HOME" in os.environ:
        config_file = pathlib.Path(os.environ["XDG_CONFIG_HOME"], "scdl", "scdl.cfg")
    else:
        config_file = pathlib.Path.home().joinpath(".config", "scdl", "scdl.cfg")

    # import conf file
    config = get_config(config_file)

    logger.info("Soundcloud Downloader")
    logger.debug(arguments)

    client_id = arguments["--client-id"] or config["scdl"]["client_id"]
    token = arguments["--auth-token"] or config["scdl"]["auth_token"]

    client = SoundCloud(client_id, token if token else None)

    if not client.is_client_id_valid():
        if arguments["--client-id"]:
            logger.warning(f"Invalid client_id specified by --client-id argument. Using a dynamically generated client_id...")
        elif config["scdl"]["client_id"]:
            logger.warning(f"Invalid client_id in {config_file}. Using a dynamically generated client_id...")
        else:
            logger.info(f"Generating dynamic client_id")
        client = SoundCloud(None, token if token else None)
        if not client.is_client_id_valid():
            logger.error("Dynamically generated client_id is not valid")
            sys.exit(1)
        config["scdl"]["client_id"] = client.client_id
        # save client_id
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with get_filelock(config_file):
            with open(config_file, "w", encoding="UTF-8") as f:
                config.write(f)

    if (token or arguments["me"]) and not client.is_auth_token_valid():
        if arguments["--auth-token"]:
            logger.error(f"Invalid auth_token specified by --auth-token argument")
        else:
            logger.error(f"Invalid auth_token in {config_file}")
        sys.exit(1)

    if arguments["-o"] is not None:
        try:
            arguments["--offset"] = int(arguments["-o"]) - 1
            if arguments["--offset"] < 0:
                raise ValueError()
        except Exception:
            logger.error("Offset should be a positive integer...")
            sys.exit(1)
        logger.debug("offset: %d", arguments["--offset"])

    if arguments["--min-size"] is not None:
        try:
            arguments["--min-size"] = utils.size_in_bytes(arguments["--min-size"])
        except Exception:
            logger.exception(
                "Min size should be an integer with a possible unit suffix"
            )
            sys.exit(1)
        logger.debug("min-size: %d", arguments["--min-size"])

    if arguments["--max-size"] is not None:
        try:
            arguments["--max-size"] = utils.size_in_bytes(arguments["--max-size"])
        except Exception:
            logger.error("Max size should be an integer with a possible unit suffix")
            sys.exit(1)
        logger.debug("max-size: %d", arguments["--max-size"])

    if arguments["--hidewarnings"]:
        warnings.filterwarnings("ignore")

    if not arguments["--name-format"]:
        arguments["--name-format"] = config["scdl"]["name_format"]

    if not arguments["--playlist-name-format"]:
        arguments["--playlist-name-format"] = config["scdl"]["playlist_name_format"]

    if arguments["me"]:
        # set url to profile associated with auth token
        arguments["-l"] = client.get_me().permalink_url

    arguments["-l"] = validate_url(client, arguments["-l"])

    if arguments["--download-archive"]:
        try:
            path = pathlib.Path(arguments["--download-archive"]).resolve()
            arguments["--download-archive"] = path
        except Exception:
            logger.error(
                f"Invalid download archive file {arguments['--download-archive']}"
            )
            sys.exit(1)

    if arguments["--sync"]:
        try:
            path = pathlib.Path(arguments["--sync"]).resolve()
            arguments["--download-archive"] = path
            arguments["--sync"] = path
        except Exception:
            logger.error(f"Invalid sync archive file {arguments['--sync']}")
            sys.exit(1)

    # convert arguments dict to python_args (kwargs-friendly args)
    python_args = {}
    for key, value in arguments.items():
        key = key.strip("-").replace("-", "_")
        python_args[key] = value

    # change download path
    path = arguments["--path"] or config["scdl"]["path"]
    if os.path.exists(path):
        os.chdir(path)
    else:
        if arguments["--path"]:
            logger.error(f"Invalid download path '{path}' specified by --path argument")
        else:
            logger.error(f"Invalid download path '{path}' in {config_file}")
        sys.exit(1)
    logger.debug("Downloading to " + os.getcwd() + "...")

    download_url(client, **python_args)

    if arguments["--remove"]:
        remove_files()


def validate_url(client: SoundCloud, url: str):
    """
    If url is a valid soundcloud.com url, return it.
    Otherwise, try to fix the url so that it is valid.
    If it cannot be fixed, exit the program.
    """
    if url.startswith("https://m.soundcloud.com") or url.startswith("http://m.soundcloud.com") or url.startswith("m.soundcloud.com"):
        url = url.replace("m.", "", 1)
    if url.startswith("https://www.soundcloud.com") or url.startswith("http://www.soundcloud.com") or url.startswith("www.soundcloud.com"):
        url = url.replace("www.", "", 1)
    if url.startswith("soundcloud.com"):
        url = "https://" + url
    if url.startswith("https://soundcloud.com") or url.startswith("http://soundcloud.com"):
        url = urllib.parse.urljoin(url, urllib.parse.urlparse(url).path)
        return url
    
    # see if link redirects to soundcloud.com
    try:
        resp = requests.get(url)
        if url.startswith("https://soundcloud.com") or url.startswith("http://soundcloud.com"):
            return urllib.parse.urljoin(resp.url, urllib.parse.urlparse(resp.url).path)
    except Exception:
        # see if given a username instead of url
        if client.resolve(f"https://soundcloud.com/{url}"):
            return f"https://soundcloud.com/{url}"
    
    logger.error("URL is not valid")
    sys.exit(1)

def get_config(config_file: pathlib.Path) -> configparser.ConfigParser:
    """
    Gets config from scdl.cfg
    """
    config = configparser.ConfigParser()

    default_config_file = pathlib.Path(__file__).with_name("scdl.cfg")

    with get_filelock(config_file):
        # load default config first
        config.read_file(open(default_config_file, encoding="UTF-8"))

        # load config file if it exists
        if config_file.exists():
            config.read_file(open(config_file, encoding="UTF-8"))

        # save config to disk
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="UTF-8") as f:
            config.write(f)

    return config


def truncate_str(s: str, length: int) -> str:
    """
    Truncate string to a certain number of bytes using the file system encoding
    """
    encoding = sys.getfilesystemencoding()
    bytes = s.encode(encoding)
    bytes = bytes[:length]
    return bytes.decode(encoding, errors="ignore")


def sanitize_str(
    filename: str,
    ext: str = "",
    replacement_char: str = "�",
    max_length: int = 255,
):
    """
    Sanitizes a string for use as a filename. Does not allow the file to be hidden
    """
    if filename.startswith("."):
        filename = "_" + filename
    if filename.endswith(".") and not ext:
        filename = filename + "_"
    max_filename_length = max_length - len(ext)
    sanitized = sanitize_filename(
        filename, replacement_text=replacement_char, max_len=max_filename_length
    )
    # sanitize_filename truncates incorrectly, use our own method
    sanitized = truncate_str(sanitized, max_filename_length)
    return sanitized + ext


def download_url(client: SoundCloud, **kwargs):
    """
    Detects if a URL is a track or a playlist, and parses the track(s)
    to the track downloader
    """
    url = kwargs.get("l")
    item = client.resolve(url)
    logger.debug(item)
    offset = kwargs.get("offset", 0)
    if not item:
        logger.error("URL is not valid")
        sys.exit(1)
    elif item.kind == "track":
        logger.info("Found a track")
        download_track(client, item, **kwargs)
    elif item.kind == "playlist":
        logger.info("Found a playlist")
        download_playlist(client, item, playlist_offset=offset, **kwargs)
    elif item.kind == "user":
        user = item
        logger.info("Found a user profile")
        if kwargs.get("f"):
            logger.info(f"Retrieving all likes of user {user.username}...")
            resources = client.get_user_likes(user.id, limit=1000)
            for i, like in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"like n°{i} of {user.likes_count}")
                if hasattr(like, "track"):
                    download_track(client, like.track, exit_on_fail=kwargs.get("strict_playlist"), **kwargs)
                elif hasattr(like, "playlist"):
                    download_playlist(client, client.get_playlist(like.playlist.id), **kwargs)
                else:
                    logger.error(f"Unknown like type {like}")
                    if kwargs.get("strict_playlist"):
                        sys.exit(1)
            logger.info(f"Downloaded all likes of user {user.username}!")
        elif kwargs.get("C"):
            logger.info(f"Retrieving all commented tracks of user {user.username}...")
            resources = client.get_user_comments(user.id, limit=1000)
            for i, comment in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"comment n°{i} of {user.comments_count}")
                download_track(client, client.get_track(comment.track.id), exit_on_fail=kwargs.get("strict_playlist"), **kwargs)
            logger.info(f"Downloaded all commented tracks of user {user.username}!")
        elif kwargs.get("t"):
            logger.info(f"Retrieving all tracks of user {user.username}...")
            resources = client.get_user_tracks(user.id, limit=1000)
            for i, track in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"track n°{i} of {user.track_count}")
                download_track(client, track, exit_on_fail=kwargs.get("strict_playlist"), **kwargs)
            logger.info(f"Downloaded all tracks of user {user.username}!")
        elif kwargs.get("a"):
            logger.info(f"Retrieving all tracks & reposts of user {user.username}...")
            resources = client.get_user_stream(user.id, limit=1000)
            for i, item in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"item n°{i} of {user.track_count + user.reposts_count if user.reposts_count else '?'}")
                if item.type in ("track", "track-repost"):
                    download_track(client, item.track, exit_on_fail=kwargs.get("strict_playlist"), **kwargs)
                elif item.type in ("playlist", "playlist-repost"):
                    download_playlist(client, item.playlist, **kwargs)
                else:
                    logger.error(f"Unknown item type {item.type}")
                    if kwargs.get("strict_playlist"):
                        sys.exit(1)
            logger.info(f"Downloaded all tracks & reposts of user {user.username}!")
        elif kwargs.get("p"):
            logger.info(f"Retrieving all playlists of user {user.username}...")
            resources = client.get_user_playlists(user.id, limit=1000)
            for i, playlist in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"playlist n°{i} of {user.playlist_count}")
                download_playlist(client, playlist, **kwargs)
            logger.info(f"Downloaded all playlists of user {user.username}!")
        elif kwargs.get("r"):
            logger.info(f"Retrieving all reposts of user {user.username}...")
            resources = client.get_user_reposts(user.id, limit=1000)
            for i, item in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"item n°{i} of {user.reposts_count or '?'}")
                if item.type == "track-repost":
                    download_track(client, item.track, exit_on_fail=kwargs.get("strict_playlist"), **kwargs)
                elif item.type == "playlist-repost":
                    download_playlist(client, item.playlist, **kwargs)
                else:
                    logger.error(f"Unknown item type {item.type}")
                    if kwargs.get("strict_playlist"):
                        sys.exit(1)
            logger.info(f"Downloaded all reposts of user {user.username}!")
        else:
            logger.error("Please provide a download type...")
            sys.exit(1)
    else:
        logger.error(f"Unknown item type {item.kind}")
        sys.exit(1)

def remove_files():
    """
    Removes any pre-existing tracks that were not just downloaded
    """
    logger.info("Removing local track files that were not downloaded...")
    files = [f for f in os.listdir(".") if os.path.isfile(f)]
    for f in files:
        if f not in fileToKeep:
            os.remove(f)


def sync(
    client: SoundCloud,
    playlist: BasicAlbumPlaylist,
    playlist_info: PlaylistInfo,
    **kwargs,
):
    """
    Downloads/Removes tracks that have been changed on playlist since last archive file
    """
    logger.info("Comparing tracks...")
    archive = kwargs.get("sync")
    with get_filelock(archive):
        with open(archive) as f:
            try:
                old = [int(i) for i in "".join(f.readlines()).strip().split("\n")]
            except IOError as ioe:
                logger.error(f"Error trying to read download archive {archive}")
                logger.debug(ioe)
                sys.exit(1)
            except ValueError as verr:
                logger.error(
                    f"Error trying to convert track ids. Verify archive file is not empty."
                )
                logger.debug(verr)
                sys.exit(1)

        new = [track.id for track in playlist.tracks]
        add = set(new).difference(old)  # find tracks to download
        rem = set(old).difference(new)  # find tracks to remove

        if not (add or rem):
            logger.info("No changes found. Exiting...")
            sys.exit(0)

        if rem:
            for track_id in rem:
                removed = False
                for ext in (".mp3", ".m4a", ".opus", ".flac", ".wav"):
                    filename = get_filename(
                        client.get_track(track_id),
                        ext,
                        playlist_info=playlist_info,
                        **kwargs,
                    )
                    if filename in os.listdir("."):
                        removed = True
                        os.remove(filename)
                        logger.info(f"Removed {filename}")
                if not removed:
                    logger.info(f"Could not find {filename} to remove")
            with open(archive, "w") as f:
                for track_id in old:
                    if track_id not in rem:
                        f.write(str(track_id) + "\n")
        else:
            logger.info("No tracks to remove.")

        if add:
            return [track for track in playlist.tracks if track.id in add]
        else:
            logger.info("No tracks to download. Exiting...")
            sys.exit(0)


def download_playlist(client: SoundCloud, playlist: BasicAlbumPlaylist, **kwargs):
    """
    Downloads a playlist
    """
    if kwargs.get("no_playlist"):
        logger.info("Skipping playlist...")
        return
    playlist_name = playlist.title.encode("utf-8", "ignore")
    playlist_name = playlist_name.decode("utf-8")
    playlist_name = sanitize_str(playlist_name)
    playlist_info = {
                "author": playlist.user.username,
                "id": playlist.id,
                "title": playlist.title
    }

    if not kwargs.get("no_playlist_folder"):
        if not os.path.exists(playlist_name):
            os.makedirs(playlist_name)
        os.chdir(playlist_name)

    try:
        if kwargs.get("n"):  # Order by creation date and get the n lasts tracks
            playlist.tracks.sort(
                key=lambda track: track.id, reverse=True
            )
            playlist.tracks = playlist.tracks[: int(kwargs.get("n"))]
            kwargs["playlist_offset"] = 0
        if kwargs.get("sync"):
            if os.path.isfile(kwargs.get("sync")):
                playlist.tracks = sync(client, playlist, playlist_info, **kwargs)
            else:
                logger.error(f'Invalid sync archive file {kwargs.get("sync")}')
                sys.exit(1)

        tracknumber_digits = len(str(len(playlist.tracks)))
        for counter, track in itertools.islice(enumerate(playlist.tracks, 1), kwargs.get("playlist_offset", 0), None):
            logger.debug(track)
            logger.info(f"Track n°{counter}")
            playlist_info["tracknumber"] = str(counter).zfill(tracknumber_digits)
            if isinstance(track, MiniTrack):
                if playlist.secret_token:
                    track = client.get_tracks([track.id], playlist.id, playlist.secret_token)[0]
                else:
                    track = client.get_track(track.id)

            download_track(client, track, playlist_info, kwargs.get("strict_playlist"), **kwargs)
    finally:
        if not kwargs.get("no_playlist_folder"):
            os.chdir("..")


def try_utime(path, filetime):
    try:
        os.utime(path, (time.time(), filetime))
    except Exception:
        logger.error("Cannot update utime of file")


def is_downloading_to_stdout(**kwargs) -> bool:
    return kwargs.get('name_format') == '-'


def get_stdout():
    # Credits: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/utils/_utils.py#L575
    if sys.platform == 'win32':
        import msvcrt

        # stdout may be any IO stream, e.g. when using contextlib.redirect_stdout
        with contextlib.suppress(io.UnsupportedOperation):
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    return getattr(sys.stdout, 'buffer', sys.stdout)


def get_filename(
    track: BasicTrack,
    ext: Optional[str] = None,
    original_filename: Optional[str] = None,
    playlist_info: Optional[PlaylistInfo] = None,
    **kwargs,
):
    # Force stdout name on tracks that are being downloaded to stdout
    if is_downloading_to_stdout(**kwargs):
        return 'stdout'

    username = track.user.username
    title = track.title.encode("utf-8", "ignore").decode("utf-8")

    if kwargs.get("addtofile"):
        if username not in title and "-" not in title:
            title = "{0} - {1}".format(username, title)
            logger.debug('Adding "{0}" to filename'.format(username))

    timestamp = str(int(track.created_at.timestamp()))
    if kwargs.get("addtimestamp"):
        title = timestamp + "_" + title

    if not kwargs.get("addtofile") and not kwargs.get("addtimestamp"):
        if playlist_info:
            title = kwargs.get("playlist_name_format").format(**asdict(track), playlist=playlist_info, timestamp=timestamp)
        else:
            title = kwargs.get("name_format").format(**asdict(track), timestamp=timestamp)

    if original_filename is not None:
        original_filename = original_filename.encode("utf-8", "ignore").decode("utf-8")
        ext = os.path.splitext(original_filename)[1]
    filename = sanitize_str(title, ext)
    return filename


def download_original_file(
    client: SoundCloud,
    track: BasicTrack,
    title: str,
    playlist_info: Optional[PlaylistInfo] = None,
    **kwargs,
) -> Tuple[Optional[str], bool]:
    logger.info("Downloading the original file.")
    to_stdout = is_downloading_to_stdout(**kwargs)

    # Get the requests stream
    url = client.get_track_original_download(track.id, track.secret_token)

    if not url:
        logger.info("Could not get original download link")
        return None, False

    r = requests.get(url, stream=True)
    if r.status_code == 401:
        logger.info("The original file has no download left.")
        return None, False

    if r.status_code == 404:
        logger.info("Could not get name from stream - using basic name")
        return None, False

    # Find filename
    header = r.headers.get("content-disposition")
    params = utils.parse_header(header)
    if "filename" in params:
        filename = urllib.parse.unquote(params["filename"][-1], encoding="utf-8")
    else:
        raise SoundCloudException(f"Could not get filename from content-disposition header: {header}")

    orig_filename = filename
    _, ext = os.path.splitext(filename)

    if not kwargs.get("original_name"):
        orig_filename, ext = os.path.splitext(filename)

        # Find file extension
        mime = r.headers.get("content-type")
        ext = ext or mimetypes.guess_extension(mime)
        ext = ext or ("." + r.headers.get("x-amz-meta-file-type"))
        orig_filename += ext

        filename = get_filename(
            track, original_filename=orig_filename, playlist_info=playlist_info, **kwargs
        )

    logger.debug(f"filename : {filename}")
    encoding_to_flac = bool(kwargs.get("flac")) and can_convert(orig_filename)

    if encoding_to_flac:
        filename = filename[:-4] + ".flac"

    # Skip if file ID or filename already exists
    # We are always re-downloading to stdout
    if not to_stdout and already_downloaded(track, title, filename, **kwargs):
        return filename, True

    re_encode_to_out(
        track,
        r,
        ext[1:] if not encoding_to_flac else 'flac',
        filename,
        skip_re_encoding=not encoding_to_flac,
        **kwargs,
    )

    return filename, False


def get_transcoding_m3u8(client: SoundCloud, transcoding: Transcoding, **kwargs):
    url = transcoding.url
    bitrate_KBps = 256 / 8 if "aac" in transcoding.preset else 128 / 8
    total_bytes = bitrate_KBps * transcoding.duration

    min_size = kwargs.get("min_size") or 0
    max_size = kwargs.get("max_size") or math.inf # max size of 0 treated as no max size

    if not min_size <= total_bytes <= max_size:
        raise SoundCloudException("File not within --min-size and --max-size bounds")

    if url is not None:
        headers = client._get_default_headers()
        if client.auth_token:
            headers["Authorization"] = f"OAuth {client.auth_token}"
        r = requests.get(url, params={"client_id": client.client_id}, headers=headers)
        logger.debug(r.url)
        return r.json()["url"]


def download_hls(
    client: SoundCloud,
    track: BasicTrack,
    title: str,
    playlist_info: Optional[PlaylistInfo] = None,
    **kwargs,
) -> Tuple[Optional[str], bool]:
    if not track.media.transcodings:
        raise SoundCloudException(f"Track {track.permalink_url} has no transcodings available")

    logger.debug(f"Transcodings: {track.media.transcodings}")

    transcodings = [t for t in track.media.transcodings if t.format.protocol == "hls"]
    to_stdout = is_downloading_to_stdout(**kwargs)

    # ordered in terms of preference best -> worst
    valid_presets = [("mp3", ".mp3")]

    if not kwargs.get("onlymp3"):
        if kwargs.get("opus"):
            valid_presets = [("opus", ".opus")] + valid_presets
        valid_presets = [("aac", ".m4a")] + valid_presets

    transcoding = None
    ext = None
    for preset_name, preset_ext in valid_presets:
        for t in transcodings:
            if t.preset.startswith(preset_name):
                transcoding = t
                ext = preset_ext
        if transcoding:
            break
    else:
        raise SoundCloudException(
            f"Could not find valid transcoding. Available transcodings: {[t.preset for t in track.media.transcodings if t.format.protocol == 'hls']}"
        )

    filename = get_filename(track, ext=ext, playlist_info=playlist_info, **kwargs)
    logger.debug(f"filename : {filename}")
    # Skip if file ID or filename already exists
    if not to_stdout and already_downloaded(track, title, filename, **kwargs):
        return filename, True

    # Get the requests stream
    url = get_transcoding_m3u8(client, transcoding, **kwargs)
    _, ext = os.path.splitext(filename)

    re_encode_to_out(
        track,
        url,
        preset_name,
        filename,
        playlist_info,
        **kwargs,
    )

    return filename, False


def download_track(
    client: SoundCloud,
    track: BasicTrack,
    playlist_info: Optional[PlaylistInfo] = None,
    exit_on_fail=True,
    **kwargs,
):
    """
    Downloads a track
    """
    try:
        title = track.title
        title = title.encode("utf-8", "ignore").decode("utf-8")
        logger.info(f"Downloading {title}")

        # Not streamable
        if not track.streamable:
            logger.warning("Track is not streamable...")

        # Geoblocked track
        if track.policy == "BLOCK":
            raise SoundCloudException(f"{title} is not available in your location...")

        # Get user_id from the client
        client_user_id = client.get_me().id if client.auth_token else None

        lock = get_filelock(pathlib.Path(f"./{track.id}"), 0)

        # Downloadable track
        downloaded_original = False
        filename = None
        is_already_downloaded = False
        if (
            (track.downloadable or track.user_id == client_user_id)
            and not kwargs["onlymp3"]
            and not kwargs.get("no_original")
            and client.auth_token
        ):
            try:
                with lock:
                    filename, is_already_downloaded = download_original_file(
                        client, track, title, playlist_info, **kwargs
                    )
                downloaded_original = True
            except filelock.Timeout:
                logger.debug(f"Could not acquire lock: {lock}. Skipping")
                return

        if filename is None:
            if kwargs.get("only_original"):
                raise SoundCloudException(f'Track "{track.permalink_url}" does not have original file available. Not downloading...')
            try:
                with lock:
                    filename, is_already_downloaded = download_hls(
                        client, track, title, playlist_info, **kwargs
                    )
            except filelock.Timeout:
                logger.debug(f"Could not acquire lock: {lock}. Skipping")
                return

        if kwargs.get("remove"):
            fileToKeep.append(filename)

        record_download_archive(track, **kwargs)

        to_stdout = is_downloading_to_stdout(**kwargs)

        # Skip if file ID or filename already exists
        if is_already_downloaded and not kwargs.get("force_metadata"):
            raise SoundCloudException(f"{filename} already downloaded.")

        # If file does not exist an error occurred
        # If we are downloading to stdout and reached this point, then most likely we downloaded the track
        if not os.path.isfile(filename) and not to_stdout:
            raise SoundCloudException(f"An error occurred downloading {filename}.")

        # Add metadata to an already existing file if needed
        if is_already_downloaded and kwargs.get('force_metadata'):
            with open(filename, 'rb') as f:
                file_data = io.BytesIO(f.read())

            _add_metadata_to_stream(track, file_data, playlist_info, **kwargs)

            with open(filename, 'wb') as f:
                file_data.seek(0)
                f.write(file_data.read())

        # Try to change the real creation date
        if not to_stdout:
            filetime = int(time.mktime(track.created_at.timetuple()))
            try_utime(filename, filetime)

        logger.info(f"{filename} Downloaded.\n")
    except SoundCloudException as err:
        logger.error(err)
        if exit_on_fail:
            sys.exit(1)


def can_convert(filename):
    ext = os.path.splitext(filename)[1]
    return "wav" in ext or "aif" in ext


def already_downloaded(track: BasicTrack, title: str, filename: str, **kwargs):
    """
    Returns True if the file has already been downloaded
    """
    already_downloaded = False

    if os.path.isfile(filename):
        already_downloaded = True
    if (
        kwargs.get("flac")
        and can_convert(filename)
        and os.path.isfile(filename[:-4] + ".flac")
    ):
        already_downloaded = True
    if kwargs.get("download_archive") and in_download_archive(track, **kwargs):
        already_downloaded = True

    if kwargs.get("flac") and can_convert(filename) and os.path.isfile(filename):
        already_downloaded = False

    if kwargs.get("overwrite"):
        already_downloaded = False

    if already_downloaded:
        if kwargs.get("c") or kwargs.get("remove") or kwargs.get("force_metadata"):
            return True
        else:
            logger.error(f'Track "{title}" already exists!')
            logger.error("Exiting... (run again with -c to continue)")
            sys.exit(1)
    return False


def in_download_archive(track: BasicTrack, **kwargs):
    """
    Returns True if a track_id exists in the download archive
    """
    archive_filename = kwargs.get("download_archive")
    if not archive_filename:
        return

    try:
        with get_filelock(archive_filename):
            with open(archive_filename, "a+", encoding="utf-8") as file:
                file.seek(0)
                track_id = str(track.id)
                for line in file:
                    if line.strip() == track_id:
                        return True
    except IOError as ioe:
        logger.error("Error trying to read download archive...")
        logger.error(ioe)

    return False


def record_download_archive(track: BasicTrack, **kwargs):
    """
    Write the track_id in the download archive
    """
    archive_filename = kwargs.get("download_archive")
    if not archive_filename:
        return

    try:
        with get_filelock(archive_filename):
            with open(archive_filename, "a", encoding="utf-8") as file:
                file.write(f"{track.id}\n")
    except IOError as ioe:
        logger.error("Error trying to write to download archive...")
        logger.error(ioe)


def _try_get_artwork(url: str, size: str = 'original') -> Optional[requests.Response]:
    new_artwork_url = url.replace("large", size)

    try:
        artwork_response = requests.get(new_artwork_url, allow_redirects=False, timeout=5)

        if artwork_response.status_code != 200:
            return None

        content_type = artwork_response.headers.get('Content-Type', '').lower()
        if content_type not in ('image/png', 'image/jpeg', 'image/jpg'):
            return None

        return artwork_response
    except requests.RequestException:
        return None


def build_ffmpeg_encoding_args(
    input_file: str,
    output_file: str,
    out_codec: str,
) -> List[str]:
    return [
        'ffmpeg',

        # Disable all the useless stuff
        '-loglevel', 'error',
        '-hide_banner',

        # Input stream
        '-i', input_file,

        # Encoding
        '-f', out_codec,

        # Progress to stderr
        '-progress', 'pipe:2',
        '-stats_period', '0.1',

        # Output file
        output_file
    ]


async def _write_streaming_response_to_pipe(
    response: requests.Response,
    pipe: Union[asyncio.StreamWriter, io.BytesIO],
    **kwargs,
) -> None:
    total_length = int(response.headers.get("content-length"))

    min_size = kwargs.get("min_size") or 0
    max_size = kwargs.get("max_size") or math.inf  # max size of 0 treated as no max size

    if not min_size <= total_length <= max_size:
        raise SoundCloudException("File not within --min-size and --max-size bounds")

    logger.info('Receiving the streaming response')
    received = 0
    chunk_size = 8192

    loop = asyncio.get_event_loop()

    with memoryview(bytearray(chunk_size)) as buffer:
        for chunk in tqdm(
            iter(lambda: response.raw.read(chunk_size), b''),
            total=(total_length / chunk_size) + 1,
            disable=bool(kwargs.get('hide_progress')),
            unit='Kb',
            unit_scale=chunk_size / 1024,
        ):
            if not chunk:
                break

            buffer_view = buffer[:len(chunk)]
            buffer_view[:] = chunk

            received += len(chunk)
            if isinstance(pipe, io.BytesIO):
                pipe.write(buffer_view)
            else:
                await loop.run_in_executor(None, pipe.write, buffer_view)

    if received != total_length:
        logger.error("connection closed prematurely, download incomplete")
        sys.exit(1)

    if not isinstance(pipe, io.BytesIO):
        pipe.close()


def _add_metadata_to_stream(
    track: BasicTrack,
    stream: io.BytesIO,
    playlist_info: Optional[PlaylistInfo] = None,
    **kwargs,
) -> None:
    logger.info("Applying metadata...")

    artwork_base_url = track.artwork_url or track.user.avatar_url
    artwork_response = None

    if kwargs.get("original_art"):
        artwork_response = _try_get_artwork(artwork_base_url, 'original')

    if artwork_response is None:
        artwork_response = _try_get_artwork(artwork_base_url, 't500x500')

    artist: str = track.user.username
    if bool(kwargs.get('extract_artist')):
        for dash in {" - ", " − ", " – ", " — ", " ― "}:
            if dash not in track.title:
                continue

            artist_title = track.title.split(dash, maxsplit=1)
            artist = artist_title[0].strip()
            track.title = artist_title[1].strip()
            break

    album_available: bool = playlist_info and not kwargs.get("no_album_tag")

    metadata = MetadataInfo(
        artist=artist,
        title=track.title,
        description=track.description,
        genre=track.genre,
        artwork_jpeg=artwork_response.content if artwork_response else None,
        link=track.permalink_url,
        date=track.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        album_title=playlist_info["title"] if album_available else None,
        album_author=playlist_info["author"] if album_available else None,
        album_track_num=playlist_info["tracknumber"] if album_available else None,
    )

    mutagen_file = mutagen.File(stream)

    handler = METADATA_ASSEMBLERS.get(type(mutagen_file), None)
    if handler is None:
        logger.error(f'Metadata assembling for {type(mutagen_file)} is unsupported. '
                     f'Please create an issue at https://github.com/flyingrub/scdl/issues and we will look into it')
        return

    # Delete all the existing tags and write our own tags
    stream.seek(0)
    mutagen_file.delete(stream)
    handler(mutagen_file, metadata)

    stream.seek(0)
    mutagen_file.save(stream)


def re_encode_to_out(
    track: BasicTrack,
    in_data: Union[requests.Response, str],
    out_codec: str,
    filename: str,
    playlist_info: Optional[PlaylistInfo] = None,
    skip_re_encoding: bool = False,
    **kwargs,
) -> None:
    to_stdout = is_downloading_to_stdout(**kwargs)

    encoded = re_encode_to_buffer(
        track,
        in_data,
        out_codec,
        playlist_info,
        skip_re_encoding,
        **kwargs,
    )

    out_handle = get_stdout() if to_stdout else open(filename, 'wb')
    shutil.copyfileobj(encoded, out_handle)

    if not to_stdout:
        out_handle.close()


def _is_ffmpeg_progress_line(parameters: List[str]):
    return len(parameters) == 2 and parameters[0] in (
        "progress",
        "speed",
        "drop_frames",
        "dup_frames",
        "out_time",
        "out_time_ms",
        "out_time_us",
        "total_size",
        "bitrate",
    )


async def _re_encode_ffmpeg(
    in_data: Union[requests.Response, str],  # streaming response or url
    out_codec: str,
    track_duration_ms: int,
    **kwargs,
) -> io.BytesIO:
    is_url: bool = isinstance(in_data, str)
    logger.info("Creating the ffmpeg pipe...")

    commands = build_ffmpeg_encoding_args(
        input_file=in_data if is_url else '-',
        output_file='pipe:1',
        out_codec=out_codec,
    )

    logger.debug(f"ffmpeg command: {commands}")
    pipe = await asyncio.create_subprocess_exec(
        *commands,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    logger.info('Encoding..')
    errors_output = ''
    stdout = io.BytesIO()

    # A function that reads encoded track to our `stdout` BytesIO object
    async def read_stdout():
        while True:
            data = await pipe.stdout.read(8196)
            if not data:
                break

            stdout.write(data)

    # Read line by line from stderr and put these messages in a queue
    async def read_stderr():
        nonlocal errors_output
        with tqdm(
                total=track_duration_ms / 1000,
                disable=bool(kwargs.get("hide_progress")),
                unit="s"
        ) as progress:
            last_secs = 0
            while True:
                line_bytes = await pipe.stderr.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode('utf-8', errors='ignore')
                parameters = line.split('=', maxsplit=1)
                if not _is_ffmpeg_progress_line(parameters):
                    errors_output += line
                    continue

                if not line.startswith('out_time_ms'):
                    continue

                try:
                    seconds = int(parameters[1]) / 1_000_000
                except ValueError:
                    seconds = 0

                changed = seconds - last_secs
                last_secs = seconds
                progress.update(changed)

            # We are done here
            progress.close()

    tasks = [read_stdout(), read_stderr()]
    if isinstance(in_data, requests.Response):
        tasks.append(_write_streaming_response_to_pipe(in_data, pipe.stdin, **kwargs))

    await asyncio.gather(*tasks)

    # Make sure that process has exited and get its exit code
    await pipe.wait()
    if pipe.returncode != 0:
        raise SoundCloudException(f'FFmpeg error({pipe.returncode}): {errors_output}')

    stdout.seek(0)
    return stdout


def _asyncio_run(coro):
    # There's no asyncio.run in old python versions
    return asyncio.get_event_loop().run_until_complete(coro)


def _copy_stream(
    in_data: requests.Response,  # streaming response or url
    **kwargs,
) -> io.BytesIO:
    result = io.BytesIO()
    _asyncio_run(_write_streaming_response_to_pipe(in_data, result, **kwargs))
    result.seek(0)
    return result


def re_encode_to_buffer(
    track: BasicTrack,
    in_data: Union[requests.Response, str],  # streaming response or url
    out_codec: str,
    playlist_info: Optional[PlaylistInfo] = None,
    skip_re_encoding: bool = False,
    **kwargs,
) -> io.BytesIO:
    if skip_re_encoding and isinstance(in_data, requests.Response):
        encoded_data = _copy_stream(in_data, **kwargs)
    else:
        encoded_data = _asyncio_run(_re_encode_ffmpeg(in_data, out_codec, track.duration, **kwargs))

    # Remove original metadata, add our own, and we are done
    if not kwargs.get("original_metadata"):
        _add_metadata_to_stream(track, encoded_data, playlist_info, **kwargs)

    encoded_data.seek(0)
    return encoded_data


def is_ffmpeg_available():
    """
    Returns true if ffmpeg is available in the operating system
    """
    return shutil.which("ffmpeg") is not None


if __name__ == "__main__":
    main()
