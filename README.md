# Pulsar for Home Assistant

Lets [Pulsar](https://pulsar.sun-driven.com) run your appliances (boilers, heat pumps,
heaters, anything on a smart plug) when electricity is cheapest, using the switches and
plugs you already have in Home Assistant, including IKEA, Zigbee, Z-Wave, Shelly and Tuya
devices.

**Nothing in your home is exposed to the internet.** Pulsar never connects to your Home
Assistant. This integration connects out to Pulsar once a minute, so it works without Nabu
Casa, port forwarding or a tunnel, and behind any router or mobile connection.

## Install

1. In HACS, open the menu (⋮) → **Custom repositories**, add
   `https://github.com/mjkapkan/pulsar-home-assistant` with type **Integration**.
2. Find **Pulsar** in HACS, download it, and restart Home Assistant.

## Connect

1. In Pulsar, open an appliance → **Linked Devices** → **Home Assistant** → **Link Account**.
   Pulsar shows an 8-character code, valid for 15 minutes.
2. In Home Assistant: **Settings → Devices & services → Add integration → Pulsar**, and
   enter the code.
3. Back in Pulsar, the Home Assistant card lists your switches, lights, fans and input
   booleans within a minute. Link the ones that power the appliance and save.

## What it does

Every minute the integration:

- tells Pulsar which switchable entities you have (`switch`, `light`, `fan`,
  `input_boolean`) with their name, room and state. Configuration and diagnostic entities
  (child lock, LED, auto-update switches), hidden and disabled entities are left out;
- receives the state Pulsar wants for each entity you linked, and switches it when that
  state **changes**.

Rules it follows:

- **Your manual changes win until the next scheduled change.** If you switch a plug by
  hand, Pulsar does not switch it back until its schedule changes.
- **Switches from the Pulsar app** arrive within a minute, and are dropped if they arrive
  more than two minutes late.
- **Failsafe:** if Pulsar cannot be reached for 15 minutes, every entity Pulsar controls is
  switched **on**, as if Pulsar were not there. Pulsar never leaves a device off because it
  went away. When Pulsar is back, its schedule resumes.
- Disconnecting in Pulsar stops the integration; Home Assistant then asks you to reconnect
  with a new code.

## Privacy

Sent to Pulsar: the entity ID, name, room, domain and on/off/unavailable state of switchable
entities, your Home Assistant's name and version, and the result of each switch Pulsar asked
for. Nothing else: no other entities, no history, no location, no credentials. Pulsar gets no
access to your Home Assistant.

## Troubleshooting

- **"That code is not valid or has expired"**: codes work once and for 15 minutes. Get a new
  one in Pulsar.
- **Devices do not appear in Pulsar**: they arrive with the next heartbeat (within a minute).
  Check that the entity is a switch, light, fan or input boolean, and is not hidden, disabled
  or a configuration entity.
- **Debug logs**: add to `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.pulsar: debug
  ```
