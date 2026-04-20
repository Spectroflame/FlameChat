# FlameChat

A fully local, accessibility-first AI chat client for conversations and coding.
Runs on macOS, Windows and Linux. The only times the app talks to the
internet are: fetching the Ollama binary on first launch, and fetching a
language model when you explicitly click download. Everything else stays
on your machine.

## Features

- Native UI via wxPython — VoiceOver (macOS), NVDA (Windows) and Orca (Linux)
  read it out of the box.
- Private Ollama subprocess managed by the app — downloads the binary on
  first launch, nothing is installed system-wide, no admin / sudo.
- Automatic hardware detection (RAM, CPU, NVIDIA / AMD / Apple Silicon GPU)
  with model recommendations sized for your machine.
- Clear speaker separation: every message is prefixed with `Du:` or
  `Assistant:` on its own line in the transcript.
- WhatsApp-style send sound and a soft bell on incoming messages.
- Streaming responses (shown in the status line, flushed to the transcript
  in one go so screen readers do not re-read partial text).

## For end users — download a ready-made build

No Python, no terminal, no Ollama install. Grab the build for your OS
from the Releases page:

- **macOS**: `FlameChat-<version>.dmg` → drag FlameChat to `/Applications`.
- **Windows**: `FlameChat-<version>-win64.zip` → extract, run
  `FlameChat.exe`.
- **Linux**: `FlameChat-<version>-x86_64.AppImage` → `chmod +x` it, then
  double-click.

On the very first launch FlameChat downloads Ollama automatically (about
~300 MB) into its own app data folder and starts it as a private
subprocess. Nothing is installed system-wide. When you quit FlameChat,
the Ollama subprocess quits with it.

## For developers — run from source

Python 3.10 or newer is required.

```bash
git clone <this-repo> FlameChat
cd FlameChat
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
flamechat
```

wxPython ships native wheels for recent Python versions on macOS, Windows
and most Linux distributions. If `pip install` has to build wxPython from
source on Linux, install the GTK 3 / WebKit2GTK development headers first
(see the [wxPython install guide](https://wxpython.org/pages/downloads/)).

## Building the installers

All three platforms share one PyInstaller spec at `flamechat.spec`.
Release builds are produced in CI (GitHub Actions) so the build
environment stays reproducible and signing keys can live in the
repository secrets instead of someone's laptop. For a local developer
build you can invoke PyInstaller directly:

```bash
pip install pyinstaller
python -m PyInstaller flamechat.spec --clean --noconfirm
# dist/FlameChat.app on macOS, dist/FlameChat/FlameChat(.exe) elsewhere
```

Unsigned local builds trigger Gatekeeper / SmartScreen warnings on
first launch; that's expected. For public distribution the CI build
signs (macOS `productsign` + notarize, Windows Authenticode) and wraps
the result (DMG, AppImage, portable zip).

## Keyboard

| Action                  | Shortcut                       |
| ----------------------- | ------------------------------ |
| Send message            | Ctrl+Enter (Cmd+Enter on macOS) |
| New line in input       | Enter                          |
| New chat                | Ctrl+N                         |
| Manage models           | Ctrl+M                         |
| Quit                    | Ctrl+Q                         |

## Accessibility notes

Every control has an explicit accessible name set via `SetName()`; wxPython
maps these to the underlying platform APIs (NSAccessibility, UIA, AT-SPI).

The transcript is a single read-only multi-line text control rather than a
custom list, so screen-reader users can navigate it the same way they would
a document — by character, word, line, or screen — using the shortcuts they
already know.

During generation, the send button is disabled and the status line is
updated. The transcript is written in one shot once generation completes,
so screen readers are not forced to re-read the growing response.

The two short WAV files (`send.wav`, `receive.wav`) are generated once by
`scripts/generate_sounds.py` using only the Python standard library and
shipped with the package. Sounds can be toggled off via the `View` menu.

## Privacy

Network destinations used by the app:

| Component          | Network? | Destination                                 | When                                         |
| ------------------ | :------: | ------------------------------------------- | -------------------------------------------- |
| UI / chat panel    |    No    | —                                           | —                                            |
| Ollama client      |    Yes   | `http://127.0.0.1:11434`                    | every request — loopback only                |
| Ollama subprocess setup | Yes | `github.com/ollama/ollama/releases/latest`  | once, on first launch                        |
| Model download     |    Yes   | Ollama's CDN (through the Ollama subprocess) | only when you click "Download" in the dialog |

There is no telemetry, no crash reporter, no auto-update check.

### Why HTTP on localhost, not HTTPS?

TLS protects data in transit against a network attacker. On the loopback
interface there is no network — packets go through the kernel back to the
same machine, never touching a NIC, a router or a cable. An attacker with
code-execution on your machine already has far stronger options than
sniffing loopback traffic, and Ollama does not serve HTTPS by default.
Adding TLS here would be complexity without a threat model.

### Localhost is enforced, not assumed

On startup, FlameChat resolves the configured Ollama host and refuses to
start if any resolved address is not a loopback address (`127.0.0.0/8` or
`::1`). This blocks foot-guns such as a stray or malicious `OLLAMA_HOST`
env var pointing to a remote server. The live bound URL is shown in the
toolbar so you can see at a glance that the connection is local.

## Layout

```
src/flamechat/
  __main__.py          # entry point
  app.py               # wx.App + MainFrame
  ui/
    chat_panel.py      # transcript + input + send
    model_dialog.py    # hardware summary + recommendations + pull
    sounds.py          # wx.adv.Sound wrapper
  backend/
    hardware.py        # RAM / CPU / GPU detection
    recommendations.py # hardware -> shortlist of Ollama models
    ollama_client.py   # HTTP client (list / pull / chat)
  assets/
    send.wav
    receive.wav
scripts/
  generate_sounds.py   # regenerate the two WAV files
```

## License

MIT.
