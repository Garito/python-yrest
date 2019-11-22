from asyncio import get_event_loop

from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorClient

import manual_tests

async def get_table(uri = None):
  client = AsyncIOMotorClient(uri)
  table = client["TF0_6"]["TF0_6"]
  await table.create_index([("path", DESCENDING), ("slug", DESCENDING)], unique = True)
  return table

async def run_it():
  table = await get_table("mongodb://192.168.1.31:27017")
  await manual_tests.user_create_task(table)

get_event_loop().run_until_complete(run_it())
