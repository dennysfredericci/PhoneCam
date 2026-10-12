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

- macOS 13 or newer, on Intel or Apple Silicon.
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

## Run from source (development)

Requires Python 3.12 or newer on the Mac where you develop. The finished app (Phase 2) won't need Python.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m phonecam              # serve the phone page (port 8443)
.venv/bin/python -m phonecam --port 9443  # another port
.venv/bin/python -m phonecam --test-pattern  # check the virtual camera without a phone
.venv/bin/python -m phonecam --debug     # log every WebRTC connection check
```

PhoneCam prints the URL to open on the phone, for example `https://192.168.1.20:8443`, and the **PIN**.

The certificate, `settings.json` and `phonecam.log` are in `~/Library/Application Support/PhoneCam`.
`settings.json` looks like `{"port": 8443, "turn_port": 3478, "pin": "042917"}`.

### PIN

Anyone on the same Wi-Fi can open the page, so streaming needs a PIN. Without it, someone
could replace your video with their camera. They could never *see* your camera, because
video only goes from the phone to the Mac.

- A random 6-digit PIN is created on first run and printed at startup.
- The phone asks for it once and remembers it. If it's wrong or you change it, the phone asks again.
- After 5 wrong tries, that address is locked out for 60 seconds.
- To change the PIN, edit `"pin"` in `settings.json` and restart PhoneCam.
  `"pin": ""` turns protection off.

## Connect your phone

Open the URL that PhoneCam prints, in **Safari** (iPhone) or **Chrome** (Android). The first time,
the browser warns about the certificate. PhoneCam creates its own certificate, so this warning is
expected. You'll see it again only when the Mac's IP address changes, because PhoneCam then
creates a new certificate.

**iPhone (Safari)**
1. On "This Connection Is Not Private", tap **Show Details**, then **visit this website**,
   then **Visit Website**.
2. Tap **Start**, then **Allow** camera access, then enter the **PIN** (only the first time).

**Android (Chrome)**
1. On "Your connection is not private", tap **Advanced**, then **Proceed to 192.168.x.x (unsafe)**.
2. Tap **Start**, then **Allow** camera access, then enter the **PIN** (only the first time).

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
