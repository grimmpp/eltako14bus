#!/usr/bin/env python3
import setuptools

extras_require = {
    'serial': ['pyserial-asyncio', 'pyserial >= 3.4'],
    'coap': ['aiocoap == 0.4a1'],
    'esp3': ['enocean >= 0.60.1', 'zeroconf'],
    # Not usable yet as it's not exported via an entry point
    'eltakotool': ['pyyaml', 'pyxdg'],
}

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="eltako14bus",
    version="1.0.0",
    author="chrysn, grimmpp",
    author_email="chrysn@fsfe.org, grimmpp14@gmail.com",
    description="Library for participating in the Eltako Series 14 RS485 bus",
    url="https://github.com/grimmpp/eltako14bus",
    license="LGPL-3.0-or-later",
    # Tests and their hardware fixtures belong in the source repository, not
    # in the installable library distribution.
    packages=setuptools.find_packages(include=["eltakobus", "eltakobus.*"]),
    extras_require=extras_require,
    # Not that there'd be tests, but at least it fetches the right dependencies and syntax checks everything
    tests_require=list(set(sum(extras_require.values(), []))),
    long_description_content_type="text/markdown",
    long_description=long_description,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)",
    ],
)
