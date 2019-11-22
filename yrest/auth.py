from os import urandom
from binascii import hexlify
from hashlib import pbkdf2_hmac
from secrets import compare_digest

from typing import Any, List, Tuple, Dict, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from bson import ObjectId

import jwt

from sanic.request import Request
from sanic.exceptions import Unauthorized

from dataclasses_jsonschema import JsonSchemaMixin, JsonSchemaMeta

from yrest.tree import Tree, Email, Password
from yrest.mongo import Mongo
from yrest.utils import Ok, ErrorMessage

def generate_password_hash(password: str, salt = None, iterations: int = 50000) -> str:
  salt = hexlify(urandom(8)) if salt is None else str.encode(salt)
  password = str.encode(password)
  hex_hash = hexlify(pbkdf2_hmac("sha256", password, salt, iterations))

  return f"pbkdf2:sha256:{iterations}${salt.decode('utf-8')}${hex_hash.decode('utf-8')}"

def check_password_hash(hashed: str, password: str) -> bool:
  _, salt, _ = hashed.split("$")
  return compare_digest(generate_password_hash(password, salt), hashed)

@dataclass
class AuthToken(JsonSchemaMixin):
  access_token: str

  @classmethod
  def get(cls, headers, key: str = "Authorization", prefix: str = "Bearer") -> Dict[str, str]:
    return cls(headers[key].replace(f"{prefix} ", "") if key in headers else None)

  @classmethod
  def generate(cls, payload: Dict[str, Any], secret: str, exp: int = 30, algo: str = "HS256") -> str:
    if "exp" not in payload:
      payload["exp"] = datetime.utcnow() + timedelta(minutes = exp)

    return cls(jwt.encode(payload, secret, algo).decode())

  def verify(self, secret: str, algos: List[str] = None) -> bool:
    try:
      return jwt.decode(self.access_token, secret, algorithms = algos or ["HS256"])
    except (jwt.DecodeError, jwt.ExpiredSignatureError):
      return False

  async def get_actor(self, table, secret, user_class):
    payload = self.verify(secret)
    if payload:
      return await user_class.get(table, _id = ObjectId(payload["user_id"]))

@dataclass
class Auth(JsonSchemaMixin):
  """The authentication model"""
  email: Email = field(metadata = JsonSchemaMeta(title = "Enter your email", extensions = {'label': 'Email', 'placeholder': 'email@example.com'}))
  password: Password = field(metadata = JsonSchemaMeta(title = "Enter your password. Click on the eye to reveal it (take care of not revealing it to others)", extensions = {'label': 'Password'}))

  @classmethod
  def secure(cls, password):
    return password if password.startswith('pbkdf2:sha256:') else generate_password_hash(password)

  async def authorize(self, table, secret, user_class):
    user = await user_class.get(table, email = self.email)
    if user and check_password_hash(user.password, self.password):
      return AuthToken.generate({"user_id": str(user._id)}, secret)

@dataclass
class ForgotPasswordRequest(JsonSchemaMixin):
  email: Email = field(metadata = JsonSchemaMeta(title = "Enter your email", extensions = {'label': 'Email', 'placeholder': 'email@example.com'}))

@dataclass
class NeedsEmail:
  email: Email

@dataclass
class PasswordResetToken(JsonSchemaMixin, Tree, Mongo, NeedsEmail):
  code: UUID = field(default_factory = uuid4)
  created_at: datetime = field(default_factory = datetime.utcnow)

  def __sluger__(self, values = None, fields: bool = False) -> Union[Tuple, str]:
    if fields:
      return ("email",)
    elif values:
      return values.get('email', self.email)
    else:
      return self.email

@dataclass
class ResetPassword(JsonSchemaMixin):
  code: UUID
  password: Password = field(metadata = JsonSchemaMeta(title = "Enter the new password. Click on the eye to reveal it (take care of not revealing it to others)", extensions = {'label': 'Password'}))

class IsAuth:
  async def auth(self, request: Request, consume: Auth) -> AuthToken:
    """Authorizes email and password"""
    token = await consume.authorize(self._table, request.app.config["JWT_SECRET"], request.app._models.User)
    return token if token else ErrorMessage("The autentication has failed", 401)

  async def forgot_password(self, request: Request, consume: ForgotPasswordRequest) -> Ok:
    """Sends a password recovery mail to the specified mail"""
    from sanic.log import logger

    user = await request.app._models.User.get(self._table, email = consume.email)
    if not user:
      return ErrorMessage("Unregistered email", 404)

    prevToken = await PasswordResetToken.get(self._table, email = consume.email)
    if prevToken:
      return ErrorMessage("Already requested", 429)

    token = PasswordResetToken(consume.email, path = "/")
    token._table = self._table
    await token.create()

    await request.app.notify(request, 'forgot_password', actor = user, token = token)

  async def reset_password(self, request: Request, consume: ResetPassword) -> Ok:
    """Reset the password authenticating the actor the forgot password token"""
    from sanic.log import logger
    logger.info(consume)
