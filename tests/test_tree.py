from json import dumps, JSONEncoder, JSONDecoder
from dataclasses import dataclass

import pytest

from faker import Faker

from slugify import slugify

from dataclasses_jsonschema import JsonSchemaMixin

from tree import Tree

class IntEncoder(JSONEncoder):
  def default(self, obj):
    print("default")
    print(obj)
    if isinstance(obj, int):
      return str(obj)
    else:
      JSONEncoder.default(self, obj)

class IntDecoder(JSONDecoder):
  def __init__(self, *args, **kwargs):
    JSONDecoder.__init__(self, object_hook = self.object_hook, *args, **kwargs)

  def object_hook(self, obj):
    try:
      result = {}
      for key, value in obj.items():
        try:
          result[key] = int(value)
        except:
          result[key] = value
      return result
    except:
      return obj

class Feature1:
  pass

class Feature2:
  pass

class ComposedTree(Tree, Feature1, Feature2):
  pass

@dataclass
class JsonSchemaTree(JsonSchemaMixin, Tree):
  pass

@dataclass
class HasName:
  name: str

@dataclass
class NamedTree(JsonSchemaMixin, Tree, HasName):
  pass

@dataclass
class HasInt:
  integer: int

class IntBase():
  _encoder: JSONEncoder = IntEncoder
  _decoder: JSONDecoder = IntDecoder

@dataclass
class IntTree(JsonSchemaMixin, IntBase, Tree, HasInt):
  pass

@pytest.fixture
def faker():
  return Faker()

@pytest.fixture
def full_tree(faker):
  data = {"path": f"/{faker.uri_path()}", "slug": faker.slug(), "type": faker.word()}
  return data, Tree(**data)

@pytest.fixture
def composed():
  return ComposedTree()

@pytest.fixture
def schema_tree(faker):
  data = {"path": f"/{faker.uri_path()}", "slug": faker.slug(), "type": faker.word()}
  return data, JsonSchemaTree(**data)

@pytest.fixture
def named_tree(faker):
  data = {"name": faker.word()}
  return data, NamedTree(**data)

@pytest.fixture
def int_tree(faker):
  data = {"integer": faker.pyint()}
  return data, IntTree(**data)

class TestTree:
  def test_empty(self):
    tree = Tree()
    assert tree.type == "Tree"
    assert tree.path is None
    assert tree.slug is None

  def test_full(self, full_tree):
    assert full_tree[1].type == full_tree[0]["type"]
    assert full_tree[1].path == full_tree[0]["path"]
    assert full_tree[1].slug == full_tree[0]["slug"]

  def test_named(self, named_tree):
    assert named_tree[1].name == named_tree[0]["name"]
    assert named_tree[1].slug == slugify(named_tree[0]["name"])

  def test_additional_arguments(self, faker):
    with pytest.raises(TypeError):
      Tree(**faker.pydict(3))

  def test_composition(self, composed):
    assert composed._composition() == {"Tree": Tree, "Feature1": Feature1, "Feature2": Feature2}

  def test_get_url_root(self, faker):
    tree = Tree("", faker.word())
    assert tree.get_url() == "/"

  def test_get_url_root_child(self, faker):
    slug = faker.word()
    tree = Tree("/", slug)
    assert tree.get_url() == f"/{slug}"

  def test_get_url(self, full_tree):
    assert full_tree[1].get_url() == f"{full_tree[0]['path']}/{full_tree[0]['slug']}"

  def test_from_json(self, full_tree):
    tree = JsonSchemaTree.from_json(dumps(full_tree[0]))
    assert tree.path == full_tree[0]["path"]
    assert tree.slug == full_tree[0]["slug"]
    assert tree.type == full_tree[0]["type"]

  def test_from_json_with_class_decoder(self, faker):
    integer = faker.pyint()
    tree = IntTree.from_json(dumps({"integer": str(integer)}, cls = IntEncoder))
    assert tree.integer == integer

  def test_to_json(self, schema_tree):
    assert schema_tree[1].to_json() == dumps(schema_tree[0])

  def test_to_json_with_class_encoder(self, int_tree):
    print(int_tree[1].to_json())
