# systemd Service

This repo ships a generic template unit:

- `systemd/epaper-dashboard@.service`

It runs for any user with `%i` and defaults to user-home paths.

## Install

```bash
sudo install -m 644 systemd/epaper-dashboard@.service /etc/systemd/system/epaper-dashboard@.service
sudo systemctl daemon-reload
sudo systemctl enable --now epaper-dashboard@dash.service
```

Replace `dash` with your Linux username.

## Optional overrides

Create `/etc/default/epaper-dashboard`:

```bash
APP_DIR=/custom/path/epaper-ha-dashboard
EPD_LIB_PATH=/custom/path/e-Paper/RaspberryPi_JetsonNano/python/lib
MODE=clock-daemon
EXTRA_ARGS=--clock-data-every-min 10 --clock-full-every 120
```

## Logs and control

```bash
systemctl status epaper-dashboard@dash.service
journalctl -u epaper-dashboard@dash.service -f
sudo systemctl restart epaper-dashboard@dash.service
```

## Notes

- The service uses `Restart=always`.
- Legacy timer-based units are not required for current daemon mode.
