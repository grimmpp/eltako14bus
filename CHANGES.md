# Release Notes
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

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