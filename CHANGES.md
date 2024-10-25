# Release Notes
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

## 0.0.74 Exception handling in serial thread extended

## 0.0.73 Added functions for discovery of devices
* Added functions for discovery of devices
* fixed blocking sleep function

## 0.0.68 Added helper functions for AddressExpression

## 0.0.67 updates b2s so that other objects of the same address can be printed as well

## 0.0.66 Fixed EEP A5-04-02 and added default values for EEPs

## 0.0.65 Added command to query for gateway base id and version

## 0.0.64 Refactored A5_10_06 (Heating and Cooling)
* Refactored A5_10_06 (Heating and Cooling)
* Cleaned up devices.py

## 0.0.63 Write sender with EEP F6-02-01 into actuator improved.
* Writing sender into actuator list with EEP F6-02-01/02. default: left push button

## 0.0.62 Added device FSR14M-2x 

## 0.0.61 Added EEP F6-01-01 for one-/push-button switch

## 0.0.59 Added EPP A5-10-03 for thermostat

## 0.0.57 Improved FTD14 handling

## 0.0.56 Added Sensor support for FTD14
- Sensors/Memory list of FTD14 can be read out

## 0.0.55 Added device FTD14
- Added device Telegram Duplicator (FTD14) which is a bus gateway

## 0.0.54 Added device FHK14 and F4HK14
- Added device FHK14 and F4HK14
- Changed slightly discovery mechanism of devices. (More than one type id can be added to identify device type)

## 0.0.53 Detection for FDG14 added
- Improvements to detect devices and added detection for FDG14 (DALI)

## 0.0.52 Unit Tests introduced
- Added initial unit test 
- Added test executing as part of release process

## 0.0.51
- Added EEP A5-30-01 and A5-30-03 for Digital Inputs

## 0.0.50
- Improved device programmability and added FAE14SSR and FMZ14

## 0.0.49
- Bug fixes/cleanup in EEPs

## 0.0.48
- Added EEP A5-0-03

## 0.0.47
- Made A5-08-01 compatible and fixed but

## 0.0.46
- added auto_reconnect as optional
- added more configuration possibility to RS485SerialInterfaceV2
- automatic release pipeline added

## 0.0.42
- Stabilized unlock and lock of FAM14

## 0.0.41
- Added get_all_sensors for FSB14 and FMZ14

## 0.0.40
- fixed message overflow in fgw14-usb. RS485 bus is working with 9600 and baudrate can be set to 57600 for FGW14-USB. When sending many message (ca. 12) in a row the buffer of FGW14-USB is flowing over.
- Added EEP H5-3F-7F for ensuring switches are programmed for cover (FSB14)

## 0.0.39
- status changed handler to serial connector added

## 0.0.38
- reconnect function for serial communication added

## 0.0.37
- extentions for management tooling

## 0.0.36
- fix of occupancy sensor (EEP A5-07-01)

## 0.0.35
- Status messages for temperature and humidity sensor (EEP A5-04-01) added
- Status messages for occupancy sensor (EEP A5-07-01) added

## 0.0.34
- Corrected telegram signals for window handle positions.

## 0.0.33
- new serial communication added which is running in a thread instead of event loop and which can automatically recover after connection loss.

## 0.0.32
- Changes for devices and sensor discovery added.

## 0.0.31
- Added parameter for baud rate.

## 0.0.30
- Status message for temperature actuator/sensor added. (EEP A5-10-06 and A5-10-12)
- Status message for air quality sensor added. (EEP A5-09-0C)

## 0.0.28
- Temperature and Humidity Sensor for EEP A5-04-02 added

## 0.0.27
- Bug Fix - Out of Memory: Range of device memory was not fitting.
- GFVS codes added so that automation software can use triggers in a generic manner.

## 0.0.26
- Refactoring and introduction of FGW14 communication

## 0.0.9
- Transferred from [GitLab eltakobus](https://gitlab.com/chrysn/eltakobus) library project to GitHub 