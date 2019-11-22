from types import ModuleType
from typing import Any, List, Dict, Union
from inspect import getmembers, isclass
from pathlib import PurePath
from json import JSONEncoder
from decimal import Decimal
from dataclasses import dataclass, fields, field, asdict
from enum import Enum

from bson import ObjectId, Decimal128
from pymongo import UpdateOne, DeleteOne, DeleteMany
from motor.motor_asyncio import AsyncIOMotorCollection

from slugify import slugify

from dataclasses_jsonschema import JsonSchemaMixin, FieldEncoder

from yrest.tree import Tree
from yrest.utils import get_url

class ChildrenAbiguity(Exception):
  pass

class ObjectIdField(FieldEncoder):
  def to_wire(self, value):
    return str(value)

  def to_python(self, value):
    return ObjectId(value)

  @property
  def json_schema(self):
    return {"type": "string"}

class DecimalField(FieldEncoder):
  def to_wire(self, value):
    return value.to_decimal()

  def to_python(self, value):
    return Decimal128(str(value))

  @property
  def json_schema(self):
    return {"type": "number"}

JsonSchemaMixin.register_field_encoders({ObjectId: ObjectIdField()})
JsonSchemaMixin.register_field_encoders({Decimal128: DecimalField()})

class MongoJSONEncoder(JSONEncoder):
  def default(self, obj):
    if isinstance(obj, ObjectId):
      return str(obj)
    elif isinstance(obj, Decimal):
      return float(obj)
    elif isinstance(obj, Decimal128):
      return float(obj.to_decimal())
    else:
      return JSONEncoder.default(self, obj)

class MongoBase:
  _table: AsyncIOMotorCollection = field(default = None, repr = False, compare = False, hash = False)
  _encoder: JSONEncoder = field(default = MongoJSONEncoder, init = False, repr = False, compare = False, hash = False)

  @classmethod
  def _decompose_url(self, url: str) -> Dict[str, str]:
    if url == "/":
      return {"path": ""}
    else:
      _url = PurePath(url)
      return {"path": str(_url.parent), "slug": _url.name}

  @classmethod
  async def _get_doc(cls, table: AsyncIOMotorCollection, **query: Dict[str, Any]) -> Dict[str, Any]:
    sort = query.pop("sort") if "sort" in query else None
    if "url" in query:
      query.update(cls._decompose_url(query.pop("url")))

    if sort:
      result = await table.find(query).sort(sort).to_list(1)
      return result[0] if len(result) else None
    else:
      return await table.find_one(query)

  @classmethod
  async def _get_docs(cls, table: AsyncIOMotorCollection, **query: Dict[str, Any]) -> List[Dict[str, Any]]:
    sort = query.pop("sort") if "sort" in query else None
    if "url" in query:
      query.update(cls._decompose_url(query.pop("url")))

    if sort:
      return await table.find(query).sort(sort).to_list(None)
    else:
      return await table.find(query).to_list(None)

  @classmethod
  async def get(cls, table: AsyncIOMotorCollection, **query: Dict[str, Any]) -> 'Mongo':
    if "type" not in query:
      query["type"] = cls.__name__

    doc = await cls._get_doc(table, **query)
    if doc:
      obj = cls(**doc)
      obj._table = table

      return obj
    else:
      return doc

  @classmethod
  async def gets(cls, table: AsyncIOMotorCollection, **query: Dict[str, Any]) -> 'Mongo':
    if "type" not in query:
      query["type"] = cls.__name__

    docs = await cls._get_docs(table, **query)
    if docs:
      objs = []
      for doc in docs:
        obj = cls(**doc)
        obj._table = table
        objs.append(obj)

      return objs
    else:
      return docs

  async def create(self, **kwargs: Dict[str, Any]):
    if not kwargs:
      kwargs = {
        key: value.value if isinstance(value, Enum) else value
        for key, value in asdict(self).items()
        if value is not None
      }

    result = await self._table.insert_one(kwargs)
    self._id = result.inserted_id

  async def update(self, models: ModuleType, **kwargs: Dict[str, Any]):
    actions = []

    if set(self.__sluger__(fields = True)) & set(kwargs.keys()):
      indexer = kwargs.pop("indexer") if "indexer" in kwargs else "slug"
      kwargs["slug"] = slugify(self.__slugger__(kwargs))
      parent = await self.ancestors(models, True)
      if parent:
        update_parent = {}
        self_class = self.__class__.__name__
        for field in fields(parent):
          if "model" in field.metadata and field.metadata["model"] == self_class:
            brothers = getattr(parent, field.name)
            key = getattr(self, "_id" if field.type == List[ObjectId] else indexer)
            brothers[brothers.index(key)] = kwargs[indexer]
            update_parent[field.name] = brothers

      url = self.get_url()
      new_url = get_url(kwargs.get("path", self.path), kwargs.get(indexer, getattr(self, indexer)))
      async for child in self._table.find({"path": {"$regex": f"^{url}"}}):
        actions.append(UpdateOne({"_id": child["_id"]}, {"$set": {"path": child["path"].replace(url, new_url, 1)}}))
      if update_parent:
        actions.append(UpdateOne({"_id": parent._id}, {"$set": update_parent}))

    actions.insert(0, UpdateOne({"_id": self._id}, {"$set": kwargs}))
    async with await self._table.database.client.start_session() as s:
      async with s.start_transaction():
        await self._table.bulk_write(actions)

    for key, val in kwargs.items():
      setattr(self, key, val)

  async def delete(self, models: ModuleType, indexer: str = "slug"):
    children = {}
    parent = await self.ancestors(models, True)
    if parent:
      self_class = self.__class__.__name__
      for field in fields(parent):
        if "model" in field.metadata and field.metadata["model"] == self_class:
          childs = getattr(parent, field.name)
          childs.remove(getattr(self, "_id" if field.type == List[ObjectId] else indexer))
          children[field.name] = childs

    actions = [DeleteOne({"_id": self._id}), DeleteMany({"path": {"$regex": f"^{self.get_url()}"}})]
    if children:
      actions.append(UpdateOne({"_id": parent._id}, {"$set": children}))
    async with await self._table.database.client.start_session() as s:
      async with s.start_transaction():
        await self._table.bulk_write(actions)

    self.id_ = None

  async def create_child(self, child: 'Mongo', models: ModuleType, as_: str = None, indexer: str = None):
    if as_ is None:
      child_class = child.__class__.__name__
      children = list(filter(lambda f: "model" in f.metadata and f.metadata["model"] == child_class, fields(self)))
      if len(children) > 1:
        children_names = list(map(lambda c: c.name, children))
        raise ChildrenAbiguity(f"{self.__class__.__name__} ({self.name}) defines {', '.join(children_names[:-1])} and {children_names[-1]} that can store {child_class}. Use as_ parameter to disambiguate it")
      elif len(children) == 1:
        as_ = children[0].name
        if children[0].type == List[ObjectId]:
          indexer = "_id"
      else:
        raise ChildrenAbiguity(f"{self.__class__.__name__} ({self.name}) can't store {child.__class__.__name__}")

    child._table = self._table
    children = getattr(self, as_)
    update = {}
    async with await self._table.database.client.start_session() as s:
      async with s.start_transaction():
        child.path = self.get_url()
        await child.create()
        if indexer:
          children.append(getattr(child, indexer))
        elif hasattr(child, "__indexer__"):
          children.append(getattr(child, child.__indexer__))
        else:
          children.append(child.slug)
        update[as_] = children
        await self.update(models, **update)

  async def ancestors(self, models: ModuleType, parent = False) -> Union['Mongo', List['Mongo']]:
    url = PurePath(self.get_url())
    if str(url) == "/":
      return None
    else:
      query = [{"path": str(parent.parent), "slug": parent.name} for parent in url.parents if str(parent) != "/"]
      query.append({"path": ""})
      if parent:
        query = query[0:1]

      ancestors = []
      async for doc in self._table.find({"$or": query}).sort([("path", -1)]):
        ancestor = getattr(models, doc["type"])(**doc)
        ancestor._table = self._table
        if parent:
          return ancestor
        ancestors.append(ancestor)

      return ancestors

  async def children(self, models: Union[ModuleType, List[Tree]], sort = None,  extra = None):
    url = self.get_url()
    if isinstance(models, list):
      models_ = {model.__name__: model for model in models}
    else:
      models_ = {model[0]: model[1] for model in getmembers(models, lambda m: isclass(m) and issubclass(m, Mongo))}
    models_names = models_.keys()

    results = {}
    for field in fields(self):
      model_name = field.metadata.get("model", None)
      if model_name and model_name in models_names:
        indexes = getattr(self, field.name)

        if field.type == List[ObjectId]:
          match, indexer = ({"_id": {"$in": indexes}}, "$_id")
        else:
          match, indexer = ({"type": model_name, "path": url}, "$slug")
        match = {"$match": match}
        if extra:
          match.update(extra[model_name] if model_name in extra else extra)

        if sort is None:
          addOrder = {"$addFields": {"__order": {"$indexOfArray": [indexes, indexer]}}}
          sort = {"$sort": {"__order": 1}}
          aggregation = [match, addOrder, sort]
        else:
          aggregation = [match, sort[model_name] if model_name in sort else sort]

        results[field.name] = []
        model = models_[model_name]
        async for doc in self._table.aggregate(aggregation):
          doc.pop("__order", None)
          results[field.name].append(model(**doc))

    return results

@dataclass
class Mongo(MongoBase):
  _id: ObjectId = None
