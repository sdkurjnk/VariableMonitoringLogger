from setuptools import setup, Extension, find_packages

module = Extension(
    name="vml.vml_engine",
    sources=["src/vml/vml_engine.c"], 
)

setup(
    name="vml",
    version="1.0.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    ext_modules=[module],
    author="sdkurjnk",
    zip_safe = False,
    classifiers= [
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent"
    ],
    description="A Variable Monitoring Logger with C-Engine and Visualizer",
    python_requires=">=3.11",
)