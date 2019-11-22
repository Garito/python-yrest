FROM python:3.7.4-buster

RUN pip install -U setuptools pip && \
    pip install python-slugify motor sanic sanic-jinja2 pyJWT aiosmtplib
# dataclasses-jsonschema
RUN pip install git+https://github.com/Garito/dataclasses-jsonschema.git

RUN pip install pytest Faker pytest-cov

COPY . /usr/src/python-yrest
RUN pip install -e /usr/src/python-yrest

RUN adduser --disabled-password --gecos '' appuser
WORKDIR /usr/src/app
USER appuser

CMD [ "python", "app.py" ]
