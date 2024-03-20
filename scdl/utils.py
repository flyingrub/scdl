# -*- encoding: utf-8 -*-

"""
Copied from
https://github.com/davidfischer-ch/pytoolbox/blob/master/pytoolbox/logging.py
"""

import logging
import re
from termcolor import colored

__all__ = ('ColorizeFilter', )


class ColorizeFilter(logging.Filter):

    color_by_level = {
        logging.DEBUG: 'blue',
        logging.WARNING: 'yellow',
        logging.ERROR: 'red'
    }

    def filter(self, record):
        record.raw_msg = record.msg
        color = self.color_by_level.get(record.levelno)
        if color:
            record.msg = colored(record.msg, color)
        return True


def size_in_bytes(insize):
    """
    Returns the size in bytes from strings such as '5 mb' into 5242880.

    >>> size_in_bytes('1m')
    1048576
    >>> size_in_bytes('1.5m')
    1572864
    >>> size_in_bytes('2g')
    2147483648
    >>> size_in_bytes(None)
    Traceback (most recent call last):
        raise ValueError('no string specified')
    ValueError: no string specified
    >>> size_in_bytes('')
    Traceback (most recent call last):
        raise ValueError('no string specified')
    ValueError: no string specified
    """
    if insize is None or insize.strip() == '':
        raise ValueError('no string specified')

    units = {
        'k': 1024,
        'm': 1024 ** 2,
        'g': 1024 ** 3,
        't': 1024 ** 4,
        'p': 1024 ** 5,
    }
    match = re.search('^\s*([0-9\.]+)\s*([kmgtp])?', insize, re.I)

    if match is None:
        raise ValueError('match not found')

    size, unit = match.groups()

    if size:
        size = float(size)

    if unit:
        size = size * units[unit.lower().strip()]

    return int(size)
