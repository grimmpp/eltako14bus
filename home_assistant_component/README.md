To enable this component, add lines like the following to your config.yaml:

~~~~~~~~
eltako:
  device: /dev/ttyS0
~~~~~~~~

Devices on the bus will be integrated automatically; devices that are not bus
participants will need additional EnOcean integration to have their telegrams
displayed, no matter whether they arrived on the wire or over the air.
