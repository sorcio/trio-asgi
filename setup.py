import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="trio-asgi",
    version="0.0.1",
    author="Davide Rizzo",
    author_email="sorcio@gmail.com",
    description="experimental trio asgi http protocol server",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/sorcio/trio-asgi",
    packages=setuptools.find_packages(),
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Framework :: Trio",
    ),
    install_requires = [
        'trio==0.4.0',
        'h11==0.8.1',
    ],
)
