import os
import subprocess
from pathlib import Path
from typing import Optional

import music_tag
from soundcloud import SoundCloud

client_id = SoundCloud().client_id


def call_scdl_with_auth(*args, encoding: Optional[str] = 'utf-8') -> subprocess.CompletedProcess[str]:
    auth_token = os.getenv("AUTH_TOKEN")
    assert auth_token
    args = (
        ["scdl"]
        + list(args)
        + [f"--auth-token={auth_token}", f"--client-id={client_id}"]
    )
    return subprocess.run(args, capture_output=True, encoding=encoding,
                          errors='ignore' if encoding is not None else None)


def assert_track(
    tmp_path: Path,
    expected_name: str,
    expected_title: str = "testing - test track",
    expected_artist: str = "7x11x13-testing",
    expected_genre: Optional[str] = "Testing",
    expected_artwork_len: int = 16136,
    expected_album: Optional[str] = None,
    expected_albumartist: Optional[str] = None,
    expected_tracknumber: Optional[int] = None,
    check_metadata: bool = True,
):
    file = tmp_path / expected_name
    assert file.exists()

    if check_metadata:
        f = music_tag.load_file(file)
        assert f["title"].value == expected_title
        assert f["artist"].value == expected_artist
        if expected_genre:
            assert f["genre"].value == expected_genre
        if expected_artwork_len is not None:
            if expected_artwork_len > 0:
                assert len(f["artwork"].value.data) == expected_artwork_len
            else:
                assert not f["artwork"]
        if expected_album:
            assert f["album"].value == expected_album
        if expected_albumartist:
            assert f["albumartist"].value == expected_albumartist
        if expected_tracknumber is not None:
            assert f["tracknumber"].value == expected_tracknumber


def assert_not_track(tmp_path: Path, expected_name: str):
    file = tmp_path / expected_name
    assert not file.exists()
