#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

"""scdl allows you to download music from Soundcloud

Usage:
    scdl (-l <track_url> | me) [-a][-r][-t][-f][-C][-p][-c][--force-metadata]
    [-n <maxtracks>][-o <offset>][--hidewarnings][--debug | --error][--path <path>]
    [--addtofile][--addtimestamp][--onlymp3][--hide-progress][--min-size <size>]
    [--max-size <size>][--remove][--no-album-tag][--no-playlist-folder]
    [--download-archive <file>][--sync <file>][--extract-artist][--flac][--original-art]
    [--original-name][--no-original][--only-original][--name-format <format>]
    [--strict-playlist][--playlist-name-format <format>][--client-id <id>]
    [--auth-token <token>][--overwrite][--no-playlist][--playlist-file]
    [--playlist-file-retain][--playlist-file-name][--playlist-file-extension]
    [--playlist-file-cache]
    
    scdl -h | --help
    scdl --version


Options:
    -h --help                       Show this screen
    --version                       Show version
    -l [url]                        URL can be track/playlist/user
    -n [maxtracks]                  Download the n last tracks of a playlist according to the creation date
    -s                              Download the stream of a user (token needed)
    -a                              Download all tracks of user (including reposts)
    -t                              Download all uploads of a user (no reposts)
    -f                              Download all favorites of a user
    -C                              Download all commented by a user
    -p                              Download all playlists of a user
    -r                              Download all reposts of user
    -c                              Continue if a downloaded file already exists
    --force-metadata                This will set metadata on already downloaded track
    -o [offset]                     Begin with a custom offset
    --addtimestamp                  Add track creation timestamp to filename,
                                    which allows for chronological sorting
    --addtofile                     Add artist to filename if missing
    --debug                         Set log level to DEBUG
    --download-archive [file]       Keep track of track IDs in an archive file,
                                    and skip already-downloaded files
    --error                         Set log level to ERROR
    --extract-artist                Set artist tag from title instead of username
    --hide-progress                 Hide the wget progress bar
    --hidewarnings                  Hide Warnings. (use with precaution)
    --max-size [max-size]           Skip tracks larger than size (k/m/g)
    --min-size [min-size]           Skip tracks smaller than size (k/m/g)
    --no-playlist-folder            Download playlist tracks into main directory,
                                    instead of making a playlist subfolder
    --onlymp3                       Download only the streamable mp3 file,
                                    even if track has a Downloadable file
    --path [path]                   Use a custom path for downloaded files
    --remove                        Remove any files not downloaded from execution
    --sync [file]                   Compares an archive file to a playlist and downloads/removes any changed tracks
    --flac                          Convert original files to .flac
    --no-album-tag                  On some player track get the same cover art if from the same album, this prevent it
    --original-art                  Download original cover art
    --original-name                 Do not change name of original file downloads
    --no-original                   Do not download original file; only mp3 or m4a
    --only-original                 Only download songs with original file available
    --name-format [format]          Specify the downloaded file name format
    --playlist-name-format [format] Specify the downloaded file name format, if it is being downloaded as part of a playlist
    --client-id [id]                Specify the client_id to use
    --auth-token [token]            Specify the auth token to use
    --overwrite                     Overwrite file if it already exists
    --strict-playlist               Abort playlist downloading if one track fails to download
    --no-playlist                   Skip downloading playlists
    --playlist-file                 Generate m3u playlist files (and additionally check them when used with --remove)
    --playlist-file-retain          Retain corrupted items
    --playlist-file-name            Specify playlist file name without extension
    --playlist-file-extension       Specify extension to playlist file
    --playlist-file-cache           Skip updates for present files
"""

import cgi
import configparser
import itertools
import logging
import math
import mimetypes

mimetypes.init()

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
import warnings
from dataclasses import asdict

import mutagen
from mutagen.easymp4 import EasyMP4

EasyMP4.RegisterTextKey("website", "purl")

import requests
from clint.textui import progress
from docopt import docopt
from pathvalidate import sanitize_filename
from soundcloud import (BasicAlbumPlaylist, BasicTrack, MiniTrack, SoundCloud,
                        Transcoding)

from scdl import __version__, utils

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addFilter(utils.ColorizeFilter())

fileToKeep = []

class SoundCloudException(Exception):
    pass

class SoundCloudSoftException(Exception):
    pass

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        logger.error("\nGoodbye!")
    else:
        logger.error("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    sys.exit(1)

sys.excepthook = handle_exception

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
            logger.error(f"Invalid client_id specified by --client-id argument. Using a dynamically generated client_id...")
        elif config["scdl"]["client_id"]:
            logger.error(f"Invalid client_id in {config_file}. Using a dynamically generated client_id...")
        client = SoundCloud(None, token if token else None)
        if not client.is_client_id_valid():
            logger.error("Dynamically generated client_id is not valid")
            sys.exit(1)
    
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

    if arguments["--sync"]:
        arguments["--download-archive"] = arguments["--sync"]
        
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
        remove_files(arguments["--playlist-file"] is not None, kwdefget("playlist_file_extension", "m3u8", **python_args))


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

def kwdefget(findkey, defaultvalue, **kwargs):
    if not kwargs.get(findkey): return defaultvalue
    return kwargs.get(findkey)

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
        if not kwargs.get("f") and not kwargs.get("C") and not kwargs.get("t") and not kwargs.get("a") and not kwargs.get("p") and not kwargs.get("r"):
            logger.error("Please provide a download type...")
            sys.exit(1)
        if kwargs.get("f"):
            logger.info(f"Retrieving all likes of user {user.username}...")
            playlistcache=None if not kwargs.get("playlist_file_cache") else playlist_map_read(kwdefget("playlist_file_name", "Likes", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs))
            playlistbuffer=None if not kwargs.get("playlist_file") else []
            subplaylistbuffer=None if not kwargs.get("playlist_file") else []
            resources = client.get_user_likes(user.id, limit=int(kwdefget("n", "1000", **kwargs)))
            ilim=int(kwdefget("n", "-1", **kwargs))
            for i, like in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"like n°{i} of {user.likes_count}")
                if hasattr(like, "track"):
                    download_track_cached(client, like.track, exit_on_fail=kwargs.get("strict_playlist"), playlist_cache=playlistcache, playlist_buffer=playlistbuffer, **kwargs)
                elif hasattr(like, "playlist"):
                    download_playlist(client, client.get_playlist(like.playlist.id), playlist_filename_prefix=kwdefget("playlist_file_name", "Likes", **kwargs) + " - ", subplaylist_buffer=subplaylistbuffer, **kwargs)
                else:
                    logger.error(f"Unknown like type {like}")
                    if kwargs.get("strict_playlist"):
                        sys.exit(1)
                ilim=ilim-1
                if ilim == 0: break
            if kwargs.get("playlist_file"):
                playlist_process(client, playlistbuffer, kwdefget("playlist_file_name", "Likes", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), **kwargs)
                playlist_process(client, subplaylistbuffer, kwdefget("playlist_file_name", "Likes Playlists", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), no_export=True, **kwargs)
            logger.info(f"Downloaded all likes of user {user.username}!")
        if kwargs.get("C"):
            logger.info(f"Retrieving all commented tracks of user {user.username}...")
            playlistcache=None if not kwargs.get("playlist_file_cache") else playlist_map_read(kwdefget("playlist_file_name", "Commented", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs))
            playlistbuffer=None if not kwargs.get("playlist_file") else []
            resources = client.get_user_comments(user.id, limit=1000)
            for i, comment in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"comment n°{i} of {user.comments_count}")
                download_track_cached(client, client.get_track(comment.track.id), exit_on_fail=kwargs.get("strict_playlist"), playlist_cache=playlistcache, playlist_buffer=playlistbuffer, **kwargs)
            if kwargs.get("playlist_file"): playlist_process(client, playlistbuffer, kwdefget("playlist_file_name", "Commented", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), **kwargs)
            logger.info(f"Downloaded all commented tracks of user {user.username}!")
        if kwargs.get("t"):
            logger.info(f"Retrieving all tracks of user {user.username}...")
            playlistbuffer=None if not kwargs.get("playlist_file") else []
            playlistcache=None if not kwargs.get("playlist_file_cache") else playlist_map_read(kwdefget("playlist_file_name", "Tracks", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs))
            resources = client.get_user_tracks(user.id, limit=1000)
            for i, track in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"track n°{i} of {user.track_count}")
                download_track_cached(client, track, exit_on_fail=kwargs.get("strict_playlist"), playlist_cache=playlistcache, playlist_buffer=playlistbuffer, **kwargs)
            if kwargs.get("playlist_file"): playlist_process(client, playlistbuffer, kwdefget("playlist_file_name", "Tracks", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), **kwargs)
            logger.info(f"Downloaded all tracks of user {user.username}!")
        if kwargs.get("a"):
            logger.info(f"Retrieving all tracks & reposts of user {user.username}...")
            playlistcache=None if not kwargs.get("playlist_file_cache") else playlist_map_read(kwdefget("playlist_file_name", "Stream", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs))
            playlistbuffer=None if not kwargs.get("playlist_file") else []
            subplaylistbuffer=None if not kwargs.get("playlist_file") else []
            resources = client.get_user_stream(user.id, limit=1000)
            for i, item in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"item n°{i} of {user.track_count + user.reposts_count if user.reposts_count else '?'}")
                if item.type in ("track", "track-repost"):
                    download_track_cached(client, item.track, exit_on_fail=kwargs.get("strict_playlist"), playlist_cache=playlistcache, playlist_buffer=playlistbuffer, **kwargs)
                elif item.type in ("playlist", "playlist-repost"):
                    download_playlist(client, item.playlist, kwdefget("playlist_file_name", "Stream", **kwargs) + " - ", subplaylist_buffer=subplaylistbuffer, **kwargs)
                else:
                    logger.error(f"Unknown item type {item.type}")
                    if kwargs.get("strict_playlist"):
                        sys.exit(1)
            if kwargs.get("playlist_file"):
                playlist_process(client, playlistbuffer, kwdefget("playlist_file_name", "Stream", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), **kwargs)
                playlist_process(client, subplaylistbuffer, kwdefget("playlist_file_name", "Stream Playlists", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), no_export=True, **kwargs)
            logger.info(f"Downloaded all tracks & reposts of user {user.username}!")
        if kwargs.get("p"):
            logger.info(f"Retrieving all playlists of user {user.username}...")
            #subplaylistbuffer=None if not kwargs.get("playlist_file") else []
            resources = client.get_user_playlists(user.id, limit=1000)
            for i, playlist in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"playlist n°{i} of {user.playlist_count}")
                download_playlist(client, playlist, **kwargs) # subplaylist_buffer=subplaylistbuffer, 
            #if kwargs.get("playlist_file"):
            #    playlist_process(client, subplaylistbuffer, kwdefget("playlist_file_name", "Playlists", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), no_export=True, **kwargs)
            logger.info(f"Downloaded all playlists of user {user.username}!")
        if kwargs.get("r"):
            logger.info(f"Retrieving all reposts of user {user.username}...")
            playlistcache=None if not kwargs.get("playlist_file_cache") else playlist_map_read(kwdefget("playlist_file_name", "Reposts", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs))
            playlistbuffer=None if not kwargs.get("playlist_file") else []
            subplaylistbuffer=None if not kwargs.get("playlist_file") else []
            resources = client.get_user_reposts(user.id, limit=1000)
            for i, item in itertools.islice(enumerate(resources, 1), offset, None):
                logger.info(f"item n°{i} of {user.reposts_count or '?'}")
                if item.type == "track-repost":
                    download_track_cached(client, item.track, exit_on_fail=kwargs.get("strict_playlist"), playlist_cache=playlistcache, playlist_buffer=playlistbuffer, **kwargs)
                elif item.type == "playlist-repost":
                    download_playlist(client, item.playlist, kwdefget("playlist_file_name", "Reposts", **kwargs) + " - ", subplaylist_buffer=subplaylistbuffer, **kwargs)
                else:
                    logger.error(f"Unknown item type {item.type}")
                    if kwargs.get("strict_playlist"):
                        sys.exit(1)
            if kwargs.get("playlist_file"):
                playlist_process(client, playlistbuffer, kwdefget("playlist_file_name", "Reposts", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), **kwargs)
                playlist_process(client, subplaylistbuffer, kwdefget("playlist_file_name", "Reposts Playlists", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs), no_export=True, **kwargs)
            logger.info(f"Downloaded all reposts of user {user.username}!")

    else:
        logger.error(f"Unknown item type {item.kind}")
        sys.exit(1)

def remove_files(check_playlist_file, playlist_file_extension):
    """
    Removes any pre-existing tracks that were not just downloaded
    """
    logger.info("Removing local track files that were not downloaded...")
    dirs = [d for d in os.listdir(".") if os.path.isdir(d)]
    dirs.insert(0, ".")
    for d in dirs:
        files = [f for f in os.listdir(d) if os.path.isfile(f)]
        playlist_data = []
        for plfile in files:
            if plfile.endswith(playlist_file_extension): playlist_data += playlist_import(plfile)
        if len(playlist_data) == 0: continue
        logger.debug(f"Removing from {d}")
      
        if playlist_data is None: continue
        for f in files:
            if not f.endswith(playlist_file_extension) and not f.endswith(playlist_file_extension + ".map") and f not in fileToKeep and f not in playlist_data:
                logger.info(f"Deleting {f}")
                os.remove(os.path.join(d, f))

def sync(client: SoundCloud, playlist: BasicAlbumPlaylist, playlist_info, **kwargs):
    """
    Downloads/Removes tracks that have been changed on playlist since last archive file
    """
    logger.info("Comparing tracks...")
    archive = kwargs.get("sync")
    with open(archive) as f:
        try:
            old = [int(i) for i in ''.join(f.readlines()).strip().split('\n')]
        except IOError as ioe:
            logger.error(f'Error trying to read download archive {archive}')
            logger.debug(ioe)
            sys.exit(1)
        except ValueError as verr:
            logger.error(f'Error trying to convert track ids. Verify archive file is not empty.')
            logger.debug(verr)
            sys.exit(1)

    new = [track.id for track in playlist.tracks]
    add = set(new).difference(old) # find tracks to download
    rem = set(old).difference(new) # find tracks to remove

    if not (add or rem):
        logger.info("No changes found. Exiting...")
        sys.exit(0)

    if rem:
        for track_id in rem:
            filename = get_filename(client.get_track(track_id),playlist_info=playlist_info,**kwargs)
            if filename in os.listdir('.'):
                os.remove(filename)
                logger.info(f'Removed {filename}')
            else:
                logger.info(f'Could not find {filename} to remove')
        with open(archive,'w') as f:
          for track_id in old:
            if track_id not in rem:
              f.write(str(track_id)+'\n')
    else:
        logger.info('No tracks to remove.')
              
    if add:
        return [track for track in playlist.tracks if track.id in add]
    else:
        logger.info('No tracks to download. Exiting...')
        sys.exit(0)

def download_playlist(client: SoundCloud, playlist: BasicAlbumPlaylist, playlist_filename_prefix="", subplaylist_buffer=None, **kwargs):
    """
    Downloads a playlist
    """
    if kwargs.get("no_playlist"):
        logger.info("Skipping playlist...")
        return
    playlist_name = playlist.title.encode("utf-8", "ignore")
    playlist_name = playlist_name.decode("utf-8")
    playlist_name = sanitize_filename(playlist_name)
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

        if not playlist.tracks or len(playlist.tracks) == 0: return
            
        if kwargs.get("sync"):
                  if os.path.isfile(kwargs.get("sync")):
                        playlist.tracks = sync(client, playlist, playlist_info, **kwargs)
                  else:
                        logger.error(f'Invalid sync archive file {kwargs.get("sync")}')
                        sys.exit(1)

        tracknumber_digits = len(str(len(playlist.tracks)))
        playlistbuffer=None if not kwargs.get("playlist_file") else []
        playlistcache=None if not kwargs.get("playlist_file_cache") else playlist_map_read(kwdefget("playlist_file_name", "Likes", **kwargs) + "." + kwdefget("playlist_file_extension", "m3u8", **kwargs))
        for counter, track in itertools.islice(enumerate(playlist.tracks, 1), kwargs.get("playlist_offset", 0), None):
            logger.debug(track)
            logger.info(f"Track n°{counter}")
            playlist_info["tracknumber"] = str(counter).zfill(tracknumber_digits)
            if isinstance(track, MiniTrack):
                if playlist.secret_token:
                    track = client.get_tracks([track.id], playlist.id, playlist.secret_token)[0]
                else:
                    track = client.get_track(track.id)

            download_track_cached(client, track, playlist_info, kwargs.get("strict_playlist"), playlist_cache=playlistcache, playlist_buffer=playlistbuffer, **kwargs)
        if kwargs.get("playlist_file"):
            playlist_filename=playlist_filename_prefix + playlist_name + ".m3u8"
            playlist_process(client, playlistbuffer, playlist_filename, **kwargs)
            if subplaylist_buffer: subplaylist_buffer.append({ "id": playlist.id, "path": playlist_filename, "uri": playlist.uri })
    except BaseException as err:
        logger.error(err)
        return False
    finally:
        if not kwargs.get("no_playlist_folder"):
            os.chdir("..")

def try_utime(path, filetime):
    try:
        os.utime(path, (time.time(), filetime))
    except Exception:
        logger.error("Cannot update utime of file")

def get_filename(track: BasicTrack, original_filename=None, aac=False, playlist_info=None, **kwargs):
    
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

    ext = ".m4a" if aac else ".mp3"  # contain aac in m4a to write metadata
    if original_filename is not None:
        original_filename = original_filename.encode("utf-8", "ignore").decode("utf-8")
        ext = os.path.splitext(original_filename)[1]
    filename = limit_filename_length(title, ext)
    filename = sanitize_filename(filename)
    return filename


def download_original_file(client: SoundCloud, track: BasicTrack, title: str, playlist_info=None, **kwargs):
    logger.info("Downloading the original file.")

    # Get the requests stream
    url = client.get_track_original_download(track.id, track.secret_token)
    
    if not url:
        logger.info("Could not get original download link")
        return (None, False)
    
    r = requests.get(url, stream=True)
    if r.status_code == 401:
        logger.info("The original file has no download left.")
        return (None, False)

    if r.status_code == 404:
        logger.info("Could not get name from stream - using basic name")
        return (None, False)

    # Find filename
    header = r.headers.get("content-disposition")
    _, params = cgi.parse_header(header)
    if "filename*" in params:
        encoding, filename = params["filename*"].split("''")
        filename = urllib.parse.unquote(filename, encoding=encoding)
    elif "filename" in params:
        filename = urllib.parse.unquote(params["filename"], encoding="utf-8")
    else:
        raise SoundCloudException(f"Could not get filename from content-disposition header: {header}")
    
    if not kwargs.get("original_name"):
        filename, ext = os.path.splitext(filename)

        # Find file extension
        mime = r.headers.get("content-type")
        ext = ext or mimetypes.guess_extension(mime)
        filename += ext

        filename = get_filename(track, filename, playlist_info=playlist_info, **kwargs)

    logger.debug(f"filename : {filename}")

    # Skip if file ID or filename already exists
    if already_downloaded(track, title, filename, **kwargs):
        if kwargs.get("flac") and can_convert(filename):
            filename = filename[:-4] + ".flac"
        return (filename, True)

    # Write file
    total_length = int(r.headers.get("content-length"))
    
    min_size = kwargs.get("min_size") or 0
    max_size = kwargs.get("max_size") or math.inf # max size of 0 treated as no max size
    
    if not min_size <= total_length <= max_size:
        raise SoundCloudException("File not within --min-size and --max-size bounds")
    
    temp = tempfile.NamedTemporaryFile(delete=False)
    received = 0
    with temp as f:
        for chunk in progress.bar(
            r.iter_content(chunk_size=1024),
            expected_size=(total_length / 1024) + 1,
            hide=True if kwargs.get("hide_progress") else False,
        ):
            if chunk:
                received += len(chunk)
                f.write(chunk)
                f.flush()

    if received != total_length:
        logger.error("connection closed prematurely, download incomplete")
        sys.exit(1)

    shutil.move(temp.name, os.path.join(os.getcwd(), filename))
    if kwargs.get("flac") and can_convert(filename):
        logger.info("Converting to .flac...")
        newfilename = limit_filename_length(filename[:-4], ".flac")

        commands = ["ffmpeg", "-i", filename, newfilename, "-loglevel", "error"]
        logger.debug(f"Commands: {commands}")
        subprocess.call(commands)
        os.remove(filename)
        filename = newfilename

    return (filename, False)


def get_transcoding_m3u8(client: SoundCloud, transcoding: Transcoding, **kwargs):
    url = transcoding.url
    bitrate_KBps = 256 / 8 if "aac" in transcoding.preset else 128 / 8
    total_bytes = bitrate_KBps * transcoding.duration
    
    min_size = kwargs.get("min_size") or 0
    max_size = kwargs.get("max_size") or math.inf # max size of 0 treated as no max size
    
    if not min_size <= total_bytes <= max_size:
        raise SoundCloudException("File not within --min-size and --max-size bounds")

    if url is not None:
        headers = client.get_default_headers()
        if client.auth_token:
            headers["Authorization"] = f"OAuth {client.auth_token}"
        r = requests.get(url, params={"client_id": client.client_id}, headers=headers)
        logger.debug(r.url)
        return r.json()["url"]


def download_hls(client: SoundCloud, track: BasicTrack, title: str, playlist_info=None, **kwargs):

    if not track.media.transcodings:
        raise SoundCloudException(f"Track {track.permalink_url} has no transcodings available")
    
    logger.debug(f"Trancodings: {track.media.transcodings}")
    
    aac_transcoding = None
    mp3_transcoding = None
    
    for t in track.media.transcodings:
        if t.format.protocol == "hls" and "aac" in t.preset:
            aac_transcoding = t
        elif t.format.protocol == "hls" and "mp3" in t.preset:
            mp3_transcoding = t
    
    aac = False
    transcoding = None
    if not kwargs.get("onlymp3") and aac_transcoding:
        transcoding = aac_transcoding
        aac = True
    elif mp3_transcoding:
        transcoding = mp3_transcoding
                
    if not transcoding:
        raise SoundCloudException(f"Could not find mp3 or aac transcoding. Available transcodings: {[t.preset for t in track.media.transcodings if t.format.protocol == 'hls']}")

    filename = get_filename(track, None, aac, playlist_info, **kwargs)
    logger.debug(f"filename : {filename}")
    # Skip if file ID or filename already exists
    if already_downloaded(track, title, filename, **kwargs):
        return (filename, True)

    # Get the requests stream
    url = get_transcoding_m3u8(client, transcoding, **kwargs)
    temp = tempfile.NamedTemporaryFile(delete=False)
    temp_filename = temp.name + os.path.splitext(filename)[1]

    p = subprocess.Popen(
        ["ffmpeg", "-i", url, "-c", "copy", temp_filename, "-loglevel", "error"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = p.communicate()
    if stderr:
        logger.error(stderr.decode("utf-8"))
    shutil.move(temp_filename, os.path.join(os.getcwd(), filename))
    return (filename, False)


def download_track(client: SoundCloud, track: BasicTrack, playlist_info=None, exit_on_fail=True, playlist_buffer=None, **kwargs):
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

        # Downloadable track
        filename = None
        is_already_downloaded = False
        if (
            track.downloadable
            and not kwargs["onlymp3"]
            and not kwargs.get("no_original")
        ):
            filename, is_already_downloaded = download_original_file(client, track, title, playlist_info, **kwargs)

        if filename is None:
            if kwargs.get("only_original"):
                raise SoundCloudException(f'Track "{track.permalink_url}" does not have original file available. Not downloading...')
            filename, is_already_downloaded = download_hls(client, track, title, playlist_info, **kwargs)

        if kwargs.get("remove"):
            fileToKeep.append(filename)

        record_download_archive(track, **kwargs)

        # Skip if file ID or filename already exists
        if is_already_downloaded and not kwargs.get("force_metadata"):
            if playlist_buffer is not None: playlist_buffer.append({ "id": track.id, "path": filename, "uri": track.uri })
            raise SoundCloudSoftException(f"{filename} already downloaded.")

        # If file does not exist an error occurred
        if not os.path.isfile(filename):
            raise SoundCloudException(f"An error occurred downloading {filename}.")

        # Try to set the metadata
        if (
            filename.endswith(".mp3")
            or filename.endswith(".flac")
            or filename.endswith(".m4a")
            or filename.endswith(".wav")
        ):
            try:
                set_metadata(track, filename, playlist_info, **kwargs)
            except Exception:
                os.remove(filename)
                logger.exception("Error trying to set the tags...")
                raise SoundCloudException("Error trying to set the tags...")
        else:
            logger.error("This type of audio doesn't support tagging...")

        # Try to change the real creation date
        filetime = int(time.mktime(track.created_at.timetuple()))
        try_utime(filename, filetime)

        if playlist_buffer is not None: playlist_buffer.append({ "id": track.id, "path": filename, "uri": track.uri })
        logger.info(f"{filename} Downloaded.\n")
        return True
        
    except SoundCloudException as err:
        logger.error(err)
        if exit_on_fail:
            sys.exit(1)
        return False

    except SoundCloudSoftException as err:
        logger.error(err)
        return False

    except BaseException as err:
        logger.error(err)
        return False

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
        if kwargs.get("overwrite"):
            os.remove(filename)
            already_downloaded = False
    if (
        kwargs.get("flac")
        and can_convert(filename)
        and os.path.isfile(filename[:-4] + ".flac")
    ):
        already_downloaded = True
        if kwargs.get("overwrite"):
            os.remove(filename[:-4] + ".flac")
            already_downloaded = False
    if kwargs.get("download_archive") and in_download_archive(track, **kwargs):
        already_downloaded = True

    if kwargs.get("flac") and can_convert(filename) and os.path.isfile(filename):
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
    if not kwargs.get("download_archive"):
        return

    archive_filename = kwargs.get("download_archive")
    try:
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
    if not kwargs.get("download_archive"):
        return

    archive_filename = kwargs.get("download_archive")
    try:
        with open(archive_filename, "a", encoding="utf-8") as file:
            file.write(f"{track.id}\n")
    except IOError as ioe:
        logger.error("Error trying to write to download archive...")
        logger.error(ioe)


def set_metadata(track: BasicTrack, filename: str, playlist_info=None, **kwargs):
    """
    Sets the mp3 file metadata using the Python module Mutagen
    """
    logger.info("Setting tags...")
    artwork_url = track.artwork_url
    user = track.user
    if not artwork_url:
        artwork_url = user.avatar_url
    response = None
    if kwargs.get("original_art"):
        new_artwork_url = artwork_url.replace("large", "original")
        try:
            response = requests.get(new_artwork_url, stream=True)
            if response.headers["Content-Type"] not in (
                "image/png",
                "image/jpeg",
                "image/jpg",
            ):
                response = None
        except Exception:
            response = None
    try:
        if response is None:
            new_artwork_url = artwork_url.replace("large", "t500x500")
            response = requests.get(new_artwork_url, stream=True)
            if response.headers["Content-Type"] not in (
                "image/png",
                "image/jpeg",
                "image/jpg",
            ):
                response = None
    except Exception:
        response = None
    if response is None:
        logger.error(f"Could not get cover art at {new_artwork_url}")
    with tempfile.NamedTemporaryFile() as out_file:
        if response:
            shutil.copyfileobj(response.raw, out_file)
            out_file.seek(0)

        track.date = track.created_at.strftime("%Y-%m-%d %H::%M::%S")

        track.artist = user.username
        if kwargs.get("extract_artist"):
            for dash in [" - ", " − ", " – ", " — ", " ― "]:
                if dash in track.title:
                    artist_title = track.title.split(dash)
                    track.artist = artist_title[0].strip()
                    track.title = artist_title[1].strip()
                    break
        mutagen_file = mutagen.File(filename)
        mutagen_file.delete()
        if track.description:
            if mutagen_file.__class__ == mutagen.flac.FLAC:
                mutagen_file["description"] = track.description
            elif mutagen_file.__class__ == mutagen.mp3.MP3 or mutagen_file.__class__ == mutagen.wave.WAVE:
                mutagen_file["COMM"] = mutagen.id3.COMM(
                    encoding=3, lang="ENG", text=track.description
                )
            elif mutagen_file.__class__ == mutagen.mp4.MP4:
                mutagen_file["\xa9cmt"] = track.description
        if response is not None:
            if mutagen_file.__class__ == mutagen.flac.FLAC:
                p = mutagen.flac.Picture()
                p.data = out_file.read()
                p.mime = "image/jpeg"
                p.type = mutagen.id3.PictureType.COVER_FRONT
                mutagen_file.add_picture(p)
            elif mutagen_file.__class__ == mutagen.mp3.MP3 or mutagen_file.__class__ == mutagen.wave.WAVE:
                mutagen_file["APIC"] = mutagen.id3.APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=out_file.read(),
                )
            elif mutagen_file.__class__ == mutagen.mp4.MP4:
                mutagen_file["covr"] = [mutagen.mp4.MP4Cover(out_file.read())]

        if mutagen_file.__class__ == mutagen.wave.WAVE:
            mutagen_file["TIT2"] = mutagen.id3.TIT2(encoding=3, text=track.title)
            mutagen_file["TPE1"] = mutagen.id3.TPE1(encoding=3, text=track.artist)
            if track.genre:
                mutagen_file["TCON"] = mutagen.id3.TCON(encoding=3, text=track.genre)
            if track.permalink_url:
                mutagen_file["WOAS"] = mutagen.id3.WOAS(url=track.permalink_url)
            if track.date:
                mutagen_file["TDAT"] = mutagen.id3.TDAT(encoding=3, text=track.date)
            if playlist_info:
                if not kwargs.get("no_album_tag"):
                    mutagen_file["TALB"] = mutagen.id3.TALB(encoding=3, text=playlist_info["title"])
                mutagen_file["TRCK"] = mutagen.id3.TRCK(encoding=3, text=str(playlist_info["tracknumber"]))
            mutagen_file.save()
        else:
            mutagen_file.save()
            audio = mutagen.File(filename, easy=True)
            audio["title"] = track.title
            audio["artist"] = track.artist
            if track.genre:
                audio["genre"] = track.genre
            if track.permalink_url:
                audio["website"] = track.permalink_url
            if track.date:
                audio["date"] = track.date
            if playlist_info:
                if not kwargs.get("no_album_tag"):
                    audio["album"] = playlist_info["title"]
                audio["tracknumber"] = str(playlist_info["tracknumber"])

            audio.save()

def limit_filename_length(name: str, ext: str, max_bytes=255):
    while len(name.encode("utf-8")) + len(ext.encode("utf-8")) > max_bytes:
        name = name[:-1]
    return name + ext

def is_ffmpeg_available():
    """
    Returns true if ffmpeg is available in the operating system
    """
    return shutil.which("ffmpeg") is not None

def playlist_process(client: SoundCloud, playlist_buffer, playlist_filename, no_export=False, no_retain=False, **kwargs):
    if kwargs.get("playlist_file_retain") and no_retain == False:
        oldint = playlist_map_read(playlist_filename)
        oldext = None if no_export == True else playlist_import(playlist_filename)
        oldindex=-1

        logger.debug(f"Old Map: {oldint}")
        logger.debug("Old Playlist: {oldext}")
        
        for oldel in reversed(oldint):
            tpath=oldel["path"]
            oldindex=oldindex+1
            if oldel["id"] == "-1":
                # Stop retaining track if deleted from playlist by the user
                if no_export == False and oldext is not None and oldel["path"] not in oldext:
                    logger.debug(f"Not retaining {tpath} ({oldel['uri']})")
                    continue
                # Stop retaining playlist if according file deleted by the user
                elif no_export == True and not os.path.isfile(oldel["path"]):
                    logger.debug(f"Not retaining {tpath} ({oldel['uri']})")
                    continue
                # Stop retaining if track or playlist has been restored
                if next((newel for newel in playlist_buffer if newel["uri"] == oldel["uri"]), None) is not None:
                    logger.debug(f"Stopping to retain restored {tpath} ({oldel['uri']})")
                    continue

            else:
                # Check if item removed
                if next((newel for newel in playlist_buffer if newel["uri"] == oldel["uri"]), None) is not None: continue
                # Check if item removed because it is corrupted
                if check_item(client, oldel["uri"]) == True:
                    # Item not corrupted
                    logger.debug(f"Not retaining {tpath} ({oldel['uri']})")
                    if no_export == True and os.path.isfile(oldel["path"]): os.remove(oldel["path"])
                    continue
                oldel["id"] = "-1"

            # Temporarily retain item due to corrupted file on server
            logger.debug(f"Retaining {tpath} ({oldel['uri']})")
            newindex = 0 if len(playlist_buffer) - oldindex < 0 else len(playlist_buffer) - oldindex
            playlist_buffer.insert(newindex, oldel)

        logger.debug(f"New Map: {playlist_buffer}")

    if kwargs.get("playlist_file_retain") or (kwargs.get("playlist_file_cache") and no_retain == False):
        playlist_map_write(playlist_buffer, playlist_filename)
        
    if no_export == False:
        playlist_export(playlist_buffer, playlist_filename)

def playlist_map_read(playlist_filename):
    try:
        res = []
        if not os.path.isfile(playlist_filename + ".map"): return res
        with open(playlist_filename + ".map", "r") as fin:
            for fline in fin.read().splitlines():
                ffields = fline.split(":", 2)
                if len(ffields) == 3: res.append({ "id": ffields[0], "path": ffields[1], "uri": ffields[2] })
        return res
    except Exception:
        return []

def playlist_map_write(playlist_buffer, playlist_filename):
    if playlist_buffer is None or len(playlist_buffer) == 0: return
    with open(playlist_filename + ".map", "w") as fout:
        for playlist_item in playlist_buffer:
            fout.write(str(playlist_item["id"]) + ":" + playlist_item["path"] + ":" + playlist_item["uri"] + "\n")

def playlist_import(playlist_filename):
    try:
        res = []
        if not os.path.isfile(playlist_filename): return None
        with open(playlist_filename, "r") as fin:
            for fline in fin.read().splitlines():
                if not fline.startswith("#EXT") or fline == sanitize_filename(fline): res.append(fline)
                    
        return res
    except Exception:
        return None

def playlist_export(playlist_buffer, playlist_filename):
    with open(playlist_filename, "w") as fout:
        for playlist_item in playlist_buffer:
            fout.write(playlist_item["path"] + "\n")

def check_item(client: SoundCloud, itemuri):
    item = client.resolve(itemuri)
    if not item:
        return False
    elif item.kind == "track":
        if item.policy == "BLOCK": return False
        if item.downloadable and client.get_track_original_download(item.id, item.secret_token): return True
        if not item.media.transcodings: return False
        for t in item.media.transcodings:
            if t.format.protocol == "hls" and "aac" in t.preset: return True
            elif t.format.protocol == "hls" and "mp3" in t.preset: return True
        return False
    elif item.kind == "playlist":
        return item.tracks is not None and len(item.tracks) > 0
    elif item.kind == "user":
        return True
    else:
        return False

def download_track_cached(client: SoundCloud, track: BasicTrack, playlist_info=None, exit_on_fail=True, playlist_cache=None, playlist_buffer=None, **kwargs):
    if playlist_cache is not None and playlist_buffer is not None:
        cacheres = next((cached for cached in playlist_cache if cached["id"] == str(track.id)), None)
        if cacheres is not None and cacheres["path"] is not None and os.path.isfile(cacheres["path"]):
            playlist_buffer.append({ "id": track.id, "path": cacheres["path"], "uri": track.uri })
            return True
    return download_track(client, track, playlist_info=playlist_info, exit_on_fail=exit_on_fail, playlist_buffer=playlist_buffer, **kwargs)
    
if __name__ == "__main__":
    main()
