# e-Paper Dashboard — Setup

Home Assistant dashboard for Waveshare 7.5" V2 e-Paper display (800×480) in portrait mode.  
Displays indoor room temperature/humidity, outdoor weather, and 4-day forecast.

## File structure

```
epaper-dashboard/
├── ha_epaper_dashboard.py      # main script (safe to commit)
├── config.json.example         # rooms/entities template (safe to commit)
├── config.json                 # your configuration (safe to commit, no secrets)
├── secrets.json.example        # credentials template (safe to commit)
├── secrets.json                # your HA credentials (DO NOT commit)
├── .gitignore                  # excludes secrets.json
├── epaper-dashboard.service    # systemd unit
└── epaper-dashboard.timer      # systemd timer (5 min refresh)
```

## 1. Dependencies

```bash
sudo apt install python3-pil python3-numpy python3-rpi.gpio python3-spidev
git clone https://github.com/waveshare/e-Paper ~/e-Paper
```

## 2. Setup

```bash
cd /home/pi
git clone <your-repo> epaper-dashboard
cd epaper-dashboard

cp secrets.json.example secrets.json
cp config.json.example config.json

nano secrets.json   # HA credentials (gitignored)
nano config.json    # rooms and entities
```

## 3. secrets.json

```json
{
    "ha_url": "http://192.168.1.X:8123",
    "ha_token": "eyJhbGciOi..."
}
```

To create a Long-Lived Access Token:  
HA → User profile → Long-lived access tokens → Create token

## 4. config.json

Available room icons: `kitchen`, `livingroom`, `bedroom`, `childroom`, `bathroom`, `laundry`, `storage`

## 5. Test

```bash
# PNG preview with demo data (no HA, no e-paper)
python3 ha_epaper_dashboard.py --simulate --demo --output preview.png

# PNG preview with live HA data (no e-paper)
python3 ha_epaper_dashboard.py --simulate --output preview.png

# Run on actual display
python3 ha_epaper_dashboard.py
```

## 6. Systemd

```bash
sudo cp epaper-dashboard.service /etc/systemd/system/
sudo cp epaper-dashboard.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now epaper-dashboard.timer
```

## 7. Useful commands

```bash
systemctl status epaper-dashboard.timer          # timer status
journalctl -u epaper-dashboard.service -f        # live logs
sudo systemctl start epaper-dashboard.service    # manual refresh
```

## Status dot legend

- `○` empty = Comfort (18–24°C, humidity < 65%)
- `◉` ring = Temperature out of range
- `●` filled = High humidity (> 65%)
