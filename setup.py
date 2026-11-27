from setuptools import find_packages, setup

setup(
    name="turbofetch",
    version="1.0.0",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "PySide6>=6.8.0",
        "httpx[socks]>=0.28.0",
        "yt-dlp>=2026.0",
        "imageio-ffmpeg>=0.8.0",
        "mutagen>=1.48.0",
    ],
    entry_points={
        "console_scripts": [
            "turbofetch=turbofetch.app.main:main",
        ],
    },
)
