# SwitcheOn Home Assistant integration

This custom integration reads the SwitcheOn account API and exposes a switch
for each channel, plus temperature and online state. Channel switches send
commands through the SwitcheOn API; switch state follows the box's reported
state and changes after the box checks in. Live check-ins arrive over SwitcheOn's
SignalR websocket.

## Install

Copy the `custom_components/switcheon` folder into the `custom_components`
folder in your Home Assistant configuration directory. Restart Home Assistant,
then go to **Settings → Devices & Services → Add Integration**, search for
**SwitcheOn**, and enter the email and password used by the SwitcheOn phone app.

The integration polls account data every two minutes to keep online status
current and maintains a SignalR websocket for real-time box check-ins. SwitcheOn
login tokens last eight hours; the integration logs in again when the account
request indicates that a token has expired. Credentials are stored by Home
Assistant in the config entry.

## Entities

For each box present when the integration is first set up, it creates:

- `switch.*`: one toggle per channel, named from the box's channel names when
  available. The reported state reflects the box, and `command_pending`
  indicates a queued request awaiting the next check-in.
- `sensor.*_temperature`: device temperature in the unit configured on the box.
- `binary_sensor.*_online`: API-reported online state.

## Notes

- The API uses `currentStatus` as reported state; `pendingStatus` is only a
  request waiting to be applied. The integration converts the bitmask to
  separate channel switches.
- Online/offline state is obtained from account polling because SwitcheOn does
  not push online changes.
- Boxes added to the account after integration setup require reloading the
  integration to create their entities.
- API reference: https://github.com/SeanMollet/SwitcheOn-API

## Local account/API diagnostic

To compare the account lookup from your Mac, run `python3 local_api_check.py`
from this project folder and open the local page it launches. The page submits
credentials only to the SwitcheOn HTTPS API. The server binds to `127.0.0.1`,
does not log form contents, and displays only the returned account and box
identifiers. It does not save credentials or API tokens. Stop it with Ctrl+C.
