from unittest import TestCase

from pymongo import MongoClient

from sanic.testing import SanicTestClient

from app import create_app
from config import Testing

class TestDispatcher(TestCase):
  def setUp(self):
    self._app = create_app(Testing)
    self._client = MongoClient(self._app.config["MONGO_URI"])
    self._table = self._client[self._app.config["MONGO_DB"]][self._app.config["MONGO_TABLE"]]

  def tearDown(self):
    self._client.close()
