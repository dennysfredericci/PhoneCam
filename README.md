# PhoneCam

Use your phone's camera as a 1080p webcam on your Mac, in Zoom, Teams, Google Meet,
OBS, or any app that can pick a camera. It's a free, self-hosted alternative to Camo:
no app on the phone, just a web page.

```
iPhone Safari / Android Chrome  --WebRTC (H.264, same Wi-Fi)-->  PhoneCam on the Mac  -->  "OBS Virtual Camera"  -->  Zoom / Teams / Meet / OBS
```

- The Mac serves a page over HTTPS. Phones only allow camera access on secure pages.
- The phone streams to the Mac with WebRTC: H.264 (hardware-encoded on the phone),
  up to 1920x1080 at 30 fps and 8 Mbps.
- If direct UDP can't reach the Mac, the video falls back to PhoneCam's own relay
  over TCP (TURN, port 3478). For example, this happens when the Mac is on the
  iPhone's Personal Hotspot. No internet servers are involved.
- PhoneCam always outputs 1920x1080 at 30 fps. Portrait video gets black side bars
  instead of being stretched, and the picture is black while no phone is connected.

## Requirements

- A Mac with **Apple Silicon** (M1, M2, M3, M4...) on macOS 14 or newer, or an **Intel** Mac on
  macOS 13 or newer.
- **OBS Studio 30 or newer** ([obsproject.com](https://obsproject.com)). PhoneCam uses its
  virtual camera driver. OBS does not need to be running while you use PhoneCam.
- An iPhone with Safari or an Android phone with Chrome, on the **same Wi-Fi** as the Mac.
  If the Mac is connected to the iPhone's **Personal Hotspot**, that works too, through the relay.

### One-time setup: enable the OBS Virtual Camera

1. Install OBS and open it.
2. Click **Start Virtual Camera** (bottom right), then **Stop Virtual Camera**.
3. If macOS asks, allow the camera extension in **System Settings > General > Login Items &
   Extensions > Camera Extensions** (on macOS 13/14: **Privacy & Security**).
4. Quit OBS, or at least keep its own Virtual Camera **stopped** while PhoneCam runs:
   only one program can feed the virtual camera at a time.

## Install PhoneCam

1. Find your Mac's type: Apple menu > **About This Mac**. "Chip: Apple M..." means Apple Silicon,
   and "Processor: Intel" means Intel.
2. Download the matching zip from the
   [latest release](https://github.com/dennysfredericci/PhoneCam/releases/latest):
   `PhoneCam-x.y.z-apple-silicon.zip` or `PhoneCam-x.y.z-intel.zip`.
3. Unzip it and drag **PhoneCam.app** into **Applications**.

### Opening it the first time

PhoneCam isn't signed with a paid Apple Developer ID, so macOS blocks the first launch.
You only need to allow it once:

- **macOS 15 (Sequoia) or newer:** double-click PhoneCam. When macOS says it can't verify the app,
  click **Done**. Open **System Settings > Privacy & Security**, scroll down to the message about
  PhoneCam, click **Open Anyway**, and confirm with your password.
- **macOS 13 or 14:** right-click (or Control-click) PhoneCam in Applications, choose **Open**,
  then click **Open** in the dialog.
- **Or, in Terminal**, on any version: `xattr -dr com.apple.quarantine /Applications/PhoneCam.app`

When PhoneCam starts, macOS may also ask whether it may accept incoming network connections and
find devices on your local network. Allow both, because the phone connects over the network.

## Using PhoneCam

PhoneCam lives in the **menu bar** as a video camera icon. There's no Dock icon. The icon is filled
while a phone is streaming, and shows a warning triangle if something needs attention. Click it to see:

- the status, for example *Waiting for phone* or *Connected to 192.168.1.30*, and while
  streaming, what's arriving, for example *1920×1080 · 30 fps · 6.2 Mbps* (plus *via TCP relay*
  when the fallback is used);
- the URL to open on the phone, and the **PIN**. Click either one to copy it;
- **Show QR Code**: scan it with the phone's camera. It opens the page with the PIN already
  filled in;
- **Change PIN...**: set your own PIN or a new random one (see [PIN](#pin));
- **Start at Login**: tick it to start PhoneCam automatically. If macOS asks, switch PhoneCam on
  in System Settings > General > Login Items;
- **Open Log Folder** and **Quit PhoneCam**.

## Run from source (development)

Requires Python 3.12 or newer. Only the Mac you develop or build on needs Python; the app bundles its own.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m phonecam              # serve the phone page (port 8443)
.venv/bin/python -m phonecam --port 9443  # another port
.venv/bin/python -m phonecam --test-pattern  # check the virtual camera without a phone
.venv/bin/python -m phonecam --debug     # log every WebRTC connection check
.venv/bin/python -m phonecam --menubar   # the menu-bar version, as in PhoneCam.app
.venv/bin/python -m phonecam --self-test # check that all libraries work
```

In the terminal version, PhoneCam prints the URL to open on the phone, for example
`https://192.168.1.20:8443`, and the **PIN**.

The certificate, `settings.json` and `phonecam.log` are in `~/Library/Application Support/PhoneCam`.
`settings.json` looks like `{"port": 8443, "turn_port": 3478, "pin": "042917"}`.

### PIN

Anyone on the same Wi-Fi can open the page, so streaming needs a PIN. Without it, someone
could replace your video with their camera. They could never *see* your camera, because
video only goes from the phone to the Mac.

- A random 6-digit PIN is created on first run. It's shown in the menu bar, or printed in the terminal version.
- The phone asks for it once and remembers it. If it's wrong or you change it, the phone asks again.
- After 5 wrong tries, that address is locked out for 60 seconds.
- To change it, choose **Change PIN...** in the menu bar. Type a new PIN (4–12 digits), or click
  **Random**. It applies immediately: the phone streaming now keeps streaming, and phones that
  connect from then on need the new PIN.
- You can also edit `"pin"` in `settings.json` and restart PhoneCam. `"pin": ""` turns protection off.

## Connect your phone

Scan the QR code from the menu bar, or open the URL shown there in **Safari** (iPhone) or
**Chrome** (Android). The first time,
the browser warns about the certificate. PhoneCam creates its own certificate, so this warning is
expected. You'll see it again only when the Mac's IP address changes, because PhoneCam then
creates a new certificate.

**iPhone (Safari)**
1. On "This Connection Is Not Private", tap **Show Details**, then **visit this website**,
   then **Visit Website**.
2. Tap **Start**, then **Allow** camera access. Enter the **PIN** if asked; the QR code
   fills it in for you.

**Android (Chrome)**
1. On "Your connection is not private", tap **Advanced**, then **Proceed to 192.168.x.x (unsafe)**.
2. Tap **Start**, then **Allow** camera access. Enter the **PIN** if asked; the QR code
   fills it in for you.

The page shows the connection state and the actual resolution, frame rate, bitrate and codec
being sent. **Flip camera** switches between the front and back cameras, and the screen stays on
while you stream. If a second phone taps Start, it takes over, and the first phone stops.

## Pick the camera in your apps

Select **OBS Virtual Camera** as the camera:

- **Zoom**: Settings > Video > Camera.
- **Microsoft Teams**: Settings > Devices > Camera.
- **Google Meet** (browser): Settings > Video > Camera. The browser may ask for camera permission.
- **OBS**: add a source **Video Capture Device**, then pick **OBS Virtual Camera**.

If an app was already open when you set up the OBS Virtual Camera, restart that app once.

### Tests

```bash
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests run real WebRTC calls with aiortc playing the phone, plus the PIN, the TCP relay and
the image fitting. They use a temporary home folder, so they never touch your real settings or
certificate. CI runs them on both CPU types before building.

`tests/test_page.py` drives the real phone page in headless Google Chrome with a fake camera. It
only runs when `PHONECAM_BROWSER_TESTS=1` is set, which CI does. Locally it's skipped by default,
because launching Chrome from a test can trigger macOS dialogs (for example about the keychain).

## Build the app

`build.sh` builds `PhoneCam.app` for the CPU type of the Mac it runs on. It needs Python 3.12 or
newer on that Mac, and nothing else.

```bash
./build.sh                                   # uses python3 from PATH
PYTHON=/path/to/python3.14 ./build.sh        # or a specific Python
```

It creates a clean venv in `.build-venv/`, installs the pinned `requirements.txt` and
`requirements-build.txt`, and runs PyInstaller with `PhoneCam.spec`. Then it checks that no
library in the bundle points outside the app or macOS, verifies the code signature, and runs the
app's `--self-test` in an empty environment: a full WebRTC/H.264 call inside the app, no OBS needed.
The output is `dist/PhoneCam.app` and `dist/PhoneCam-<version>-<apple-silicon|intel>.zip`.

The app can't be "universal" (one download for both CPU types), because PyAV, the video
library, ships separate Apple Silicon and Intel builds. That's why there are two zips.

### Releases (GitHub Actions)

`.github/workflows/build.yml` builds both versions on every push, on GitHub's Apple Silicon
(`macos-15`) and Intel (`macos-15-intel`) runners. The zips appear under the run's
**Artifacts**. To publish a release:

1. Set the version in `phonecam/__init__.py`, for example `__version__ = "0.2.0"`, and push it.
2. Tag that commit and push the tag: `git tag v0.2.0 && git push origin v0.2.0`.

The workflow then creates the GitHub Release with both zips. It refuses to publish if the tag
doesn't match `__version__`.

### Check that the app doesn't need Python

On the Mac where you want to verify it, preferably one without Homebrew:

1. Check what's installed. `ls /opt/homebrew /usr/local/bin/python3 /Library/Frameworks/Python.framework`
   should report "No such file" for each one. `/usr/bin/python3` exists on every Mac; it's
   Apple's installer stub for the Command Line Tools, and PhoneCam never uses it.
2. Run the self-test: `/Applications/PhoneCam.app/Contents/MacOS/PhoneCam --self-test` should end with
   **Self-test passed.**
3. Open PhoneCam normally, then list any libraries it loaded from outside the app and macOS:
   ```bash
   lsof -c PhoneCam | grep -E '\.(so|dylib)$' | grep -v -E 'PhoneCam\.app|/usr/lib/|/System/'
   ```
   This should print **nothing**.

## Troubleshooting

**The phone can't open the page / "can't reach the Mac"**
- **Firewall:** when PhoneCam starts, macOS may ask whether to accept incoming connections.
  Click **Allow**. If you clicked Deny, go to System Settings > Network > Firewall > Options
  and set Python (or PhoneCam) to *Allow incoming connections*.
- **Local Network (macOS 15+):** if asked whether Terminal (or PhoneCam) may find devices on your
  local network, click **Allow**. To change it later: System Settings > Privacy & Security >
  Local Network.
- **Different networks:** the phone must be on the same Wi-Fi as the Mac, not on mobile data,
  and not on a "guest" network. Guest networks often block devices from reaching each other.
  Some office networks also block device-to-device traffic.
- Check that the IP in the URL matches the one PhoneCam printed. It changes when the Mac joins
  another network.

**The page loads, but it stays on "Connecting" or "Reconnecting"**
- The video can't find a path to the Mac. PhoneCam's TCP relay on port **3478** should handle this
  automatically. Check that the log shows `TURN relay (TCP) listening on port 3478`. If another
  program uses that port, change `turn_port` in `settings.json`.
- To test the relay path on purpose, open the URL with `?relay` added, for example
  `https://192.168.1.20:8443/?relay`. The stats line then says **via TCP relay**.
- Start PhoneCam with `--debug` and look in the log for the `Phone candidates` and
  `Mac candidates` lines.

**Black image in Zoom/Teams/Meet**
- Black is what PhoneCam shows when no phone is connected. Check that the phone says **Live on Mac**.
- Check that the app's camera is set to **OBS Virtual Camera**, and that OBS's own Virtual Camera
  is stopped.
- Restart the call app if it was open before the virtual camera was set up.

**Low resolution, blur or lag**
- Use **5 GHz** Wi-Fi and stay close to the router. 2.4 GHz is often too slow or crowded for 1080p.
- Hold the phone in **landscape**. In portrait, the picture is narrower and has black bars.
- Keep the phone **on a charger**. Hot phones slow down their encoder.
- If the stats line says "limited by bandwidth", the Wi-Fi is the bottleneck. If it says
  "limited by cpu", the phone is throttling.

**The phone keeps asking for the PIN, or says "Too many wrong PINs"**
- Use the PIN that PhoneCam printed, or the one in `settings.json`. After 5 wrong tries,
  wait one minute.

**"Camera access is blocked" on the phone**
- iPhone: tap **aA** in the address bar > Website Settings > Camera > Allow, then reload.
- Android: tap the icon left of the address > Permissions > Camera > Allow, then reload.

Logs: `~/Library/Application Support/PhoneCam/phonecam.log`.
