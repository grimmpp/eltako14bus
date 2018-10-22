#!/usr/bin/env python3
import setuptools

setuptools.setup(
    name="eltakobus",
    version="0.0.2",
    author="chrysn",
    author_email="chrysn@fsfe.org",
    description="Library for participating in the Eltako Series 14 RS485 bus",
    url="https://gitlab.com/chrysn/eltakobus",
    packages=setuptools.find_packages(),
    extras_require={
        'serial': ['pyserial_asyncio', 'pyserial >= 3.4'],
        'coap': ['aiocoap == 0.4a1'],
        # Not usable yet as it's not exported via an entry point
        'eltakotool': ['pyyaml', 'pyxdg'],
        },
    classifiers=[
        "Programming Language :: Python :: 3",
    ],
)
