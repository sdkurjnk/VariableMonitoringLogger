from setuptools import setup, Extension

module = Extension(
    name="Ocilo.vmlog_engine",
    sources=["src/Ocilo/vmlog_engine.c"],
)

setup(
    ext_modules=[module],
    zip_safe=False,
)