# Tapo L630 for Home Assistant

A HACS custom integration for locally controlling TP-Link Tapo L630 smart
bulbs. It is based on the KLAP implementation in
[homebridge-tapo-smart-light](https://github.com/say4n/homebridge-tapo-smart-light).

## Features

- Local polling and control; the Tapo cloud is not used
- Power and brightness control
- Hue and saturation color control
- Color temperature control from 2500 K to 6500 K
- Automatic recovery when the bulb's encrypted session expires
- UI-based setup through Home Assistant

## Requirements

- Home Assistant 2024.4 or newer
- A Tapo L630 already configured in the Tapo app
- The bulb and Home Assistant on the same local network
- The bulb's local IP address, preferably reserved in your router's DHCP
  settings
- Your Tapo account email and password

The credentials are used only to authenticate directly with the bulb over the
local network.

## HACS installation

1. Open HACS in Home Assistant.
2. Select **Integrations**, open the three-dot menu, and choose
   **Custom repositories**.
3. Add `https://github.com/say4n/hacs-tapo-l630` as an **Integration**.
4. Install **Tapo L630** and restart Home Assistant.
5. Go to **Settings > Devices & services**, select **Add Integration**, and
   search for **Tapo L630**.
6. Enter the bulb's IP address and your Tapo credentials.

## Manual installation

Copy `custom_components/tapo_l630` into the `custom_components` directory in
your Home Assistant configuration directory, restart Home Assistant, and add
the integration from **Settings > Devices & services**.

## Troubleshooting

- Reserve the bulb's IP address in your router so the config entry remains
  valid after a DHCP lease change.
- Ensure guest Wi-Fi or client isolation is not blocking Home Assistant from
  reaching the bulb.
- Tapo credentials are case-sensitive. Use the same credentials as the Tapo
  mobile app.

## License

MIT
