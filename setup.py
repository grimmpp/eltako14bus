#!/usr/bin/env python3
import setuptools

extras_require = {
    'serial': ['pyserial-asyncio', 'pyserial >= 3.4'],
    # aiocoap 0.4a1 uses the removed asyncio.coroutine API and is not
    # compatible with the Python versions supported by this project.
    'coap': ['aiocoap >= 0.4.17, < 1'],
    'discovery': ['zeroconf'],
    # Not usable yet as it's not exported via an entry point
    'eltakotool': ['pyyaml', 'pyxdg'],
}

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="eltako14bus",
    version="2.0.0rc1",
    author="chrysn, grimmpp",
    author_email="chrysn@fsfe.org, grimmpp14@gmail.com",
    description="Library for participating in the Eltako Series 14 RS485 bus",
    url="https://github.com/grimmpp/eltako14bus",
    license="LGPL-3.0-or-later",
    # Tests and their hardware fixtures belong in the source archive, not in
    # the installable library wheel.
    packages=setuptools.find_packages(include=["eltakobus", "eltakobus.*"]),
    python_requires=">=3.10",
    extras_require=extras_require,
    long_description_content_type="text/markdown",
    long_description=long_description,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
)
