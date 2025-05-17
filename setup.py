#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

setup(
    name="crypto_trader",
    version="1.0.0",
    description="Automated cryptocurrency trading bot with Google Sheets integration",
    author="Shaumne",
    author_email="devshaumne@gmail.com",
    packages=find_packages(),
    install_requires=[
        "requests>=2.25.0",
        "python-telegram-bot>=13.0",
        "gspread>=5.0.0",
        "oauth2client>=4.1.3",
        "python-dotenv>=0.15.0",
        "aiohttp>=3.8.0"
    ],
    entry_points={
        "console_scripts": [
            "crypto-trader=main:main",
        ],
    },
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Office/Business :: Financial :: Investment",
    ],
) 