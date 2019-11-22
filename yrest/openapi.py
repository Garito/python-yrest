from inspect import getmro
from typing import Union, List, Dict, Any
import re
from dataclasses import fields

from sanic import response
from sanic.request import Request

from dataclasses_jsonschema import JsonSchemaMixin, SchemaType

from yrest.tree import Tree

class OpenApi():
  def v3(self):
    result = {"openapi": "3.0.1"}

    c_keys = list(self.config.keys())
    if "OA_INFO" in c_keys:
      result["info"] = self.config["OA_INFO"]

    if "OA_SERVER_DESCRIPTION" in c_keys:
      result["servers"] = [{"url": self.config["SERVER_NAME"], "description": self.config["OA_SERVER_DESCRIPTION"]}]

    result["paths"] = self._paths()

    schemas = self._correct_schemas(JsonSchemaMixin.all_json_schemas(schema_type = SchemaType.OPENAPI_3))
    result["components"] = {"x-root": self._root_model.__name__, "schemas": schemas}
    if hasattr(self, "_params"):
      result["components"]["parameters"] = self._params

    return result

  def _paths(self):
    from sanic.log import logger
    regex = re.compile("\/new\/\w+$")

    result = self._own_path()
    for name, data in self._introspection.items():
      paths = {}
      model = getattr(self._models, name)
      for e_name, endpoint in data.items():
        if e_name != "factories":
          for path, path_data in self._path(model, e_name, endpoint).items():
            if not regex.search(path):
              for verb, verb_data in path_data.items():
                if path not in paths:
                  paths[path] = {}
                paths[path][verb] = verb_data

      if "factories" in data.keys():
        result.update(self._factories(model, data))

      if paths:
        result.update(paths)

    return result

  def _path(self, model: Tree, e_name: str, e_data: Dict[str, Union[str, Dict]]) -> Dict[str, Union[str, Dict]]:
    regex = re.compile("/{\w+_Path}")
    path = {}
    verb = e_data["verb"].lower()
    e_keys = e_data.keys()
    for url in e_data["urls"]:
      p = {}
      p[url] = {}
      p[url][verb] = {}

      if regex.match(url):
        p[url][verb]["operationId"] = f"{model.__name__}/{e_name}"
        p[url][verb]["parameters"] = self._parameters(model, url)
      else:
        p[url][verb]["operationId"] = f"Root/{e_name}"

      if "can_crash" in e_keys or "produces" in e_keys:
        p[url][verb]["responses"] = {}

        if "produces" in e_keys:
          p[url][verb]["responses"][200] = {}
          if "description" in e_data:
            p[url][verb]["responses"][200]["description"] = e_data["description"]

          p[url][verb]["responses"][200].update(self._content(e_data["produces"]))

        if "can_crash" in e_keys:
          for error in e_data["can_crash"].values():
            p[url][verb]["responses"][error["code"]] = {}
            if "description" in error:
              p[url][verb]["responses"][error["code"]]["description"] = error["description"]

            p[url][verb]["responses"][error["code"]].update(self._content(error["returns"]))

      if "consumes" in e_keys:
        p[url][verb]["requestBody"] = self._content(e_data["consumes"])

      path.update(p)

    return path

  def _factories(self, model: Tree, data):
    okResultContent = self._content(getattr(self._models, "OkResult"))["content"]
    errorMessageContent = self._content(getattr(self._models, "ErrorMessage"))["content"]

    urls = []
    if model == self._root_model:
      urls.append("/")

    if model != self._root_model or model.__name__ in data["factories"]:
      urls.append(f"/{{{model.__name__}_Path}}/")

    regex = re.compile("/{\w+_Path}")
    paths = {}
    for factory in data["factories"]:
      fact = factory.lower()
      for url in urls:
        path = f"{url}new/{fact}"
        paths[path] = {"post": {}}
        if regex.match(url):
          paths[path]["post"]["operationId"] = f"{model.__name__}/create_{fact}"
          paths[path]["post"]["parameters"] = self._parameters(model, url)
        else:
          paths[path]["post"]["operationId"] =  f"Root/create_{fact}"
        paths[path]["post"]["requestBody"] = self._content(getattr(self._models, factory))

        paths[path]["post"]["responses"] = {
          200: {
            "description": f"Returns the data of the new {fact}",
            "content": okResultContent
          },
          400: {
            "description": f"Returns the errors if the {fact} can't be created with the provided data",
            "content": errorMessageContent
          },
          401: {
            "description": f"Returns Unauthorized if the actor is not allowed to perform the creation of the {fact}",
            "content": errorMessageContent
          },
          409: {
            "description": f"Returns an error if there is already a model with the same url",
            "content": errorMessageContent
          }
        }

    return paths

  def _own_path(self) -> Dict[str, Union[str, Dict]]:
    result = {
      "/openapi": {
        "get": {
          "responses": {
            "200": {
              "description": "Returns the app's OpenAPI definition",
              "content": {
                "application/json": {
                  "schema": {"type": "object"}
                }
              }
            }
          }
        }
      }
    }
    return result

  def _parameters(self, model: Tree, url: str):
    if not hasattr(self, "_params"):
      self._params = {}

    name = model.__name__
    param_name = f"{name}_Path"

    if param_name not in self._params.keys():
      path = {
        "name": param_name,
        "in": "path",
        "description": f"The URL of the {name} with out the first slash",
        "required": True,
        "schema": {"type": "string"}
      }

      self._params[param_name] = path

    return [self._ref(param_name, "parameters")]

  def _content(self, model: Tree, mime: str = "application/json"):
    content = {}
    content[mime] = {"schema": self._ref(model[1].__name__ if isinstance(model, tuple) else model.__name__)}
    return {"content": content}

  def _ref(self, model: Tree, context: str = "schemas"):
    return {"$ref": f"#/components/{context}/{model}"}

  def _correct_schemas(self, schemas):
    models = {model.__name__: model for model in JsonSchemaMixin.__subclasses__()}
    needed_props = {"maximum", "exclusiveMaximum", "minimum", "exclusiveMinimum", "maxLength", "minLength"}

    for schema in schemas.keys():
      if hasattr(models[schema], "__x_schema__"):
        schemas[schema].update({f"x-{key}": value for key, value in models[schema].__x_schema__.items()})
        schemas[schema][f"x-features"] = [feat.__name__ for feat in getmro(models[schema])]

      for field in fields(models[schema]):
        if hasattr(field, "metadata") and field.metadata :
          for prop in needed_props & set(field.metadata.keys()):
            schemas[schema]["properties"][field.name][prop] = field.metadata[prop]

          if "model" in field.metadata:
            schemas[schema]["properties"][field.name]["x-model"] = field.metadata["model"]

    return schemas

  def openapi(self, request: Request) -> Dict[str, str]:
    """Returns tha API's OpenAPI definition"""
    return response.json(self.v3())
