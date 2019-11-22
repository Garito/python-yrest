from setuptools import setup, find_packages

def readme():
  with open("README.md") as f:
    return f.read()

setup(
  name = "python-yrest",
  version = "0.2.0",
  description = "Python backend for yRest",
  long_description = readme(),
  long_description_content_type='text/markdown',
  classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Plugins",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3"
  ],
  keywords = "full stack framework trees",
  url = "https://github.com/Garito/python-yrest",
  author = "Garito",
  author_email = "garito@gmail.com",
  license = "MIT",
  packages = find_packages(),
  python_requires=">=3.7",
  install_requires = ["python-slugify", "motor", "dataclasses-jsonschema", "sanic", "sanic-jinja2", "pyJWT"],
  extras_requires = {
    "dev": ["pytest", "Faker", "pytest-cov"]
  },
  test_suite = "pytest"
)
