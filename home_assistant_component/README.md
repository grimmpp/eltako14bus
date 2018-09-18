To enable this component, add lines like the following to your config.yaml:

~~~~~~~~
eltako:
  device: /dev/ttyS0
~~~~~~~~

Devices on the bus will be integrated automatically.

Devices that are not on the bus can be made to send teach-in telegrams. As soon
as the teach-in telegrams are received, its sensor values are added to home
assistant. As those additions are not permanent, a notice is shown on the home
screen on how to make those devices available across reboots without sending
teach-in messsages again.

Features
========

Recognized on the bus:

* FUD14 and FSG14 1-10V (as dimmable lights)
* FSR14 with 1, 2, or 4 slots (as switches)
* FWZ14-65A

Recognized over the air:

* Various temperature sensors (A5-02-01 to A5-02-1B)
* Various humidity sensors (A5-04-01 and A5-05-02)
* Direcional buttons (RPS)

  Those are not exposed as sensors as they are in practice taught into actuators, would only clutter the display, and just because home assistant received a telegram from them doesn't mean that any of its recipient devices actually got the message).

  Note that devices like the FTS14EM appear just as such devices because they do not fully participate on the bus, and send regular radio telegrams from their own address space.

* FGW14MS

  Those devices participate on the bus, but report their status only using telegrams whose ID depends on the switch state which can be read from the bus. For the purpose of reading it, the FGW14MS on the bus is a no-op entity, and has to be taught in like any other radio object.

TBD:

* FSR14-LED (probably FSR14-ish)

* FSB14 (needs actual hardware)
* FDG14 (needs actual hardware, works different from FUD)
