from unittest.mock import Mock

from mongo import MongoBase

class TestMongo:
  def test_get_doc(self):
    mongo_mock = Mock()
    print(MongoBase._get_doc(mongo_mock, path = "/garito"))
    print(mongo_mock)