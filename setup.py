from setuptools import setup, Extension

module = Extension(
    name="ocilo.vmlog_engine",
    sources=["src/ocilo/vmlog_engine.c"],
)

setup(
    ext_modules=[module],
    zip_safe=False,
)