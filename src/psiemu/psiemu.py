#!/usr/bin/env python3

# Copyright (c) 2025-2026 Jason Morley
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import curses
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile

import pyclip
import requests
import yaml

from dataclasses import dataclass

PSIEMU_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
RESOURCES_DIRECTORY = os.path.join(PSIEMU_DIRECTORY, "resources")
PROFILES_PATH = os.path.join(RESOURCES_DIRECTORY, "profiles.yaml")

CONFIG_DIRECTORY = os.path.expanduser("~/.config/psiemu")
NVRAM_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "nvram")
CFG_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "cfg")

CACHE_DIRECTORY = os.path.expanduser("~/.cache/psiemu")
ROM_DIRECTORY = os.path.join(CACHE_DIRECTORY, "roms")

os.makedirs(CONFIG_DIRECTORY, exist_ok=True)
os.makedirs(CACHE_DIRECTORY, exist_ok=True)

LANGUAGES = {
    "de-DE": {"name": "German", "symbol": "de"},
    "en-GB": {"name": "British English", "symbol": "en"},
    "en-US": {"name": "American English", "symbol": "us"},
    "es-ES": {"name": "Spanish", "symbol": "es"},
    "fr-FR": {"name": "French", "symbol": "fr"},
    "it-IT": {"name": "Italian", "symbol": "it"},
    "nl-NL": {"name": "Dutch", "symbol": "nl"},
    "ru-RU": {"name": "Russian", "symbol": "ru"},
}

NOTES = """Special keys:

- Menu -> F11 (Shift + F11 on macOS)
- Psion -> Alt
- Help -> F10

Silkscreen buttons:

- System -> F1
- Data -> F2
- Word -> F3
- Agenda -> F4
- Time -> F5
- World -> F6
- Calc -> F7
- Sheet -> F8

"""

HEADER = r"""
 ____      _ _____
|  _ \ ___(_) ____|_ __ ___  _   _
| |_) / __| |  _| | '_ ` _ \| | | |
|  __/\__ \ | |___| | | | | | |_| |
|_|   |___/_|_____|_| |_| |_|\__,_|

MAME Emulation Launcher for Psion Devices
"""
HEADER = HEADER[1:]  # Trim the leading newline (makes the header easier to read and write).
HEADER_LENGTH = len(HEADER.split("\n"))


with open(PROFILES_PATH) as fh:
    PROFILES = yaml.safe_load(fh)


@dataclass
class Selection:

    vendor: int
    device: int
    variant: int


def download(url, filename):
    destination_path = os.path.join(os.getcwd(), filename)

    print(f"Downloading '{os.path.basename(filename)}'...")

    with tempfile.TemporaryDirectory() as directory:
        temporary_path = os.path.join(directory, filename)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(temporary_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        shutil.move(temporary_path, destination_path)
        return destination_path


def hash(path):
    md5 = hashlib.md5()
    if os.path.isdir(path):
        for f in sorted(listdir(path, include_hidden=False)):
            md5.update(shasum(os.path.join(path, f)).encode('utf-8'))
    else:
        with open(path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                md5.update(data)
    return md5.hexdigest()


def mame_command(profile):

    scale = profile["display"]["scale"] * 2  # TODO: Detect display scale.
    width, height = profile["display"]["width"], profile["display"]["height"]

    command = [
        "mame",
        "-window",
        "-nomaximize",
        "-skip_gameinfo",
        "-rompath", ROM_DIRECTORY,
        "-cfg_directory", CFG_DIRECTORY,
        "-nvram_directory", NVRAM_DIRECTORY,
        "-prescale", "%s" % (scale, ),
        "-resolution", "%dx%d" % (width * scale, height * scale),
        profile["id"],
    ]

    if "bios" in profile:
        command.extend([
            "-bios", profile["bios"],
        ])

    return command


def run_mame(profile):
    command = mame_command(profile)
    subprocess.Popen(command,
                     start_new_session=True,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def language_symbol(variant):
    languages = variant["languages"]
    if len(languages) > 1:
        return "+ "
    elif len(languages) == 1:
        return LANGUAGES[languages[0]]["symbol"]
    else:
        return " "


def language_description(variant):
    return ", " .join([LANGUAGES[language]["name"] for language in variant["languages"]])


def device_picker(stdscr):

    def render_footer(text, offset, attr=0):
        (height, width) = stdscr.getmaxyx()
        text = text.ljust(width)[:width]
        try:
            stdscr.addstr(height + offset, 0, text, attr)
        except curses.error:
            pass

    def render_device_section(devices, is_section_active, y_pos, selection):

        for device_index, profile in enumerate(devices):
            title = profile["name"].ljust(22)
            variants = profile["variants"]

            for variant_index, variant in enumerate(variants):
                name = variant["name"]
                languages = language_symbol(variant)
                # languages = "".join([LANGUAGES[language] for language in variant["languages"]])
                if is_section_active and device_index == selection.device and variant_index == selection.variant:
                    name = "-> " + name
                else:
                    name = "   " + name
                # While it might seem like a good idea to use `ljust` here to ensure these are consistent lengths
                # we're instead relying on `name` being of equal length to avoid bumping into Python's terrible
                # handling of multi-codepoint emoji.
                # In the future, we might want to use 'grapheme' which provides suport for this.
                title += f"{name} {languages}  "

            stdscr.addstr(y_pos + device_index, 0, "  " + title)

        return len(devices) + 2

    curses.use_default_colors()
    curses.curs_set(0)

    selection = Selection(0, 0, 0)
    status_text = None

    while True:

        (height, width) = stdscr.getmaxyx()
        stdscr.clear()

        stdscr.addstr(0, 0, HEADER)
        offset = HEADER_LENGTH

        for vendor_index, vendor in enumerate(PROFILES):
            stdscr.addstr(offset, 0, vendor["name"])
            offset += render_device_section(devices=vendor["devices"],
                                            is_section_active=vendor_index == selection.vendor,
                                            y_pos=offset + 2,
                                            selection=selection)
            offset += 1

        # Current selection.
        vendor = PROFILES[selection.vendor]
        devices = vendor["devices"]
        profile = vendor["devices"][selection.device]
        variant = profile["variants"][selection.variant]

        # Render the footer.
        render_footer("ent: run   c: copy command   q: quit", -2, curses.A_REVERSE)
        if status_text is not None:
            render_footer(status_text, -1)
            status_text = None
        else:
            languages = language_description(variant)
            render_footer(f"{variant["description"]} ({languages})" if "description" in variant else languages, -1)

        # Get and handle input.
        key = stdscr.getch()
        if key == curses.KEY_UP:

            if selection.device > 0:
                selection.device -= 1
                selection.variant = 0
            elif selection.vendor > 0:
                selection.vendor -= 1
                selection.device = len(PROFILES[selection.vendor]["devices"]) - 1
                selection.variant = 0

        elif key == curses.KEY_DOWN:

            if selection.device < len(devices) - 1:
                selection.device += 1
                selection.variant = 0
            elif selection.vendor < len(PROFILES) - 1:
                selection.vendor += 1
                selection.device = 0
                selection.variant = 0

        elif key == curses.KEY_LEFT:

            if selection.variant > 0:
                selection.variant -= 1

        elif key == curses.KEY_RIGHT:

            variants = profile["variants"]
            if selection.variant < len(variants) - 1:
                selection.variant += 1

        elif key == ord('\n'):

            run_mame(variant)

        elif key == ord('c'):

            pyclip.copy(" ".join(mame_command(variant)))
            status_text = "Command line copied to clipboard"

        elif key == 27 or key == ord('q'):

            return None


def main():
    parser = argparse.ArgumentParser()
    options = parser.parse_args()

    os.makedirs(ROM_DIRECTORY, exist_ok=True)
    for profile in PROFILES:
        for device in profile["devices"]:
            for variant in device["variants"]:
                if "roms" not in variant:
                    continue
                device_directory = os.path.join(ROM_DIRECTORY, variant["id"] if "id" in variant else device["id"])
                os.makedirs(device_directory, exist_ok=True)
                for rom in variant["roms"]:
                    rom_path = os.path.join(device_directory, rom["name"])
                    if "md5" in rom and os.path.exists(rom_path):
                        if hash(rom_path) == rom["md5"]:
                            continue
                        os.remove(rom_path)
                    download(rom["url"], rom_path)

    os.environ.setdefault('ESCDELAY', '25')
    curses.wrapper(lambda stdscr: device_picker(stdscr))


if __name__ == "__main__":
    main()
