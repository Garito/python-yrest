from typing import Any, List, Dict, Callable
from functools import wraps
from pathlib import PurePath
from dataclasses import dataclass, fields

from dataclasses_jsonschema import JsonSchemaMixin

class Result:
  code = int

@dataclass
class Ok(JsonSchemaMixin, Result):
  ok: bool = True
  code: int = 200

@dataclass
class OkResult(Ok, JsonSchemaMixin):
  result: Dict[str, Any] = None

@dataclass
class OkListResult(Ok, JsonSchemaMixin):
  result: List = None

@dataclass
class Error(JsonSchemaMixin, Result):
  ok: bool = False
  code: int = 500

@dataclass
class ErrorMessage(Error, JsonSchemaMixin):
  message: str = None

def get_url(path: str, slug: str) -> str:
  if path is None or not path:
    return "/"
  elif path == "/":
    return f"/{slug}"
  else:
    return f"{path}/{slug}"

def get_path(url: str) -> Dict[str, str]:
  path = PurePath(url)
  return {"path": str(path.parent), "slug": path.name}

def get_parents_paths(url: str) -> List[Dict[str, str]]:
  if url == "/":
    return [{"path": ""}]

  paths = []
  ppath = PurePath(url)
  while ppath.parent != ppath:
    paths.append({"path": str(ppath.parent), "slug": ppath.name})

    ppath = ppath.parent

  paths.append({"path": ""})

  return paths

def get_parents_urls(url: str) -> List[str]:
  if url == "/":
    return None

  urls = []
  while url:
    urls.append(url)
    url = "/".join(url.split("/")[:-1])
  urls.append("/")

  return urls

def get_model_lists(models, model):
  return [field.name for field in fields(getattr(models, model)) if "model" in field.metadata]

def mount_tree(elements, obj, models):
  from sanic.log import logger
  url = get_url(obj["path"], obj["slug"])
  obj["lists"] = get_model_lists(models, obj["type"])
  for lst in obj["lists"]:
    for idx, child in enumerate(obj[lst]):
      idx2 = None
      for idx2, el in enumerate(elements):
        if el["path"] == url and el["slug"] == child:
          break

      element = elements.pop(idx2)
      obj[lst][idx] = mount_tree(elements, element, models) if get_model_lists(models, element["type"]) else element

  return obj

def can_crash(exception: Exception, returns: JsonSchemaMixin = ErrorMessage, code: int = None, description: str = None) -> Callable:
  if code is None:
    codes = {"ValidationError": 400, "Unauthorized": 401, "NotFound": 404, "URIAlreadyExists": 409, "ExistException": 422}
    code = codes.get(exception.__name__, "")

  if description is None:
    descriptions = {400: "Returns the validation errors", 401: "Raises if the actor has not enought privileges", 404: "Raises when not found"}
    description = descriptions.get(code, "")

  def decorator(func: Callable) -> Callable:
    if not hasattr(func, "__decorators__"):
      func.__decorators__ = {}
    if "can_crash" not in func.__decorators__:
      func.__decorators__["can_crash"] = {}
    func.__decorators__["can_crash"][exception.__name__] = {"returns": returns, "code": code, "description": description}

    @wraps(func)
    async def decorated(*args: List[Any], **kwargs: Dict[str, Any]) -> Any:
      try:
        return await func(*args, **kwargs)
      except exception as e:
        return returns(message = str(e))

    return decorated
  return decorator
