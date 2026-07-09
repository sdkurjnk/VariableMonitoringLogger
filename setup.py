from setuptools import setup, Extension

module = Extension(
    name="oscilo.vmlog_engine",
    sources=["src/oscilo/vmlog_engine.c"],
)

setup(
    ext_modules=[module],
    zip_safe=False,
)