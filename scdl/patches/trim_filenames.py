# https://github.com/yt-dlp/yt-dlp/pull/12023

import os
import platform
import re
import sys
from pathlib import Path

import yt_dlp
from yt_dlp import YoutubeDL, options
from yt_dlp import validate_options as old_validate_options
from yt_dlp.utils import OUTTMPL_TYPES, preferredencoding, replace_extension
from yt_dlp.YoutubeDL import _catch_unsafe_extension_error


def evaluate_outtmpl(self, outtmpl, info_dict, *args, trim_filename=False, **kwargs):
    outtmpl, info_dict = self.prepare_outtmpl(outtmpl, info_dict, *args, **kwargs)
    if not trim_filename:
        return self.escape_outtmpl(outtmpl) % info_dict

    ext_suffix = ".%(ext\0s)s"
    suffix = ""
    if outtmpl.endswith(ext_suffix):
        outtmpl = outtmpl[: -len(ext_suffix)]
        suffix = ext_suffix % info_dict
    outtmpl = self.escape_outtmpl(outtmpl)
    filename = outtmpl % info_dict

    def parse_trim_file_name(trim_file_name):
        if trim_file_name is None or trim_file_name == "none":
            return 0, None
        mobj = re.match(r"(?:(?P<length>\d+)(?P<mode>b|c)?|none)", trim_file_name)
        return int(mobj.group("length")), mobj.group("mode") or "c"

    max_file_name, mode = parse_trim_file_name(self.params.get("trim_file_name"))
    if max_file_name == 0:
        # no maximum
        return filename + suffix

    encoding = sys.getfilesystemencoding() if platform.system() != "Windows" else "utf-16-le"

    def trim_filename(name: str):
        if mode == "b":
            name = name.encode(encoding)
            name = name[:max_file_name]
            return name.decode(encoding, "ignore")
        return name[:max_file_name]

    filename = os.path.join(*map(trim_filename, Path(filename).parts or "."))
    return filename + suffix


@_catch_unsafe_extension_error
def _prepare_filename(self, info_dict, *, outtmpl=None, tmpl_type=None):
    assert None in (outtmpl, tmpl_type), "outtmpl and tmpl_type are mutually exclusive"
    if outtmpl is None:
        outtmpl = self.params["outtmpl"].get(tmpl_type or "default", self.params["outtmpl"]["default"])
    try:
        outtmpl = self._outtmpl_expandpath(outtmpl)
        filename = self.evaluate_outtmpl(outtmpl, info_dict, True, trim_filename=True)
        if not filename:
            return None

        if tmpl_type in ("", "temp"):
            final_ext, ext = self.params.get("final_ext"), info_dict.get("ext")
            if final_ext and ext and final_ext != ext and filename.endswith(f".{final_ext}"):
                filename = replace_extension(filename, ext, final_ext)
        elif tmpl_type:
            force_ext = OUTTMPL_TYPES[tmpl_type]
            if force_ext:
                filename = replace_extension(filename, force_ext, info_dict.get("ext"))
        return filename
    except ValueError as err:
        self.report_error("Error in output template: " + str(err) + " (encoding: " + repr(preferredencoding()) + ")")
        return None


def new_validate_options(opts):
    def validate(cndn, name, value=None, msg=None):
        if cndn:
            return True
        raise ValueError((msg or 'invalid {name} "{value}" given').format(name=name, value=value))

    def validate_regex(name, value, regex):
        return validate(value is None or re.match(regex, value), name, value)

    ret = old_validate_options(opts)
    validate_regex("trim filenames", opts.trim_file_name, r"(?:\d+[bc]?|none)")
    return ret


old_create_parser = options.create_parser


def create_parser_patched():
    parser = old_create_parser()
    filesystem = parser.get_option_group("--trim-filenames")
    filesystem.remove_option("--trim-filenames")
    filesystem.add_option(
        "--trim-filenames",
        "--trim-file-names",
        metavar="LENGTH",
        dest="trim_file_name",
        default="none",
        help="Limit the filename length (excluding extension) to the specified number of characters or bytes",
    )
    return parser


YoutubeDL.evaluate_outtmpl = evaluate_outtmpl
YoutubeDL._prepare_filename = _prepare_filename
yt_dlp.validate_options = new_validate_options
options.create_parser = create_parser_patched
