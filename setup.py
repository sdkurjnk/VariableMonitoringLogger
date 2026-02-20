from setuptools import setup, Extension

module = Extension(
    name="vml.vml_engine",
    sources=["src/vml/vml_engine.c"],
)

if __name__ == "__main__":
    setup(
        ext_modules=[module],
        zip_safe=False,
    )