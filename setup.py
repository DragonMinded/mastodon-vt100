from distutils.core import setup


setup(
    name="mastodon-vt100",
    version="0.2.0",
    description="VT-100 Mastodon Client",
    author="DragonMinded",
    license="Public Domain",
    packages=[
        "masto",
    ],
    install_requires=[
        req for req in open("requirements.txt").read().split("\n") if len(req) > 0
    ],
    python_requires=">3.8",
    entry_points={
        "console_scripts": [
            "mastodon-vt100 = masto.__main__:cli",
        ],
    },
)
