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
import math
import os
import shutil
import subprocess
import tempfile

import pyclip
import requests
import yaml

from dataclasses import dataclass
from lxml import etree

PSIEMU_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
RESOURCES_DIRECTORY = os.path.join(PSIEMU_DIRECTORY, "resources")
PROFILES_PATH = os.path.join(RESOURCES_DIRECTORY, "profiles.yaml")

CONFIG_DIRECTORY = os.path.expanduser("~/.config/psiemu")
CFG_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "cfg")
CTRLR_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "ctrlr")
NVRAM_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "nvram")

CACHE_DIRECTORY = os.path.expanduser("~/.cache/psiemu")
ARTWORK_DIRECTORY = os.path.join(CACHE_DIRECTORY, "artwork")
ROM_DIRECTORY = os.path.join(CACHE_DIRECTORY, "roms")

os.makedirs(CONFIG_DIRECTORY, exist_ok=True)
os.makedirs(CTRLR_DIRECTORY, exist_ok=True)

os.makedirs(CACHE_DIRECTORY, exist_ok=True)
os.makedirs(ARTWORK_DIRECTORY, exist_ok=True)
os.makedirs(ROM_DIRECTORY, exist_ok=True)

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

HEADER = r"""
 ____      _ _____
|  _ \ ___(_) ____|_ __ ___  _   _
| |_) / __| |  _| | '_ ` _ \| | | |
|  __/\__ \ | |___| | | | | | |_| |
|_|   |___/_|_____|_| |_| |_|\__,_|

MAME Emulation Launcher for Psion Devices
"""[1:]
HEADER_LENGTH = len(HEADER.split("\n"))

PSION_LOGO = r"""
   _   _
  | |_| |
  \_____/
 _________
|_________|
"""[1:]
PSION_LOGO_LENGTH = len(PSION_LOGO.split("\n"))

DEFAULT_CONTROLLER_CONFIG = """
<?xml version="1.0"?>
<mameconfig version="10">
    <system name="default">
        <input>
            <port tag=":TOUCHX" type="P1_LIGHTGUN_X" mask="1023" defvalue="362">
                <newseq type="increment">NONE</newseq>
                <newseq type="decrement">NONE</newseq>
            </port>
            <port tag=":TOUCHY" type="P1_LIGHTGUN_Y" mask="511" defvalue="125">
                <newseq type="increment">NONE</newseq>
                <newseq type="decrement">NONE</newseq>
            </port>
        </input>
    </system>
</mameconfig>
"""[1:]
DEFAULT_CONTROLLER_CONFIG_PATH = os.path.join(CTRLR_DIRECTORY, "default.cfg")


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


def hash(path, method=hashlib.md5):
    hash = method()
    if os.path.isdir(path):
        for f in sorted(listdir(path, include_hidden=False)):
            hash.update(shasum(os.path.join(path, f)).encode('utf-8'))
    else:
        with open(path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                hash.update(data)
    return hash.hexdigest()


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
        "-ctrlrpath", CTRLR_DIRECTORY,
        "-artpath", ARTWORK_DIRECTORY,
        "-prescale", "%s" % (scale, ),
        "-resolution", "%dx%d" % (width * scale, height * scale),
        profile["id"],
    ]

    if "touchscreen" in profile and profile["touchscreen"]:
        command.extend([
            "-lightgun",
            "-mouse",
            "-ctrlr", "default",
        ])

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

    def render_device_section(devices, cursor, title_width, column_width, column_spacing, is_section_active, y_pos, selection):
        (height, width) = stdscr.getmaxyx()

        column_width = column_width + len(cursor) + column_spacing + 3
        column_count = math.floor((width - (title_width + column_spacing) + column_spacing) / column_width)
        section_height = 2  # Title

        for device_index, profile in enumerate(devices):
            title = profile["name"].ljust(title_width)
            variants = profile["variants"]
            section_height += math.ceil(len(variants) / column_count)

            stdscr.addstr(y_pos, 0, title)

            for variant_index, variant in enumerate(variants):
                if variant_index >= column_count:
                    y_pos += 1
                x_pos = (variant_index % column_count) * column_width
                name = variant["name"]
                languages = language_symbol(variant)
                is_selected = is_section_active and device_index == selection.device and variant_index == selection.variant
                cursor_string = cursor if is_selected else " " * len(cursor)
                name = f"{cursor_string} {name} {languages}"
                stdscr.addstr(y_pos, title_width + column_spacing + x_pos, name)

            y_pos += 1

        return section_height

    curses.use_default_colors()
    curses.curs_set(0)

    selection = Selection(0, 0, 0)
    status_text = None

    while True:

        # Determine the max title and column width.
        title_width = 0;
        column_width = 0
        for vendor in PROFILES:
            for device in vendor["devices"]:
                title_width = max(title_width, len(device["name"]))
                for variant in device["variants"]:
                    column_width = max(column_width, len(variant["name"]))

        (height, width) = stdscr.getmaxyx()
        stdscr.clear()

        stdscr.addstr(0, 0, HEADER)
        for i, line in enumerate(PSION_LOGO.split("\n")):
            stdscr.addstr(i, width-11, line)
        offset = HEADER_LENGTH

        for vendor_index, vendor in enumerate(PROFILES):
            stdscr.addstr(offset, 0, vendor["name"])
            offset += render_device_section(devices=vendor["devices"],
                                            cursor="->",
                                            title_width=title_width,
                                            column_width=column_width,
                                            column_spacing=2,
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
        render_footer("ent:run   c:copy command   q:quit", -2, curses.A_REVERSE)
        if status_text is not None:
            render_footer(status_text, -1)
            status_text = None
        else:
            languages = language_description(variant)
            status_components = []
            if "description" in variant:
                status_components.append(variant["description"])
            status_components.append(variant["year"])
            status_components.append(languages)
            render_footer("; ".join(status_components), -1)

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

    # Create the default controller configuration.
    with open(DEFAULT_CONTROLLER_CONFIG_PATH, "w") as fh:
        fh.write(DEFAULT_CONTROLLER_CONFIG)

    # Load the metadata from MAME.
    metadata = etree.fromstring(subprocess.check_output(["mame", "-listxml", "psion*", "siena*", "pocketbk*"]))

    # Update the configuration with metadata from MAME.
    for section in PROFILES:
        for device in section["devices"]:
            for variant in device["variants"]:
                machine = metadata.find(f".//machine[@name='{variant["id"]}']")
                year = metadata.find(".//year").text
                variant["year"] = machine.find(".//year").text
                display = machine.find(".//display")
                if "width" not in variant["display"]:
                    variant["display"]["width"] = int(display.get("width"))
                if "height" not in variant["display"]:
                    variant["display"]["height"] = int(display.get("height"))

    # Download ROMs.
    os.makedirs(ROM_DIRECTORY, exist_ok=True)
    for profile in PROFILES:
        for device in profile["devices"]:
            for variant in device["variants"]:
                if "roms" in variant:
                    device_directory = os.path.join(ROM_DIRECTORY, variant["id"] if "id" in variant else device["id"])
                    os.makedirs(device_directory, exist_ok=True)
                    for rom in variant["roms"]:
                        rom_path = os.path.join(device_directory, rom["name"])
                        rom_metadata = metadata.find(f".//machine[@name='{variant["id"]}']/rom[@name='{rom["name"]}']")
                        rom_sha = rom_metadata.get("sha1")
                        if os.path.exists(rom_path):
                            if hash(rom_path, hashlib.sha1) == rom_sha:
                                continue
                            os.remove(rom_path)
                        download(rom["url"], rom_path)
                if "artwork" in variant:
                    for artwork in variant["artwork"]:
                        artwork_path = os.path.join(ARTWORK_DIRECTORY, artwork["name"])
                        if os.path.exists(artwork_path):
                            if hash(artwork_path) == artwork["md5"]:
                                continue
                            os.remove(artwork_path)
                        download(artwork["url"], artwork_path)

    # Run.
    os.environ.setdefault('ESCDELAY', '25')
    curses.wrapper(lambda stdscr: device_picker(stdscr))


if __name__ == "__main__":
    main()
