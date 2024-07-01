import os
from pathlib import Path

import pytest

from tests.utils import assert_not_track, assert_track, call_scdl_with_auth


def test_original_download(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",  # thanks saves for hosting
        "--name-format",
        "track",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.wav", "copy", "saves", None)


def test_original_to_stdout(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "-",
        encoding=None,
    )
    assert r.returncode == 0
    with open('track.wav', 'wb') as f:
        f.write(r.stdout)
    assert_track(tmp_path, "track.wav", "copy", "saves", None)


def test_mp3_to_stdout(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--onlymp3",
        "--name-format",
        "-",
        encoding=None,
    )
    assert r.returncode == 0

    with open('track.mp3', 'wb') as f:
        f.write(r.stdout)

    assert_track(tmp_path, "track.mp3")


def test_flac_to_stdout(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "-",
        "--flac",
        encoding=None,
    )

    with open('track.flac', 'wb') as f:
        f.write(r.stdout)

    assert r.returncode == 0
    assert_track(tmp_path, "track.flac", "copy", "saves", None)


def test_flac(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "track",
        "--flac",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.flac", "copy", "saves", None)


def test_m4a(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/7x11x13/wan-bushi-eurodance-vibes-part-123",
        "--name-format",
        "track",
        "--no-original",
        "--opus",
    )
    assert r.returncode == 0
    assert_track(
        tmp_path,
        "track.m4a",
        "Wan Bushi - Eurodance Vibes (part 1+2+3)",
        "7x11x13",
        "Electronic",
        None,
    )


def test_opus(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--no-original",
        "--opus",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.opus")


def test_mp3(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.mp3")


def test_unlisted_track(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track-2/s-fgLQFAzNIMP",
        "--name-format",
        "track",
        "--onlymp3",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.mp3", "test track 2")


def test_original_art(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
        "--original-art",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.mp3", expected_artwork_len=3409)


def test_original_name(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "track",
        "--original-name",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "original.wav", check_metadata=False)


def test_original_metadata(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "track",
        "--original-metadata",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.wav", "og title", "og artist", "og genre", 0)


def test_force_metadata(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "track",
        "--original-metadata",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.wav", "og title", "og artist", "og genre", 0)

    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/57v/original",
        "--name-format",
        "track",
        "--force-metadata",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.wav", "copy", "saves", None)


def test_addtimestamp(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--onlymp3",
        "--addtimestamp",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "1719169486_testing - test track.mp3", check_metadata=False)


def test_addtofile(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track-2/s-fgLQFAzNIMP",
        "--onlymp3",
        "--addtofile",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "7x11x13-testing - test track 2.mp3", check_metadata=False)


def test_extract_artist(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--onlymp3",
        "--name-format",
        "track",
        "--extract-artist",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.mp3", "test track", "testing")


def test_maxsize(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--onlymp3",
        "--max-size=10kb",
    )
    assert r.returncode == 1
    assert "not within --min-size and --max-size bounds" in r.stderr


def test_minsize(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--onlymp3",
        "--min-size=1mb",
    )
    assert r.returncode == 1
    assert "not within --min-size and --max-size bounds" in r.stderr


def test_only_original(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track-2/s-fgLQFAzNIMP",
        "--only-original",
    )
    assert r.returncode == 1
    assert "does not have original file available" in r.stderr


def test_overwrite(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
    )
    assert r.returncode == 0

    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
    )
    assert r.returncode == 1
    assert "already exists" in r.stderr

    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
        "--overwrite",
    )
    assert r.returncode == 0


def test_path(tmp_path: Path):
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
        "--path",
        str(tmp_path),
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.mp3", check_metadata=False)


def test_remove(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track.mp3", check_metadata=False)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track-2/s-fgLQFAzNIMP",
        "--name-format",
        "track2",
        "--remove",
        "--onlymp3",
    )
    assert r.returncode == 0
    assert_track(tmp_path, "track2.mp3", check_metadata=False)
    assert_not_track(tmp_path, "track.mp3")


def test_download_archive(tmp_path: Path):
    os.chdir(tmp_path)
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
        "--download-archive=archive.txt",
    )
    assert r.returncode == 0
    os.remove("track.mp3")
    assert not os.path.exists("track.mp3")
    r = call_scdl_with_auth(
        "-l",
        "https://soundcloud.com/one-thousand-and-one/test-track",
        "--name-format",
        "track",
        "--onlymp3",
        "--download-archive=archive.txt",
    )
    assert r.returncode == 1
    assert "already exists" in r.stderr
