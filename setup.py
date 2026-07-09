from setuptools import setup, Extension

module = Extension(
    name="oscilo.oscilo_engine",
    sources=["src/oscilo/oscilo_engine.c"],
)

setup(
    ext_modules=[module],
    zip_safe=False,
)