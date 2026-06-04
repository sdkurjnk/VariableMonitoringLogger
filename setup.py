from setuptools import setup, Extension

module = Extension(
    name="vmlog.vmlog_engine",
    sources=["src/vmlog/vmlog_engine.c"],
)

setup(
    ext_modules=[module],
    zip_safe=False,
)