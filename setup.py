# setup.py
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="flowcompass",
    version="0.1.3",
    author="Krishna Prasad",
    author_email="krishnapd883@gmail.com",
    description="A tool to generate flow diagrams from source code",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/krishnapd1/flowcompass",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",  
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
    entry_points={
        'console_scripts': [
            'flowcompass=flowcompass.main:main',
        ],
    },
    install_requires=[],
)
