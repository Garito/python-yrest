from sys import exc_info
from traceback import format_exception
from os.path import isfile
from types import ModuleType
from functools import wraps
from typing import Any, List, Dict, Union, Callable, ForwardRef, Awaitable
from inspect import getmembers, signature, Signature, isfunction, isclass
from dataclasses import fields, Field
from pathlib import PurePath
from time import perf_counter, process_time
from asyncio import iscoroutinefunction
import re
from datetime import datetime
from mimetypes import guess_type
from email.encoders import encode_base64
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from dataclasses_jsonschema import JsonSchemaMixin, ValidationError

from aiosmtplib import send

from sanic import Sanic, response
from sanic.request import Request
from sanic.log import logger
from sanic.exceptions import abort, NotFound, Unauthorized

from yrest.tree import Tree
from yrest.mongo import MongoJSONEncoder, Mongo
from yrest.openapi import OpenApi
from yrest.utils import Ok, OkResult, OkListResult, Error, ErrorMessage
from yrest.auth import AuthToken

class yJSONEncoder(MongoJSONEncoder):
  def default(self, obj):
    if isclass(obj) or isinstance(obj, (Tree, Mongo)):
      return repr(obj)
    elif isinstance(obj, datetime):
      return obj.isoformat()
    elif isinstance(obj, set):
      return str(obj)
    elif isinstance(obj, (ForwardRef, Field)):
      return str(obj)
    else:
      return MongoJSONEncoder.default(self, obj)

def timed(func):
  @wraps(func)
  async def decorated(*args, **kwargs):
    counter, time = perf_counter(), process_time()

    code = 200
    result = await func(*args, **kwargs)
    if isinstance(result, AuthToken):
      result = result.to_dict()
    elif isinstance(result, (Ok, Error)):
      result = result.to_dict()
      code = result.pop("code")

    result["pref_counter"] = perf_counter() - counter
    result["process_time"] = process_time() - time

    return response.json(result, code)
  return decorated

class ySanic(Sanic):
  def __init__(self, root_model: Tree, models: ModuleType, **kwargs: Dict[str, Any]):
    super().__init__(**kwargs)

    self._root_model = root_model
    self._models = models

    self._introspection = {}
    tree = self._introspect(tree = [])
    # print("\n".join(tree))
    # from json import dumps
    # logger.info(dumps(self._introspection["Group"], indent = 2, cls = yJSONEncoder))

    self._build_routes()

  def _introspect(self, model: Tree = None, analized: List[str] = None, indent: int = 0, tree: List[str] = None):
    if model is None:
      model = self._root_model

    if analized is None:
      analized = []

    if tree is not None:
      tab = "|  " * indent
      tree.append(f"{tab}{model.__name__}")

    if model.__name__ not in analized:
      self._introspection[model.__name__] = self._analize(model)
      analized.append(model.__name__)

    factories = []
    for field in fields(model):
      if "model" in field.metadata:
        factories.append(field.metadata['model'])

        child = getattr(self._models, field.metadata["model"])
        if child != model:
          self._introspect(child, analized, indent + 1, tree)

    if factories:
      self._introspection[model.__name__]["factories"] = factories

    return tree

  def _analize(self, model: Tree) -> Dict[str, str]:
    result = {}

    for name, member in getmembers(model, lambda m: iscoroutinefunction(m) or isfunction(m)):
      sig = signature(member)
      if "request" in sig.parameters.keys():
        result["call" if name == "index" else name] = self._check_signature(model, name, member, sig)

    return result

  def _check_signature(self, model: Tree, name: str, member: Awaitable, sig: Signature) -> Dict[str, str]:
    model_name = model.__name__
    is_root = model == self._root_model
    is_recursive = getattr(model, "_is_recursive", False)

    result = {}

    if hasattr(member, "__doc__") and member.__doc__:
      result["description"] = member.__doc__

    for param_name, param in sig.parameters.items():
      if param_name == "actor":
        result["actor"] = True
      elif param_name == "consume":
        result["consumes"] = getattr(self._models, param.annotation) if isinstance(param.annotation, str) else param.annotation

        urls = []

        consumed = result["consumes"].__name__.lower()
        if name == f"create_{consumed}":
          result["verb"] = "POST"
          if is_root:
            urls.append(f"/new/{consumed}")
          if not is_root or is_recursive:
            urls.append(f"/{{{model_name}_Path}}/new/{consumed}")
        else:
          result["verb"] = "POST" if name == "auth" else "PUT"
          if is_root:
            urls.append(f"/{name}")
          if not is_root or is_recursive:
            urls.append(f"/{{{model_name}_Path}}/{name}")

        result["urls"] = urls

    if "verb" not in result:
      urls = []
      if name == "remove":
        result["verb"] = "DELETE"
        if is_root:
          urls.append("/")
        if not is_root or is_recursive:
          urls.append(f"/{{{model_name}_Path}}/")
      else:
        result["verb"] = "GET"
        if is_root:
            urls.append("/" if name == "index" else f"/{name}")
        if not is_root or is_recursive:
          urls.append(f"/{{{model_name}_Path}}/" if name == "index" else f"/{{{model_name}_Path}}/{name}")
      result["urls"] = urls

    if hasattr(member, "__decorators__"):
      if "can_crash" in member.__decorators__:
        result["can_crash"] = member.__decorators__["can_crash"]

    result["produces"] = sig.return_annotation.__args__ if getattr(sig.return_annotation, "__origin__", False) == Union else sig.return_annotation

    return result

  def _build_routes(self):
    if "call" in self._introspection[self._root_model.__name__]:
      self.add_route(self.dispatcher, "/", ["GET"])
      self.add_route(self._generic_options, "/", ["OPTIONS"])

    if "update" in self._introspection[self._root_model.__name__]:
      self.add_route(self.updater, "/", ["PUT"])

    if hasattr(self, 'ws_endpoint'):
      self.add_websocket_route(self.ws_endpoint, "/ws")

    if "auth" in self._introspection[self._root_model.__name__]:
      self.add_route(self.auth, "/auth", ["POST"])
      self.add_route(self._generic_options, "/auth", ["OPTIONS"])

    if "factories" in self._introspection[self._root_model.__name__]:
      self.add_route(self.factory, "/new/<model>", ["POST"])
      self.add_route(self._generic_options, "/new/<model>", ["OPTIONS"])

    if isinstance(self, OpenApi):
      self.add_route(self.openapi, "/openapi", ["GET"])
      self.add_route(self._generic_options, "/openapi", ["OPTIONS"])

    not_root_models = list(self._introspection.keys())
    not_root_models.pop(not_root_models.index(self._root_model.__name__))
    not_root_factories = list(filter(lambda m: "factories" in self._introspection[m], not_root_models))
    if getattr(self._root_model, "_is_recursive", False) or len(not_root_factories):
      self.add_route(self.factory, "/<path:path>/new/<model>", ["POST"])
      self.add_route(self._generic_options, "/<path:path>/new/<model>", ["OPTIONS"])

    self.add_route(self.dispatcher, "/<path:path>", ["GET"])
    self.add_route(self.updater, "/<path:path>", ["PUT"])
    self.add_route(self.remover, "/<path:path>", ["DELETE"])
    self.add_route(self._generic_options, "/<path:path>", ["OPTIONS"])

  async def get_path(self, url: str, models, tolerance: int = 0) -> Dict[str, Any]:
    if url == "/":
      return await self._root_model.get(self._table, path = "")

    url_ = PurePath(url)
    test = 0
    while url_ != url_.parent:
      doc = await self._root_model._get_doc(self._table, url = str(url_))
      if doc:
        paper = getattr(models, doc["type"])(**doc)
        return paper

      test += 1
      if test > tolerance:
        break

      url_ = url_.parent
      if str(url_) == "/":
        return await self._root_model.get(self._table, path = "")

    raise NotFound(f"{url} not found")

  @timed
  async def auth(self, request: Request):
    if request.json is None:
      return ErrorMessage(message = f"Data must be provided",  code = 400)

    root = await self._root_model.get(self._table, path = "")
    auth = self._models.Auth(**request.json)
    return await root.auth(request, auth)

  @timed
  async def updater(self, request: Request, path: str = None):
    if request.json is None:
      return ErrorMessage(message = f"Data must be provided",  code = 400)

    path_ = f"/{path or ''}"
    try:
      paper = await self.get_path(path_, self._models, 1)
      paper._table = request.app._table
    except NotFound as e:
      return ErrorMessage(message = e.args[0], code = 404)

    url = paper.get_url()
    member = path_.replace(url, "")[1:] if url > "/" else path_[1:]
    if not member:
      member = "update"

    perm = await self._models.Permission.get(self._table, context = paper.type, name = member)
    token = AuthToken.get(request.headers)
    actor = await token.get_actor(self._table, self.config["JWT_SECRET"], self._models.User)
    # actor = await self._models.User.get(self._table, slug = "garito")
    if not perm or not await perm.allows(actor, paper):
      return ErrorMessage(message = "Unauthorized", code = 401)

    args = [request]
    _introspection = self._introspection[paper.type]["call" if member == "index" else member]
    if "actor" in _introspection:
      args.append(actor)

    consumes = _introspection.get("consumes", None)
    try:
      model = consumes(**request.json)
      args.append(model)
    except TypeError as e:
      return ErrorMessage(message = f"Validation error: {e}", code = 400)

    try:
      result = await getattr(paper, member)(*args)
      if isinstance(result, Tree):
        result = result.to_plain_dict()
      return OkListResult(result = result, code = 200) if isinstance(result, list) else  OkResult(result = result, code = 200)
    except Exception as e:
      message = format_exception(*exc_info()) if request.app.config.get("DEBUG", False) else str(e)
      for line in message:
        logger.error(line)
      return ErrorMessage(message = message, code = 400)

  @timed
  async def dispatcher(self, request, path: str = None):
    path_ = f"/{path or ''}"
    try:
      paper = await self.get_path(path_, self._models, 1)
      paper._table = request.app._table
    except NotFound as e:
      return ErrorMessage(message = e.args[0], code = 404)

    url = paper.get_url()
    member = path_.replace(url, "")[1:] if url > "/" else path_[1:]
    if not member:
      member = "index"

    perm = await self._models.Permission.get(self._table, context = paper.type, name = "call" if member == "index" else member)
    token = AuthToken.get(request.headers)
    actor = await token.get_actor(self._table, self.config["JWT_SECRET"], self._models.User)
    # actor = await self._models.User.get(self._table, slug = "garito")
    if not perm or not await perm.allows(actor, paper):
      return ErrorMessage(message = "Unauthorized", code = 401)

    args = [request]

    _introspection = self._introspection[paper.type]["call" if member == "index" else member]
    if "actor" in _introspection:
      args.append(actor)

    try:
      result = await getattr(paper, member)(*args)
      if isinstance(result, Tree):
        result = result.to_plain_dict()
      return OkListResult(result = result, code = 200) if isinstance(result, list) else  OkResult(result = result, code = 200)
    except Exception as e:
      message = format_exception(*exc_info()) if request.app.config.get("DEBUG", False) else str(e)
      for line in message:
        logger.error(line)
      return ErrorMessage(message = message, code = 500)

  @timed
  async def factory(self, request, model, path: str = None):
    try:
      consume = getattr(self._models, model.capitalize()).from_dict(request.json)
    except TypeError as e:
      return ErrorMessage(message = e.args, code = 400)

    path_ = f"/{path or ''}"
    try:
      paper = await self.get_path(path_, self._models, 0)
      paper._table = request.app._table
    except NotFound as e:
      return ErrorMessage(message = e.args[0], code = 404)

    perm = await self._models.Permission.get(self._table, context = paper.type, name = f"create_{model}")
    token = AuthToken.get(request.headers)
    actor = await token.get_actor(self._table, self.config["JWT_SECRET"], self._models.User)
    # actor = await self._models.User.get(self._table, slug = "garito")
    if not await perm.allows(actor, paper):
      return ErrorMessage(message = "Unauthorized", code = 401)

    member = getattr(paper, f"create_{model}", None)
    if member is None:
      member = self._generic_factory
      args = [request, paper, actor, consume]
    else:
      known = {"request": request, "actor": actor, "consume": consume}
      args = [known[param] for param in signature(member).parameters if param in known.keys()]

    try:
      result = await member(*args)
      if isinstance(result, Tree):
        result = result.to_plain_dict()
      return OkResult(result = result, code = 201)
    except DuplicateKeyError:
      return ErrorMessage(message = f"{consume.name} already exists @ {paper.name}", code = 409)

  @timed
  async def remover(self, request: Request, path: str = None):
    path_ = f"/{path or ''}"
    try:
      paper = await self.get_path(path_, self._models, 0)
      paper._table = request.app._table
    except NotFound as e:
      return ErrorMessage(message = e.args[0], code = 404)

    perm = await self._models.Permission.get(self._table, context = paper.type, name = "remove")
    token = AuthToken.get(request.headers)
    actor = await token.get_actor(self._table, self.config["JWT_SECRET"], self._models.User)
    # actor = await self._models.User.get(self._table, slug = "garito")
    if not await perm.allows(actor, paper):
      return ErrorMessage(message = "Unauthorized", code = 401)

    member = getattr(paper, "remove")
    if member is None:
      member = self._generic_remover
      args = [request, paper, actor]
    else:
      args = [request, actor]

    try:
      result = await member(*args)
      return OkListResult(result = result)
    except Exception as e:
      message = format_exception(*exc_info()) if request.app.config.get("DEBUG", False) else str(e)
      for line in message:
        logger.error(line)
      return ErrorMessage(message = message, code = 500)

  async def _generic_factory(self, request: Request, paper: Mongo, actor, consume, update_roles: bool = True):
    # this could be executed in a mongo transaction
    await paper.create_child(consume, request.app._models)

    # This assumes the actor should be the owner
    # Here we could implement a mechanism to allow delegation (when a user makes and action on behalf another user)
    # Or perhaps is better to delegate this decision to the model
    roles = actor.roles
    roles.append(f"owner@{consume.get_url()}")
    if update_roles:
      await actor.update(request.app._models, roles = roles)

    return {"object": consume.to_plain_dict(), "actor_roles": roles}

  async def _generic_remover(self, request: Request, paper: Mongo, actor, update_roles: bool = True):
    # this assumes that the actor is the owner. Meh...
    roles = actor.roles
    roles.pop(roles.index(f"owner@{paper.get_url()}"))

    await paper.delete(request.app._models)
    await actor.update(request.app._models, roles = roles)

    return roles

  async def notify(self, request, notification: str, **kwargs) -> bool:
    member = getattr(self, notification, None)
    if member is None:
      raise NotFound(f"The server hasn't {notification} as notification")

    return await member(request, **kwargs)

  async def send_email(self, to: str, subject: str, from_: str = None, text: str = None, html: str = None, attachments: Any = None) -> bool:
    if from_ is None:
        from_ = self.config["MAIL_SENDER"]

    if self.config.get("DEBUG_NOTIFICATIONS", False):
      logger.info(to)
      logger.info(from_)
      logger.info(subject)
      logger.info(text)
      logger.info(html)
      logger.info(attachments)
    else:
      if text is None and html is None:
        raise ValidationError("Neither text nor html has been provided")
      elif text is not None and html is not None:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(text))
        message.attach(MIMEText(html, "html"))
      elif html is not None and attachments:
        message = MIMEMultipart()
        message.attach(MIMEText(html, "html"))
      elif text is None:
        message = MIMEText(html, "html")
      else:
        message = MIMEText(text)

      if attachments:
        for idx, attachment in enumerate(attachments):
          if isfile(attachment):
            m_type = guess_type(attachment)[0]
            main_type, subtype = m_type.split('/', 1)
            attach = MIMEBase(main_type, subtype)
            with open(attachment, 'rb') as f:
              attach.set_payload(f.read())
            encode_base64(attach)
            attach.add_header("Content-Disposition", "attachment", filename = attachment)
            attach.add_header("X-Attachment-Id", str(idx))
            attach.add_header("Content-ID", f"<{idx}>")
            message.attach(attach)
          else:
            logger.warn(f"{attachment} is not a file")

      message["From"] = from_
      message["To"] = to
      message["Subject"] = subject

      return await send(message, hostname = self.config["MAIL_SERVER"], port = self.config["MAIL_PORT"], **self.config.get("MAIL_ARGS", {}))

  async def _generic_options(self, request, *args, **kwargs):
    return response.text("", status = 204)

  async def _allow_origin(self, request, response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Access-Control-Allow-Origin, Access-Control-Allow-Headers, Origin, X-Requested-With, Content-Type, Authorization"

class MongoServer(ySanic):
  def __init__(self, root_model: Tree, models: ModuleType, **kwargs: Dict[str, Any]):
    super().__init__(root_model, models, **kwargs)

    self.register_listener(self._set_table, 'before_server_start')
    self.register_listener(self._close_table, 'before_server_stop')

  async def _set_table(self, app, loop):
    app._client = AsyncIOMotorClient(app.config["MONGO_URI"], io_loop = loop)
    db = app._client[app.config["MONGO_DB"]]
    app._table = db[app.config.get("MONGO_TABLE", app.config["MONGO_DB"])]

    if app.config.get("MONGO_GRIDFS", False):
      app._gridfs = AsyncIOMotorGridFSBucket(db)

    app._table.create_index("created_at", expireAfterSeconds = 1800)
    app._table.create_index([("path", ASCENDING), ("slug", ASCENDING)], unique = True)

    root = await app._root_model.get(app._table, path = "")
    if root:
      await root._rebuild_sec(app)

  def _close_table(self, app, loop):
    app._client.close()
