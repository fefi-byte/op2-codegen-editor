"""Orchestriert: Mission-Modell -> LevelMain.cpp -> msbuild -> Mission-DLL.

Schreibt den generierten C++-Code in das (bewiesene) LevelTemplate-Projekt
und ruft msbuild ueber die VS-Entwicklerumgebung auf.

Orchestrates: mission model -> LevelMain.cpp -> msbuild -> mission DLL.

Writes the generated C++ code into the (proven) LevelTemplate project
and invokes msbuild through the VS developer environment.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import appconfig
from codegen import generate_levelmain
from demo_mission import build_demo

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "LevelTemplate"
LEVELMAIN = TEMPLATE / "LevelMain.cpp"
VCXPROJ = TEMPLATE / "OP2Script.vcxproj"


def write_levelmain(cpp: str) -> None:
    # Original einmalig sichern, damit das Template wiederherstellbar bleibt.
    # Back up the original once so the template stays restorable.
    backup = TEMPLATE / "LevelMain.cpp.orig"
    if not backup.exists() and LEVELMAIN.exists():
        shutil.copy2(LEVELMAIN, backup)
    LEVELMAIN.write_text(cpp, encoding="utf-8")
    print(f"[ok] LevelMain.cpp geschrieben ({len(cpp)} Zeichen)")


def build() -> Path:
    if sys.platform != "win32":
        raise SystemExit(
            "[FEHLER] Der Legacy-msbuild-Pfad (build()) laeuft nur unter Windows.\n"
            "Benutze build_folder() fuer den CMake-basierten Build (auch auf Linux)."
        )
    vsdevcmd = appconfig.vsdevcmd()
    if not vsdevcmd.exists():
        raise SystemExit(
            f"[FEHLER] VsDevCmd.bat nicht gefunden:\n{vsdevcmd}\n"
            f"Bitte 'msvs_path' in der config.ini anpassen:\n{appconfig.CONFIG_PATH}")
    props = "/p:Configuration=Release /p:Platform=Win32"
    if appconfig.platform_toolset():
        props += f" /p:PlatformToolset={appconfig.platform_toolset()}"
    if appconfig.windows_sdk():
        props += f" /p:WindowsTargetPlatformVersion={appconfig.windows_sdk()}"
    cmd = (
        f'"{vsdevcmd}" -arch=x86 >nul 2>&1 && '
        f'msbuild "{VCXPROJ}" {props} /v:minimal /nologo'
    )
    print("[..] msbuild laeuft ...")
    # Outpost2Path aus der Umgebung entfernen, damit der Post-Build-Schritt des
    # Templates NICHT zusaetzlich ctest.dll in den OP2-Ordner kopiert.
    # (Die DLL wird stattdessen vom Editor an den gewuenschten Ort gelegt.)
    # Remove Outpost2Path from the environment so the template's post-build step
    # does NOT additionally copy ctest.dll into the OP2 folder.
    # (Instead the DLL is placed at the desired location by the editor.)
    env = {k: v for k, v in os.environ.items() if k.lower() != "outpost2path"}
    # shell=True: cmd-String direkt an cmd.exe geben, damit die verschachtelten
    # Anfuehrungszeichen korrekt ankommen (Liste + cmd /c verstuemmelt sie).
    # shell=True: pass the cmd string directly to cmd.exe so the nested
    # quotes arrive correctly (a list + cmd /c would mangle them).
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise SystemExit(f"[FEHLER] Build fehlgeschlagen (Code {result.returncode})")

    dll = next((TEMPLATE / "Release").glob("*.dll"), None)
    if not dll:
        raise SystemExit("[FEHLER] Keine DLL im Release-Ordner gefunden")
    print(f"[ok] DLL: {dll}  ({dll.stat().st_size} Bytes)")
    return dll


def _find_cmake() -> str:
    """Sucht cmake -- PATH zuerst, auf Windows zusaetzlich VS-Installationen."""
    p = shutil.which("cmake")
    if p:
        return p
    if sys.platform == "win32":
        candidates = []
        for vs_year in ("18", "17", "16"):
            for edition in ("Community", "Professional", "Enterprise", "BuildTools"):
                candidates.append(
                    Path("C:/Program Files/Microsoft Visual Studio") / vs_year / edition
                    / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
                )
        candidates.append(Path("C:/Program Files/CMake/bin/cmake.exe"))
        candidates.append(Path("C:/Program Files (x86)/CMake/bin/cmake.exe"))
        for c in candidates:
            if c.exists():
                return str(c)
    raise SystemExit(
        "[FEHLER] cmake nicht gefunden.\n"
        "Windows: CMake installieren oder Visual Studio mit C++/CMake-Komponente.\n"
        "Linux:   sudo apt install cmake  (Debian/Ubuntu)"
    )


def _find_make_tool() -> tuple[str, str]:
    """Gibt (cmake-Generator, make-Programm) fuer Linux zurueck.

    Bevorzugt Ninja (schneller), faellt auf GNU make zurueck.
    """
    for prog, generator in (
        ("ninja", "Ninja"),
        ("ninja-build", "Ninja"),
        ("make", "Unix Makefiles"),
        ("gmake", "Unix Makefiles"),
    ):
        p = shutil.which(prog)
        if p:
            return generator, p
    raise SystemExit(
        "[FEHLER] Weder ninja noch make gefunden.\n"
        "Bitte eines installieren:\n"
        "  Debian/Ubuntu: sudo apt install ninja-build\n"
        "  Arch/SteamDeck: sudo pacman -S ninja\n"
        "  Fedora:        sudo dnf install ninja-build"
    )


def _find_mingw32() -> tuple[str, str, str]:
    """Sucht den MinGW i686-w64-mingw32 Cross-Compiler (fuer Linux-Host).

    Gibt (cc, cxx, windres) zurueck. windres kann leer sein wenn nicht gefunden
    (CMake faellt dann auf einen generischen RC-Compiler zurueck).
    """
    for prefix in ("i686-w64-mingw32", "i686-mingw32"):
        cc = shutil.which(f"{prefix}-gcc")
        cxx = shutil.which(f"{prefix}-g++")
        if cc and cxx:
            rc = shutil.which(f"{prefix}-windres") or ""
            return cc, cxx, rc
    raise SystemExit(
        "[FEHLER] i686-w64-mingw32-gcc nicht gefunden.\n"
        "Bitte MinGW-w64 installieren:\n"
        "  Debian/Ubuntu: sudo apt install mingw-w64\n"
        "  Fedora:        sudo dnf install mingw32-gcc-c++\n"
        "  Arch:          sudo pacman -S mingw-w64-gcc"
    )


def build_folder(folder: Path) -> Path:
    """Baut eine TitanAPI-Mission via CMake.

    Erwartet `CMakeLists.txt` direkt im Ordner. Gibt den Pfad zur erzeugten DLL
    zurueck. Unterstuetzt Windows (MSVC via Visual Studio Generator) und Linux
    (MinGW i686-w64-mingw32 Cross-Compiler).
    """
    folder = Path(folder)
    cmakelists = folder / "CMakeLists.txt"
    if not cmakelists.exists():
        raise SystemExit(f"[FEHLER] CMakeLists.txt nicht gefunden: {cmakelists}")

    cmake = _find_cmake()
    build_dir = folder / "build"
    env = {k: v for k, v in os.environ.items() if k.lower() != "outpost2path"}

    # Stale CMakeCache.txt (z.B. von einem früheren Build auf einem anderen OS)
    # führt zu Pfadkonflikten. Build-Ordner vor dem Configure immer löschen.
    if (build_dir / "CMakeCache.txt").exists():
        shutil.rmtree(build_dir)

    print(f"[..] cmake configure fuer {folder.name} ...")

    if sys.platform == "win32":
        configure_cmd = [
            cmake, "-S", str(folder), "-B", str(build_dir),
            "-G", "Visual Studio 18 2026", "-A", "Win32",
        ]
        build_cmd = [cmake, "--build", str(build_dir), "--config", "Release"]
        dll_dirs = [build_dir / "Release", build_dir]
    else:
        cc, cxx, rc = _find_mingw32()
        generator, make_prog = _find_make_tool()
        configure_cmd = [
            cmake, "-S", str(folder), "-B", str(build_dir),
            "-G", generator,
            f"-DCMAKE_MAKE_PROGRAM={make_prog}",
            f"-DCMAKE_C_COMPILER={cc}",
            f"-DCMAKE_CXX_COMPILER={cxx}",
            "-DCMAKE_SYSTEM_NAME=Windows",
            "-DCMAKE_BUILD_TYPE=Release",
        ]
        if rc:
            configure_cmd.append(f"-DCMAKE_RC_COMPILER={rc}")
        build_cmd = [cmake, "--build", str(build_dir)]
        dll_dirs = [build_dir, build_dir / "Release"]

    res = subprocess.run(configure_cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        details = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()[-3000:] or "(keine cmake-Ausgabe)"
        raise SystemExit(
            f"[FEHLER] cmake configure fehlgeschlagen (Code {res.returncode})\n\n"
            f"cmake-Ausgabe (letzte Zeilen):\n{details}"
        )

    print(f"[..] cmake --build (Release) fuer {folder.name} ...")
    res = subprocess.run(build_cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        details = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()[-3000:] or "(keine cmake-Ausgabe)"
        raise SystemExit(
            f"[FEHLER] cmake build fehlgeschlagen (Code {res.returncode})\n\n"
            f"cmake-Ausgabe (letzte Zeilen):\n{details}"
        )

    dll = None
    for d in dll_dirs:
        if d.is_dir():
            dll = next(d.glob("*.dll"), None)
            if dll:
                break
    if not dll:
        raise SystemExit(f"[FEHLER] Keine DLL gefunden unter: {build_dir}")
    print(f"[ok] DLL: {dll}  ({dll.stat().st_size} Bytes)")
    return dll


def main() -> None:
    mission = build_demo()
    cpp = generate_levelmain(mission)
    write_levelmain(cpp)
    build()


if __name__ == "__main__":
    main()
