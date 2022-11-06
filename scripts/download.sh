#!/bin/sh -ex

pip install .

scdl -l https://soundcloud.com/corletti/sets/barely0 --path /Users/anthony/Music --strict-playlist
scdl -l https://soundcloud.com/corletti/sets/barely1 --path /Users/anthony/Music --strict-playlist
scdl -l https://soundcloud.com/corletti/sets/barely2 --path /Users/anthony/Music --strict-playlist

