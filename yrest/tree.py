from typing import NewType, List, Tuple, Dict, Any, Union
from json import dumps, loads, JSONEncoder, JSONDecoder
from dataclasses import dataclass, Field
from datetime import datetime
from enum import Enum

from dataclasses_jsonschema import JsonSchemaMixin, FieldEncoder
from dataclasses_jsonschema.field_types import DateTimeFieldEncoder

from slugify import slugify

from yrest.utils import get_url

Email = NewType("Email", str)
class EmailField(FieldEncoder):
  @property
  def json_schema(self):
    return {"type": "string", "format": "email"}

JsonSchemaMixin.register_field_encoders({Email: EmailField()})

Phone = NewType("Phone", str)
class PhoneField(FieldEncoder):
  @property
  def json_schema(self):
    return {"type": "string", "format": "phone"}

JsonSchemaMixin.register_field_encoders({Phone: PhoneField()})

Password = NewType("Password", str)
class PasswordField(FieldEncoder):
  @property
  def json_schema(self):
    return {"type": "string", "format": "password"}

JsonSchemaMixin.register_field_encoders({Password: PasswordField()})

Url = NewType("Url", str)
class UrlField(FieldEncoder):
  @property
  def json_schema(self):
    return {"type": "string", "format": "url"}

JsonSchemaMixin.register_field_encoders({Url: UrlField()})

File = NewType("File", str)
class FileField(FieldEncoder):
  @property
  def json_schema(self):
    return {"type": "string", "format": "byte"}

JsonSchemaMixin.register_field_encoders({File: FileField()})

JsonSchemaMixin.register_field_encoders({datetime: DateTimeFieldEncoder()})

class Recursive:
  _is_recursive = True

class TreeBase:
  def __sluger__(self, values = None, fields: bool = False) -> Union[Tuple, str]:
    if fields:
      return ("name",)
    elif values:
      return values.get('name', self.name)
    else:
      return self.name

  def __post_init__(self):
    if self.type is None:
      self.type = self.__class__.__name__

    if self.slug is None:
      self.slug = slugify(self.__sluger__())

  def _composition(self) -> Dict[str, Any]:
    return {c.__name__: c for c in self.__class__.__bases__}

  def get_url(self) -> str:
    return get_url(self.path, self.slug)

  def to_plain_dict(self, encoder: JSONEncoder = None) -> Dict[str, Any]:
    if encoder is None and hasattr(self, "_encoder"):
      encoder = self._encoder.default if isinstance(self._encoder, Field) else self._encoder

    result = loads(self.to_json(cls = encoder))

    for exclude in getattr(self, "__exclude__", []):
      result.pop(exclude)

    return result

@dataclass
class Tree(TreeBase):
  path: str = None
  slug: str = None
  type: str = None
