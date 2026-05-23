# PsiEmu

Lightweight TUI launcher for Psion MAME emulators.

![](images/preview.gif)

## Usage

```sh
git clone ssh://git@codeberg.org/psion/psiemu.git
cd psiemu

export PSIEMU_ROM_PATH=~/path/to/roms
./psiemu
```

## Development

Print specific details of MAME systems using `-listroms` and `-listbios`. For exmaple,

```sh
$ mame psion3mx_fr -listbios                                              Chii
BIOS options for system Series 3mx (French) (psion3mx_fr):
    620f             V6.20F/FRE
$  mame psion3mx_fr -listroms                                              Chii
ROMs required for driver "psion3mx_fr".
Name                                   Size Checksum
maple_v6.20f_fre.bin                2097152 CRC(b4fc57f4) SHA1(26588937d811adf08b973a0188927707d1f6a6e4)
```
