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
import hashlib
import os
import shutil
import subprocess
import tempfile

import pyclip
import requests
import yaml

from dataclasses import dataclass
from lxml import etree
from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widget import Widget, Text
from textual.widgets import Tree, Placeholder, Label, Static

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
"""[1:]

DESCRIPTION = "MAME Emulation Launcher for Psion Devices"

PSION_LOGO = r"""
   _   _
  | |_| |
  \_____/
 _________
|_________|
"""[1:]

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


def language_description(variant):
    return ", " .join([LANGUAGES[language]["name"] for language in variant["languages"]])


def variant_description(variant):
    languages = language_description(variant)
    status_components = []
    if "description" in variant:
        status_components.append(variant["description"])
    status_components.append(variant["year"])
    status_components.append(languages)
    return "; ".join(status_components)


class Header(Vertical):

    DEFAULT_CSS = """
    Header {
        height: 7;
        dock: top;
        margin-bottom: 1;
    }
    #Title {
        width: 1fr;
    }
    #Logo {
        width: auto;
    }
    """

    def compose(self):
        with Horizontal():
            yield Label(HEADER, id="Title")
            yield Label(PSION_LOGO, id="Logo")
        yield Label(DESCRIPTION)


class KeyboardShortcuts(Widget):

    DEFAULT_CSS = """
    KeyboardShortcuts {
        height: 1;
        text-style: reverse;
    }
    """

    def __init__(self, text, **kwargs):
        super().__init__(**kwargs)
        self.text = text

    def render(self):
        return Text(self.text.ljust(self.size.width))


# TODO: Rename to Footer.
class Footer(Vertical):

    DEFAULT_CSS = """
    Footer {
        height: 2;
        dock: bottom;
        width: 1fr;
    }
    """

    def compose(self):
        yield KeyboardShortcuts("ent:run   c:copy command   q:quit", id="Shortcuts")
        yield Static(id="Description", markup=False)

    def update(self, text):
        self.query_one("#Description", Static).update(text)


class TreeApp(App):

    BINDINGS = [
        ("c", "copy", "Copy command"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, sections):
        self.sections = sections
        super().__init__()

    def compose(self) -> ComposeResult:

        tree: Tree[str] = Tree("Vendors")
        tree.show_root = False
        tree.root.expand()
        for vendor_index, vendor in enumerate(self.sections):
            vendor_node = tree.root.add(vendor["name"])
            for profile in vendor["devices"]:
                device_node = vendor_node.add(profile["name"])
                for variant_index, variant in enumerate(profile["variants"]):
                    device_node.add_leaf(f"{variant["name"]} ({language_description(variant)})", data=variant)

        yield Header()
        yield tree
        yield Footer()

    def on_mount(self):
        self.theme = "ansi-dark"
        tree = self.query_one(Tree)
        tree.call_after_refresh(tree.move_cursor, tree.root.children[0])

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        variant = event.node.data
        self.query_one(Footer).update(variant_description(variant) if variant is not None else "")

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        variant = event.node.data
        if variant is None:
            return
        run_mame(variant)

    def action_copy(self) -> None:
        variant = self.query_one(Tree).cursor_node.data
        if variant is None:
            return
        pyclip.copy(" ".join(mame_command(variant)))
        self.query_one(Footer).update("Command line copied to clipboard")


def main():
    parser = argparse.ArgumentParser()
    options = parser.parse_args()

    with open(PROFILES_PATH) as fh:
        profiles = yaml.safe_load(fh)

    # Create the default controller configuration.
    with open(DEFAULT_CONTROLLER_CONFIG_PATH, "w") as fh:
        fh.write(DEFAULT_CONTROLLER_CONFIG)

    # Load the metadata from MAME.
    metadata = etree.fromstring(subprocess.check_output(["mame", "-listxml", "psion*", "siena*", "pocketbk*"]))

    # Update the configuration with metadata from MAME.
    for section in profiles:
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
    for profile in profiles:
        for device in profile["devices"]:
            for variant in device["variants"]:
                if "roms" in variant:
                    device_directory = os.path.join(ROM_DIRECTORY, variant["id"] if "id" in variant else device["id"])
                    os.makedirs(device_directory, exist_ok=True)
                    for rom_name, rom_url in variant["roms"].items():
                        rom_path = os.path.join(device_directory, rom_name)
                        rom_metadata = metadata.find(f".//machine[@name='{variant["id"]}']/rom[@name='{rom_name}']")
                        rom_sha = rom_metadata.get("sha1")
                        if os.path.exists(rom_path):
                            if hash(rom_path, hashlib.sha1) == rom_sha:
                                continue
                            os.remove(rom_path)
                        download(rom_url, rom_path)
                if "artwork" in variant:
                    for artwork in variant["artwork"]:
                        artwork_path = os.path.join(ARTWORK_DIRECTORY, artwork["name"])
                        if os.path.exists(artwork_path):
                            if hash(artwork_path) == artwork["md5"]:
                                continue
                            os.remove(artwork_path)
                        download(artwork["url"], artwork_path)

    # Run.
    app = TreeApp(sections=profiles)
    app.run(mouse=False)


if __name__ == "__main__":
    main()
